from __future__ import annotations

import plistlib
import json
import shlex
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


LAUNCHERS = [
    ("PDF to EPUB", []),
    ("PDF to EPUB MLX", ["--mlx"]),
    ("PDF to EPUB Tunnel", ["--tunnel"]),
    ("PDF to EPUB Tunnel MLX", ["--mlx", "--tunnel"]),
]


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    for name, args in LAUNCHERS:
        _write_command(name, args)
    _write_app("PDF to EPUB", [])
    print(f"Wrote launchers to {DIST}")
    return 0


def _write_command(name: str, args: list[str]) -> None:
    target = DIST / f"{name}.command"
    command = _shell_command(args)
    target.write_text(
        "#!/bin/zsh\n"
        "set -e\n"
        f"cd {shlex.quote(str(ROOT))}\n"
        f"exec {command}\n",
        encoding="utf-8",
    )
    _make_executable(target)


def _write_app(name: str, args: list[str]) -> None:
    app_dir = DIST / f"{name}.app"
    contents = app_dir / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)

    executable = macos / "launcher"
    terminal_command = f"cd {shlex.quote(str(ROOT))}; {_shell_command(args)}"
    executable.write_text(
        "#!/bin/zsh\n"
        "/usr/bin/osascript <<'OSA'\n"
        "tell application \"Terminal\"\n"
        "  activate\n"
        f"  do script {json.dumps(terminal_command)}\n"
        "end tell\n"
        "OSA\n",
        encoding="utf-8",
    )
    _make_executable(executable)

    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": "launcher",
        "CFBundleIdentifier": "local.pdf-epub.launcher",
        "CFBundleName": name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)


def _shell_command(args: list[str]) -> str:
    parts = [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "run-app.py"), *args]
    return " ".join(shlex.quote(part) for part in parts)


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    raise SystemExit(main())
