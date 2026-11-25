# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Downloading and removing the speech models (Nemotron, Moonshine, Whisper)."""
import json
import subprocess
import sys
from pathlib import Path as _P
import urllib.request

from . import config

HF = "https://huggingface.co/{repo}/resolve/main/{name}"


def _download(items, d, progress):
    """items: [(url, filename)]. Downloads into folder d with progress(fraction); resumes cleanly by
    skipping files that are already complete, and writes each file as .part first."""
    d.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for url, f in items:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "FreeCallNotes"})
        with urllib.request.urlopen(req, timeout=60) as r:
            sizes[f] = int(r.headers.get("Content-Length") or 0)
    total = max(1, sum(sizes.values()))
    done = sum(sizes[f] for _, f in items if (d / f).exists() and (d / f).stat().st_size == sizes[f])
    for url, f in items:
        target = d / f
        if target.exists() and target.stat().st_size == sizes[f]:
            continue
        part = d / (f + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": "FreeCallNotes"})
        with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                progress(min(1.0, done / total))
        part.replace(target)
    progress(1.0)


def download_nemotron(progress):
    """progress(fraction) is called as bytes arrive."""
    _download([(HF.format(repo=config.NEMOTRON_REPO, name=f), f) for f in config.NEMOTRON_FILES],
              config.NEMOTRON_DIR, progress)


def download_whisper(progress):
    """Whisper large-v3 turbo (about 1 GB) plus the small Silero voice detector it needs."""
    items = [(HF.format(repo=config.WHISPER_REPO, name=f), f) for f in config.WHISPER_FILES]
    items.append((config.VAD_URL, config.VAD_FILE))
    _download(items, config.WHISPER_DIR, progress)


def download(model, progress):
    {"nemotron": download_nemotron, "moonshine": download_moonshine, "whisper": download_whisper}[model](progress)


def remove(model):
    """Delete a model's files. It downloads again if it's installed again."""
    import shutil
    d = {"nemotron": config.NEMOTRON_DIR, "moonshine": config.MOONSHINE_DIR, "whisper": config.WHISPER_DIR}[model]
    if d.exists():
        shutil.rmtree(d)


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
