from __future__ import annotations

import plistlib
import shutil
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP_NAME = "PDF to EPUB"
APP_DIR = DIST / f"{APP_NAME}.app"
BUNDLE_ROOT = APP_DIR / "Contents" / "Resources" / "pdf-epub"

REQUIRED_ITEMS = [
    "local_app",
    "scripts",
    "node_modules",
    ".venv",
    ".venv_paddleocr",
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "README.md",
    "LICENSE",
    "NOTICE",
    ".env.example",
]

PRIVATE_ENV_FILES = [".env", ".env.local"]
OPTIONAL_ITEMS = ["tmp/kcc-source-work"]
SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def main() -> int:
    _preflight()
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)

    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    _copy_runtime()
    _write_launcher()
    _write_info_plist()
    _warn_about_kcc()
    print(f"Wrote {APP_DIR}")
    print("Job data will live in ~/Library/Application Support/PDF to EPUB/data")
    return 0


def _preflight() -> None:
    missing = [name for name in REQUIRED_ITEMS if not (ROOT / name).exists()]
    if missing:
        raise SystemExit(f"Missing required package inputs: {', '.join(missing)}")


def _copy_runtime() -> None:
    for name in REQUIRED_ITEMS:
        source = ROOT / name
        target = BUNDLE_ROOT / name
        _copy_item(source, target)

    for name in PRIVATE_ENV_FILES:
        source = ROOT / name
        if source.exists():
            _copy_item(source, BUNDLE_ROOT / name)

    for name in OPTIONAL_ITEMS:
        source = ROOT / name
        if source.exists():
            _copy_item(source, BUNDLE_ROOT / name)


def _copy_item(source: Path, target: Path) -> None:
    if source.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, symlinks=True, ignore=_ignore_for(source))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _ignore_for(source: Path):
    def ignore(_directory: str, names: list[str]) -> set[str]:
        skipped = set(names).intersection(SKIP_DIR_NAMES)
        if source.name == "tmp":
            skipped.update(name for name in names if name != "kcc-source-work")
        return skipped

    return ignore


def _write_launcher() -> None:
    macos = APP_DIR / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    executable = macos / "launcher"
    executable.write_text(
        "#!/bin/zsh\n"
        "set -e\n"
        'CONTENTS_DIR="${0:A:h:h}"\n'
        'APP_ROOT="$CONTENTS_DIR/Resources/pdf-epub"\n'
        'DATA_DIR="$HOME/Library/Application Support/PDF to EPUB/data"\n'
        'PYTHON="$APP_ROOT/.venv/bin/python"\n'
        'RUNNER="$APP_ROOT/scripts/run-app.py"\n'
        'mkdir -p "$DATA_DIR"\n'
        "/usr/bin/osascript <<OSA\n"
        "set appRoot to \"$APP_ROOT\"\n"
        "set dataDir to \"$DATA_DIR\"\n"
        "set pythonPath to \"$PYTHON\"\n"
        "set runnerPath to \"$RUNNER\"\n"
        "tell application \"Terminal\"\n"
        "  activate\n"
        "  do script \"cd \" & quoted form of appRoot & \"; export LOCAL_DATA_DIR=\" & quoted form of dataDir & \"; exec \" & quoted form of pythonPath & \" \" & quoted form of runnerPath\n"
        "end tell\n"
        "OSA\n",
        encoding="utf-8",
    )
    _make_executable(executable)


def _write_info_plist() -> None:
    contents = APP_DIR / "Contents"
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": "launcher",
        "CFBundleIdentifier": "local.pdf-epub.app",
        "CFBundleName": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "2",
        "LSMinimumSystemVersion": "13.0",
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)


def _warn_about_kcc() -> None:
    bundled_kcc = BUNDLE_ROOT / "tmp" / "kcc-source-work"
    if shutil.which("kcc-c2e") or bundled_kcc.exists():
        return
    print("Warning: Comic mode needs kcc-c2e on PATH or tmp/kcc-source-work before packaging.")


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    raise SystemExit(main())
