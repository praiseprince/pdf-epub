from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRYCLOUDFLARE_RE = re.compile(r"https://[-a-zA-Z0-9.]+\.trycloudflare\.com")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local PDF-to-EPUB app.")
    parser.add_argument("--host", default=os.environ.get("LOCAL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LOCAL_PORT", "8000")))
    parser.add_argument("--tunnel", action="store_true", help="Start a temporary Cloudflare URL inside the app.")
    backend = parser.add_mutually_exclusive_group()
    backend.add_argument("--mlx", dest="mlx", action="store_true", default=None, help="Use the MLX-VLM Apple GPU service.")
    backend.add_argument("--cpu", dest="mlx", action="store_false", help="Use CPU PaddleOCR-VL.")
    parser.add_argument("--mlx-port", type=int, default=8111)
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically.")
    parser.add_argument("--reload", action="store_true", help="Run uvicorn in reload mode for development.")
    args = parser.parse_args()
    if args.mlx is None:
        args.mlx = _default_mlx()
    return args


def main() -> int:
    args = parse_args()
    _preflight(args)

    local_url = f"http://{args.host}:{args.port}"
    env = os.environ.copy()
    env["LOCAL_HOST"] = args.host
    env["LOCAL_PORT"] = str(args.port)
    env.setdefault("LOCAL_PADDLE_MODE", "local")
    env["LOCAL_START_MLX"] = "true" if args.mlx else "false"
    env["LOCAL_START_TUNNEL"] = "true" if args.tunnel else "false"

    processes: list[subprocess.Popen[str]] = []

    try:
        if args.mlx:
            mlx_url = f"http://127.0.0.1:{args.mlx_port}/"
            env["LOCAL_PADDLE_VL_BACKEND"] = "mlx-vlm-server"
            env["LOCAL_PADDLE_VL_SERVER_URL"] = mlx_url
            env.setdefault("LOCAL_PADDLE_VL_API_MODEL_NAME", "PaddlePaddle/PaddleOCR-VL-1.6")
            env.setdefault("LOCAL_PADDLE_VL_MAX_CONCURRENCY", "4")
            print(f"MLX-VLM server requested at {mlx_url}")
        else:
            env["LOCAL_PADDLE_VL_BACKEND"] = ""
            env["LOCAL_PADDLE_VL_SERVER_URL"] = ""

        app_cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "local_app.main:app",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
        if args.reload:
            app_cmd.extend(["--reload", "--reload-dir", "local_app"])
        app_proc = _start_process("app", app_cmd, env=env)
        processes.append(app_proc)

        if _wait_for_http(f"{local_url}/login", timeout=45):
            print(f"Local app: {local_url}/login")
            if not args.no_open:
                webbrowser.open(f"{local_url}/login")
        else:
            print(f"Local app is starting at {local_url}/login")

        if args.tunnel:
            print("Cloudflare tunnel requested. Log in locally and open the Runtime panel for the URL.")

        print("Press Ctrl-C in this terminal to stop the app.")
        while any(proc.poll() is None for proc in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping local app...")
    finally:
        _stop_processes(processes)
    return 0


def _preflight(args: argparse.Namespace) -> None:
    if not (ROOT / ".env").exists() and not (ROOT / ".env.local").exists():
        raise SystemExit("Create .env first. Use .env.example as the template.")
    if not (ROOT / ".venv").exists():
        raise SystemExit("Missing .venv. Run the README setup first.")
    if not (ROOT / "node_modules").exists():
        raise SystemExit("Missing node_modules. Run npm install first.")
    if not shutil.which("pdfinfo") or not shutil.which("pdftoppm"):
        raise SystemExit("Missing Poppler tools. Install poppler first.")
    if args.tunnel and not shutil.which("cloudflared"):
        raise SystemExit("Missing cloudflared. Install it with: brew install cloudflared")
    if args.mlx:
        paddle_python = _paddle_python()
        probe = subprocess.run(
            [str(paddle_python), "-c", "import mlx_vlm"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            raise SystemExit(
                "Missing mlx-vlm in the PaddleOCR environment. Install it with:\n"
                f"{paddle_python} -m pip install 'mlx-vlm>=0.3.11'"
            )


def _paddle_python() -> Path:
    value = os.environ.get("LOCAL_PADDLE_PYTHON", ".venv_paddleocr/bin/python")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise SystemExit(f"Missing PaddleOCR Python at {path}")
    return path


def _start_process(
    name: str,
    cmd: list[str],
    *,
    env: dict[str, str],
    url_holder: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip()
            if not text:
                continue
            if url_holder is not None:
                match = TRYCLOUDFLARE_RE.search(text)
                if match:
                    url_holder["url"] = match.group(0)
            print(f"[{name}] {text}", flush=True)

    threading.Thread(target=pump, daemon=True).start()
    return proc


def _default_mlx() -> bool:
    return platform.system() == "Darwin" and platform.machine() in {"arm64", "aarch64"}


def _wait_for_http(url: str, *, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if response.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _stop_processes(processes: list[subprocess.Popen[str]]) -> None:
    for proc in reversed(processes):
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + 10
    for proc in reversed(processes):
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        if proc.poll() is None:
            proc.kill()
    for proc in reversed(processes):
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
