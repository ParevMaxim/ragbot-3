# bootstrap_ollama.py
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

def _default_ollama_check_url(ollama_host: str) -> str:
    return ollama_host.rstrip("/") + "/api/tags"

def is_ollama_up(ollama_host: str, timeout_sec: float = 2.0) -> bool:
    url = _default_ollama_check_url(ollama_host)
    try:
        with urlopen(url, timeout=timeout_sec) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False

def find_ollama_exe() -> str | None:
    # 1) PATH
    p = shutil.which("ollama")
    if p:
        return p

    # 2) типичные места на Windows
    local = os.environ.get("LOCALAPPDATA", "")
    prog = os.environ.get("ProgramFiles", "")
    candidates = [
        Path(local) / "Programs" / "Ollama" / "ollama.exe",
        Path(prog) / "Ollama" / "ollama.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    return None

def try_start_ollama_serve() -> None:
    exe = find_ollama_exe()
    if not exe:
        return

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    try:
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except Exception:
        return

def ensure_ollama_running(ollama_host: str, wait_seconds: int = 30) -> bool:
    if is_ollama_up(ollama_host):
        return True

    try_start_ollama_serve()

    t0 = time.time()
    while time.time() - t0 < wait_seconds:
        if is_ollama_up(ollama_host):
            return True
        time.sleep(1)

    return False