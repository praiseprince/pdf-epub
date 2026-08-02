from __future__ import annotations

import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MLX_URL = "http://127.0.0.1:8111/"
DEFAULT_MLX_MODEL = "PaddlePaddle/PaddleOCR-VL-1.6"
TRYCLOUDFLARE_RE = re.compile(r"https://[-a-zA-Z0-9.]+\.trycloudflare\.com")


class RuntimeErrorMessage(RuntimeError):
    pass


@dataclass
class ManagedProcess:
    proc: subprocess.Popen[str] | None = None
    logs: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def managed_running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def stop(self) -> None:
        proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        with self._lock:
            self.proc = None

    def _start_process(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        with self._lock:
            self.logs = []
            self.proc = subprocess.Popen(
                cmd,
                cwd=cwd or ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            threading.Thread(target=self._pump_logs, daemon=True).start()

    def _append_log(self, text: str) -> None:
        with self._lock:
            self.logs.append(text)
            self.logs = self.logs[-80:]

    def _last_log(self, fallback: str) -> str:
        with self._lock:
            return self.logs[-1] if self.logs else fallback

    def _pump_logs(self) -> None:
        proc = self.proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            text = line.strip()
            if text:
                self._append_log(text)


@dataclass(kw_only=True)
class TunnelManager(ManagedProcess):
    local_url: str = ""
    url: str = ""

    def start(self, *, wait_seconds: int = 20) -> dict[str, object]:
        if self.managed_running:
            return self.status()
        executable = shutil.which("cloudflared")
        if not executable:
            raise RuntimeErrorMessage("cloudflared is not installed.")

        self.url = ""
        self._start_process([executable, "tunnel", "--url", self.local_url])
        deadline = time.monotonic() + max(0, wait_seconds)
        while time.monotonic() < deadline:
            status = self.status()
            if status["url"] or not status["running"]:
                break
            time.sleep(0.25)
        status = self.status()
        if not status["running"] and not status["url"]:
            raise RuntimeErrorMessage(self._last_log("Cloudflare tunnel did not start."))
        return status

    def stop(self) -> dict[str, object]:
        super().stop()
        with self._lock:
            self.url = ""
        return self.status()

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "running": self.managed_running,
                "url": self.url,
                "logs": self.logs[-20:],
            }

    def _append_log(self, text: str) -> None:
        match = TRYCLOUDFLARE_RE.search(text)
        with self._lock:
            if match:
                self.url = match.group(0)
            self.logs.append(text)
            self.logs = self.logs[-80:]


@dataclass(kw_only=True)
class MlxServerManager(ManagedProcess):
    settings: Settings | None = None

    def start(self, *, wait_seconds: int = 12) -> dict[str, object]:
        if self.status()["running"]:
            return self.status()
        if self.settings is None:
            raise RuntimeErrorMessage("MLX server settings are unavailable.")

        paddle_python = _paddle_python(self.settings)
        _ensure_mlx_vlm(paddle_python)
        port = _port_for_url(_mlx_url(self.settings))
        self._start_process(
            [
                str(paddle_python),
                "-m",
                "mlx_vlm.server",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "INFO",
            ],
            cwd=ROOT,
        )

        deadline = time.monotonic() + max(0, wait_seconds)
        while time.monotonic() < deadline:
            status = self.status()
            if status["available"] or not status["managed"]:
                break
            time.sleep(0.5)
        status = self.status()
        if not status["running"]:
            raise RuntimeErrorMessage(self._last_log("MLX server did not start."))
        return status

    def stop(self) -> dict[str, object]:
        super().stop()
        return self.status()

    def status(self) -> dict[str, object]:
        available = _server_available(_mlx_url(self.settings)) if self.settings else False
        with self._lock:
            managed = self.managed_running
            return {
                "running": managed or available,
                "managed": managed,
                "available": available,
                "url": _mlx_url(self.settings) if self.settings else DEFAULT_MLX_URL,
                "logs": self.logs[-20:],
            }


def runtime_payload(settings: Settings, tunnel: TunnelManager, mlx_server: MlxServerManager) -> dict[str, object]:
    return {
        "ocr_backend": ocr_backend(settings),
        "mlx_configured": bool(settings.local_paddle_vl_server_url or settings.local_paddle_vl_backend),
        "mlx_server_url": _mlx_url(settings),
        "mlx_server": mlx_server.status(),
        "tunnel": tunnel.status(),
    }


def ocr_backend(settings: Settings) -> str:
    return "mlx" if settings.local_paddle_vl_backend == "mlx-vlm-server" else "cpu"


def set_ocr_backend(settings: Settings, backend: str) -> str:
    if backend == "mlx":
        settings.local_paddle_vl_backend = "mlx-vlm-server"
        settings.local_paddle_vl_server_url = settings.local_paddle_vl_server_url or DEFAULT_MLX_URL
        settings.local_paddle_vl_api_model_name = settings.local_paddle_vl_api_model_name or DEFAULT_MLX_MODEL
        settings.local_paddle_vl_max_concurrency = settings.local_paddle_vl_max_concurrency or 4
        settings.local_start_mlx = True
        return "mlx"
    if backend == "cpu":
        settings.local_paddle_vl_backend = ""
        settings.local_paddle_vl_server_url = ""
        settings.local_start_mlx = False
        return "cpu"
    raise RuntimeErrorMessage("Unsupported OCR backend.")


def _mlx_url(settings: Settings | None) -> str:
    if settings is None:
        return DEFAULT_MLX_URL
    return settings.local_paddle_vl_server_url or DEFAULT_MLX_URL


def _paddle_python(settings: Settings) -> Path:
    path = settings.local_paddle_python.expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise RuntimeErrorMessage(f"Missing PaddleOCR Python at {path}")
    return path


def _ensure_mlx_vlm(python: Path) -> None:
    probe = subprocess.run(
        [str(python), "-c", "import mlx_vlm"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if probe.returncode != 0:
        raise RuntimeErrorMessage(
            "Missing mlx-vlm in the PaddleOCR environment. Install it with: "
            f"{python} -m pip install 'mlx-vlm>=0.3.11'"
        )


def _port_for_url(url: str) -> int:
    parsed = urlparse(url)
    if parsed.port:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


def _server_available(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = _port_for_url(url)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False
