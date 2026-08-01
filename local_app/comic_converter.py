from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .conversion_options import ComicLayout, ComicOutputFormat


class KccComicError(RuntimeError):
    pass


@dataclass(frozen=True)
class KccComicResult:
    output_path: Path
    command: list[str]
    stdout: str
    stderr: str


class KccComicConverter:
    def __init__(
        self,
        *,
        command: str,
        source_dir: Path | None,
        profile: str,
        force_color: bool,
        disable_rotate: bool,
    ):
        self.command = command
        self.source_dir = source_dir
        self.profile = profile
        self.force_color = force_color
        self.disable_rotate = disable_rotate

    def convert(
        self,
        *,
        input_dir: Path,
        output_dir: Path,
        title: str,
        author: str,
        output_format: ComicOutputFormat,
        layout: ComicLayout,
        final_stem: str,
    ) -> KccComicResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        command = self._resolve_command()
        args = [
            *command,
            "-p",
            self.profile,
            "-o",
            str(output_dir),
            "-t",
            title,
            "--language",
            "en-US",
        ]
        if author:
            args.extend(["-a", author])
        if output_format == "cbz":
            args.extend(["-f", "CBZ"])
        else:
            args.extend(["-f", "EPUB"])
            if output_format == "epub":
                args.append("--nokepub")
        if layout == "manga":
            args.append("--manga-style")
        elif layout == "webtoon":
            args.append("--webtoon")
        if self.force_color:
            args.append("--forcecolor")
        if self.disable_rotate:
            args.append("--norotate")
        args.append(str(input_dir))

        proc = subprocess.run(args, check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or "KCC conversion failed."
            raise KccComicError(detail)

        output_path = self._find_output(output_dir, output_format)
        target = output_dir / f"{_safe_stem(final_stem)}{_extension(output_format)}"
        if output_path != target:
            if target.exists():
                target.unlink()
            shutil.move(str(output_path), str(target))
            output_path = target

        return KccComicResult(output_path=output_path, command=args, stdout=proc.stdout, stderr=proc.stderr)

    def _resolve_command(self) -> list[str]:
        if self.command.strip():
            return shlex.split(self.command)

        executable = shutil.which("kcc-c2e") or shutil.which("kcc-c2e.py")
        if executable:
            return [executable]

        source_dir = self.source_dir
        if source_dir:
            script = source_dir.expanduser().resolve() / "kcc-c2e.py"
            if script.exists():
                return [sys.executable, str(script)]

        raise KccComicError(
            "Kindle Comic Converter CLI was not found. Set LOCAL_KCC_C2E_COMMAND to kcc-c2e "
            "or LOCAL_KCC_SOURCE_DIR to a KCC source checkout."
        )

    def _find_output(self, output_dir: Path, output_format: ComicOutputFormat) -> Path:
        patterns = {
            "kepub": ["*.kepub.epub"],
            "epub": ["*.epub"],
            "cbz": ["*.cbz"],
        }[output_format]
        candidates: list[Path] = []
        for pattern in patterns:
            candidates.extend(output_dir.glob(pattern))
        if output_format == "epub":
            candidates = [path for path in candidates if not path.name.endswith(".kepub.epub")]
        if not candidates:
            raise KccComicError(f"KCC finished but no {output_format.upper()} output was found.")
        return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def _extension(output_format: ComicOutputFormat) -> str:
    if output_format == "kepub":
        return ".kepub.epub"
    if output_format == "epub":
        return ".epub"
    return ".cbz"


def _safe_stem(value: str) -> str:
    stem = Path(value).stem.strip() or "comic"
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "-", stem)
    return stem[:140] or "comic"
