# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""First-run download of the two speech models (about 930 MB in total)."""
import json
import subprocess
import sys
from pathlib import Path as _P
import urllib.request

from . import config

HF = "https://huggingface.co/{repo}/resolve/main/{name}"


def download_nemotron(progress):
    """progress(fraction) is called as bytes arrive."""
    d = config.NEMOTRON_DIR
    d.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for f in config.NEMOTRON_FILES:
        req = urllib.request.Request(HF.format(repo=config.NEMOTRON_REPO, name=f), method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            sizes[f] = int(r.headers.get("Content-Length") or 0)
    total = max(1, sum(sizes.values()))
    done = sum(sizes[f] for f in config.NEMOTRON_FILES if (d / f).exists() and (d / f).stat().st_size == sizes[f])
    for f in config.NEMOTRON_FILES:
        target = d / f
        if target.exists() and target.stat().st_size == sizes[f]:
            continue
        part = d / (f + ".part")
        with urllib.request.urlopen(HF.format(repo=config.NEMOTRON_REPO, name=f), timeout=120) as r, open(part, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                progress(min(1.0, done / total))
        part.replace(target)
    progress(1.0)


def download_moonshine(progress):
    """Runs in a separate process (see post.py) so its speech engine never loads into this one."""
    flags = 0x08000000 if sys.platform == "win32" else 0
    p = subprocess.Popen([console_python(), "-m", "callrec.post", "download"], cwd=str(config.APP_DIR),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)
    for raw in p.stdout:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if msg.get("type") == "progress":
            progress(msg.get("fraction", 0))
    err = p.stderr.read()
    if p.wait() != 0:
        raise RuntimeError(err.strip().splitlines()[-1] if err.strip() else "Moonshine download failed")
    progress(1.0)


def console_python():
    """pythonw.exe has no console; use python.exe (with no window) so progress messages reach us."""
    exe = _P(sys.executable)
    alt = exe.with_name("python.exe")
    return str(alt) if exe.name.lower() == "pythonw.exe" and alt.exists() else sys.executable
