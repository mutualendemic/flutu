#!/usr/bin/env python3
"""Create a source ZIP suitable for a Dockerfile-based deployment service."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "flutu-snapdeploy.zip"
INCLUDE_PATHS = (
    Path("Dockerfile"),
    Path(".dockerignore"),
    Path("requirements.txt"),
    Path("run.py"),
    Path("app"),
)


def iter_package_files():
    for relative_path in INCLUDE_PATHS:
        source = ROOT / relative_path
        if not source.exists():
            raise FileNotFoundError(f"Required SnapDeploy package path is missing: {relative_path}")
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for path in candidates:
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.name == ".DS_Store":
                continue
            yield path, path.relative_to(ROOT)


def build_zip(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    files = list(iter_package_files())
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, relative_path in files:
            archive.write(source, arcname=relative_path.as_posix())

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        required = {"Dockerfile", ".dockerignore", "requirements.txt", "run.py", "app/__init__.py"}
        missing = required - names
        if missing:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"ZIP is missing required deployment files: {', '.join(sorted(missing))}")
        if any(name.startswith((".env", ".git/", ".venv/", "tests/")) for name in names):
            output.unlink(missing_ok=True)
            raise RuntimeError("ZIP unexpectedly contains local configuration, git data, venv, or tests")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output ZIP path (default: dist/flutu-snapdeploy.zip)")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    built = build_zip(output)
    print(f"Created {built.relative_to(ROOT) if built.is_relative_to(ROOT) else built} ({built.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
