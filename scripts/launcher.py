#!/usr/bin/env python3
"""Lance le MCP dans un environnement Python isolé, sans polluer stdout."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.sha256"
LOCK = ROOT / ".bootstrap.lock"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def requirements_digest() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ready() -> bool:
    try:
        return venv_python().is_file() and STAMP.read_text(encoding="utf-8").strip() == requirements_digest()
    except OSError:
        return False


def acquire_lock() -> None:
    deadline = time.monotonic() + 180
    while True:
        try:
            LOCK.mkdir()
            return
        except FileExistsError:
            try:
                stale = time.time() - LOCK.stat().st_mtime > 300
            except OSError:
                stale = False
            if stale:
                shutil.rmtree(LOCK, ignore_errors=True)
                continue
            if ready():
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("installation Python concurrente bloquée depuis plus de 3 minutes")
            time.sleep(0.25)


def bootstrap() -> None:
    if ready():
        return
    acquire_lock()
    if ready():
        return
    try:
        if not venv_python().is_file():
            subprocess.run(
                [sys.executable, "-m", "venv", str(VENV)],
                check=True,
                stdout=sys.stderr,
                stderr=sys.stderr,
            )
        subprocess.run(
            [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)],
            check=True,
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
        STAMP.write_text(f"{requirements_digest()}\n", encoding="utf-8")
    finally:
        shutil.rmtree(LOCK, ignore_errors=True)


def configure_environment() -> None:
    if os.environ.get("LEGIFRANCE_ENV_FILE"):
        return
    candidate = Path.home() / ".config" / "mcp-legifrance" / ".env"
    if candidate.is_file():
        os.environ["LEGIFRANCE_ENV_FILE"] = str(candidate)


def main() -> None:
    try:
        bootstrap()
        if "--bootstrap-only" in sys.argv[1:]:
            return
        configure_environment()
        os.execv(str(venv_python()), [str(venv_python()), str(ROOT / "mcp_stdio_server.py")])
    except Exception as error:
        print(f"Impossible de démarrer Légifrance MCP : {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

