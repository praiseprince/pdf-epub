from __future__ import annotations

import argparse
import json
import os
import plistlib
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP_NAME = "PDF to EPUB"
VERSION = "0.3.0"
APP_DIR = DIST / f"{APP_NAME}.app"
CONTENTS_DIR = APP_DIR / "Contents"
BUNDLE_ROOT = CONTENTS_DIR / "Resources" / "pdf-epub"
DMG_PATH = DIST / "PDF-to-EPUB-mac-arm64.dmg"

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
PYTHON_SPECS = [
    {"venv": ".venv", "executable": "python3.14", "formula": "python@3.14", "version": "3.14"},
    {"venv": ".venv_paddleocr", "executable": "python3.12", "formula": "python@3.12", "version": "3.12"},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the macOS PDF to EPUB app bundle.")
    parser.add_argument("--include-private-env", action="store_true", help="Copy .env/.env.local into the app bundle.")
    parser.add_argument("--skip-dmg", action="store_true", help="Build only the .app bundle.")
    parser.add_argument("--node-version", default=os.environ.get("BUNDLE_NODE_VERSION", ""), help="Node version to bundle, e.g. v24.18.1.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _preflight()
    _ensure_kcc_source()
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
    if DMG_PATH.exists():
        DMG_PATH.unlink()

    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    _copy_runtime(include_private_env=args.include_private_env)
    _bundle_python_runtimes()
    _bundle_node(args.node_version)
    _bundle_cloudflared()
    _write_info_plist()
    _compile_native_launcher()
    _codesign_app()
    if not args.skip_dmg:
        _write_dmg()
    _summarize()
    return 0


def _preflight() -> None:
    missing = [name for name in REQUIRED_ITEMS if not (ROOT / name).exists()]
    if missing:
        raise SystemExit(f"Missing required package inputs: {', '.join(missing)}")
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        raise SystemExit("This package target currently builds macOS arm64 apps only.")
    if not shutil.which("swiftc"):
        raise SystemExit("Missing swiftc. Install Xcode command line tools first.")
    if not shutil.which("install_name_tool"):
        raise SystemExit("Missing install_name_tool. Install Xcode command line tools first.")
    if not shutil.which("hdiutil"):
        raise SystemExit("Missing hdiutil. This script must run on macOS.")


def _copy_runtime(*, include_private_env: bool) -> None:
    for name in REQUIRED_ITEMS:
        _copy_item(ROOT / name, BUNDLE_ROOT / name)

    if include_private_env:
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


def _bundle_python_runtimes() -> None:
    for spec in PYTHON_SPECS:
        source_python = (ROOT / spec["venv"] / "bin" / spec["executable"]).resolve()
        if not source_python.exists():
            raise SystemExit(f"Missing Python executable for {spec['venv']}: {source_python}")

        source_root = _python_cellar_root(source_python)
        target_root = BUNDLE_ROOT / "vendor" / spec["formula"] / source_root.name
        if target_root.exists():
            shutil.rmtree(target_root)
        shutil.copytree(source_root, target_root, symlinks=True, ignore=_ignore_for(source_root))

        binary = _python_framework_executable(target_root, spec)
        old_framework = _python_framework_load_path(binary)
        new_framework = "@executable_path/../Python"
        if old_framework != new_framework:
            subprocess.run(["install_name_tool", "-change", old_framework, new_framework, str(binary)], check=True)

        _replace_venv_python_link(spec["venv"], spec["executable"], target_root)
        _rewrite_pyvenv_cfg(spec["venv"], spec["executable"], spec["version"], target_root)
        _codesign_python_runtime(target_root, binary)


def _python_cellar_root(python: Path) -> Path:
    parts = python.parts
    if "Cellar" not in parts:
        raise SystemExit(f"Python executable is not under a Homebrew Cellar path: {python}")
    cellar_index = parts.index("Cellar")
    return Path(*parts[: cellar_index + 3])


def _python_framework_executable(runtime_root: Path, spec: dict[str, str]) -> Path:
    executable = (
        runtime_root
        / "Frameworks"
        / "Python.framework"
        / "Versions"
        / spec["version"]
        / "bin"
        / spec["executable"]
    )
    if not executable.exists():
        raise SystemExit(f"Missing bundled Python framework executable: {executable}")
    return executable


def _python_framework_load_path(binary: Path) -> str:
    proc = subprocess.run(["otool", "-L", str(binary)], check=True, capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        value = line.strip().split(" ", 1)[0]
        if "Python.framework" in value and value.endswith("/Python"):
            return value
    raise SystemExit(f"Could not find Python.framework load path in {binary}")


def _codesign_python_runtime(runtime_root: Path, binary: Path) -> None:
    if not shutil.which("codesign"):
        return
    framework = runtime_root / "Frameworks" / "Python.framework"
    versioned_framework = binary.parent.parent
    sign_target = framework if (framework / "Python").exists() else versioned_framework
    subprocess.run(["codesign", "--force", "--sign", "-", str(binary)], check=True)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(sign_target)], check=True)


def _replace_venv_python_link(venv: str, executable: str, runtime_root: Path) -> None:
    link = BUNDLE_ROOT / venv / "bin" / executable
    if link.exists() or link.is_symlink():
        link.unlink()
    relative = os.path.relpath(runtime_root / "bin" / executable, start=link.parent)
    link.symlink_to(relative)


def _rewrite_pyvenv_cfg(venv: str, executable: str, version: str, runtime_root: Path) -> None:
    config = BUNDLE_ROOT / venv / "pyvenv.cfg"
    relative_home = os.path.relpath(runtime_root / "bin", start=config.parent)
    relative_executable = os.path.relpath(runtime_root / "bin" / executable, start=config.parent)
    config.write_text(
        "\n".join(
            [
                f"home = {relative_home}",
                "include-system-site-packages = false",
                f"version = {version}",
                f"executable = {relative_executable}",
                f"command = {relative_executable} -m venv {venv}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _bundle_node(requested_version: str) -> None:
    version = requested_version or _latest_lts_node_version()
    arch = "arm64" if platform.machine() in {"arm64", "aarch64"} else "x64"
    archive_name = f"node-{version}-darwin-{arch}.tar.xz"
    url = f"https://nodejs.org/dist/{version}/{archive_name}"
    vendor_dir = BUNDLE_ROOT / "vendor"
    target = vendor_dir / "node"
    if target.exists():
        shutil.rmtree(target)

    with tempfile.TemporaryDirectory() as temp_dir:
        archive = Path(temp_dir) / archive_name
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive, "r:xz") as stream:
            stream.extractall(temp_dir, filter="data")
        extracted = Path(temp_dir) / f"node-{version}-darwin-{arch}"
        shutil.copytree(extracted, target, symlinks=True)

    bin_dir = BUNDLE_ROOT / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    node_link = bin_dir / "node"
    if node_link.exists() or node_link.is_symlink():
        node_link.unlink()
    node_link.symlink_to(os.path.relpath(target / "bin" / "node", start=bin_dir))


def _latest_lts_node_version() -> str:
    with urllib.request.urlopen("https://nodejs.org/dist/index.json", timeout=20) as response:
        releases = json.loads(response.read().decode("utf-8"))
    for release in releases:
        if release.get("lts") and "osx-arm64-tar" in release.get("files", []):
            return str(release["version"])
    raise SystemExit("Could not find a Node.js LTS macOS arm64 release.")


def _bundle_cloudflared() -> None:
    executable = shutil.which("cloudflared")
    if not executable:
        raise SystemExit("Missing cloudflared. Install it or make it available on PATH before packaging.")
    target = BUNDLE_ROOT / "bin" / "cloudflared"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(executable).resolve(), target)
    _make_executable(target)


def _ensure_kcc_source() -> None:
    target = ROOT / "tmp" / "kcc-source-work"
    if (target / "kcc-c2e.py").exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    subprocess.run(
        ["git", "clone", "--depth", "1", "https://github.com/ciromattia/kcc.git", str(target)],
        cwd=ROOT,
        check=True,
    )


def _write_info_plist() -> None:
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": "PDFToEPUBApp",
        "CFBundleIdentifier": "local.pdf-epub.app",
        "CFBundleName": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "13.0",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    }
    with (CONTENTS_DIR / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)


def _compile_native_launcher() -> None:
    macos = CONTENTS_DIR / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "swiftc",
            str(ROOT / "macos" / "PDFToEPUBApp.swift"),
            "-o",
            str(macos / "PDFToEPUBApp"),
            "-framework",
            "Cocoa",
            "-framework",
            "WebKit",
        ],
        cwd=ROOT,
        check=True,
    )
    _make_executable(macos / "PDFToEPUBApp")


def _codesign_app() -> None:
    if not shutil.which("codesign"):
        return
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(APP_DIR)],
        check=True,
    )


def _write_dmg() -> None:
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(APP_DIR),
            "-ov",
            "-format",
            "UDZO",
            str(DMG_PATH),
        ],
        check=True,
    )


def _summarize() -> None:
    print(f"Wrote {APP_DIR}")
    if DMG_PATH.exists():
        print(f"Wrote {DMG_PATH}")
    print("Private .env files are not bundled unless --include-private-env is used.")
    print("App data, config, and model cache live in ~/Library/Application Support/PDF to EPUB")


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    raise SystemExit(main())
