"""Stable identity for the source tree served by a desktop process."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SOURCE_DIRS = ("web", "analytics", "services", "repository", "migrations", "models", "utils", "data", "gui", "ui")
SOURCE_SUFFIXES = {".py", ".js", ".css", ".html"}
ROOT_FILES = ("desktop.py", "pyproject.toml", "alembic.ini")


def python_runtime_id() -> str:
    identity = f"{Path(sys.executable).absolute()}\0{Path(sys.prefix).absolute()}"
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def source_build_id(root: Path | None = None) -> str:
    project = (root or Path(__file__).resolve().parents[1]).resolve()
    digest = hashlib.sha256(str(project).encode())
    for name in SOURCE_DIRS:
        directory = project / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            digest.update(path.relative_to(project).as_posix().encode())
            digest.update(b"\0")
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
    for name in ROOT_FILES:
        path = project / name
        if path.is_file():
            digest.update(name.encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()[:20]
