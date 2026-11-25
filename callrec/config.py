# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Paths and settings shared by every part of the app."""
import os
import sys
from pathlib import Path

APP_NAME = "FreeCallNotes"
VERSION = "1.4.1"
# Portable mode: by default calls are saved in a "Call Notes" folder inside the app folder, so the
# whole app (and everything it records) lives in one folder that can be moved or deleted.
# Set to False to default to Documents\Call Notes instead. Users can pick any folder in Options.
SAVE_IN_APP_FOLDER = True
NOTICE_VERSION = 1   # bump when the first-run notice text changes, so users see it again
SR = 16000  # every track is stored and transcribed as 16 kHz mono

# The app folder is two levels above this file: <app>/callrec/config.py
APP_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = APP_DIR / "models"
NEMOTRON_DIR = MODELS_DIR / "nemotron"
MOONSHINE_DIR = MODELS_DIR / "moonshine"
LOG_FILE = APP_DIR / "freecallnotes.log"

NEMOTRON_REPO = "csukuangfj/sherpa-onnx-nemotron-speech-streaming-en-0.6b-int8-2026-01-14"
NEMOTRON_FILES = ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"]


def notes_root() -> Path:
    """Where finished calls are saved: Documents\\Call Notes (or ~/Call Notes off Windows)."""
    override = os.environ.get("CALLREC_NOTES_DIR")
    if override:
        return Path(override)
    chosen = settings().get("notes_dir")
    if chosen:
        return Path(chosen)
    if SAVE_IN_APP_FOLDER:
        return APP_DIR / "Call Notes"
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5 (Documents), honours OneDrive-redirected Documents
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            if buf.value:
                return Path(buf.value) / "Call Notes"
        except Exception:
            pass
        return Path.home() / "Documents" / "Call Notes"
    return Path.home() / "Call Notes"


def nemotron_ready() -> bool:
    return all((NEMOTRON_DIR / f).exists() and (NEMOTRON_DIR / f).stat().st_size > 0 for f in NEMOTRON_FILES)


def moonshine_ready() -> bool:
    return (MOONSHINE_DIR / ".ready").exists()


DEFAULT_SETTINGS = {
    "nemotron": "during",     # "during" the call, "after" the call, or "off"
    "moonshine": "off",
    "show_live": True,        # the model running during the call is shown live
    "notes_dir": None,        # where calls are saved (None = the default folder)
    "notice_accepted": 0,     # NOTICE_VERSION the user last accepted
}


def settings() -> dict:
    """User options (settings.json next to the app), merged over the defaults."""
    import json
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads((APP_DIR / "settings.json").read_text()))
    except Exception:
        pass
    if s["nemotron"] == "during" and s["moonshine"] == "during":     # older settings: only one may run live
        s["moonshine"] = "after"
    s["show_live"] = "during" in (s["nemotron"], s["moonshine"])
    return s


def default_notes_root() -> Path:
    return (APP_DIR / "Call Notes") if SAVE_IN_APP_FOLDER else _documents() / "Call Notes"


def _documents() -> Path:
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            if buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def set_notes_dir(path) -> dict:
    import json
    s = settings()
    s["notes_dir"] = str(path) if path else None
    (APP_DIR / "settings.json").write_text(json.dumps(s, indent=1))
    return s


def save_settings(new: dict) -> dict:
    """Rules: at most one model during the call (it is shown live); a model running during the call
    is not run again afterwards; at least one model must run."""
    import json
    s = settings()
    during = new.get("during", "nemotron")
    after = set(new.get("after", []))
    for m in ("nemotron", "moonshine"):
        s[m] = "during" if m == during else ("after" if m in after else "off")
    if s["nemotron"] == "off" and s["moonshine"] == "off":
        s["nemotron"] = "during"
    s["show_live"] = "during" in (s["nemotron"], s["moonshine"])
    (APP_DIR / "settings.json").write_text(json.dumps(s, indent=1))
    return s


def code_stamp() -> float:
    """Latest change time of the app's own files; used to spot that an update was installed."""
    d = APP_DIR / "callrec"
    return max((f.stat().st_mtime for f in d.iterdir() if f.suffix in (".py", ".html")), default=0.0)


def accept_notice() -> dict:
    import json
    s = settings()
    s["notice_accepted"] = NOTICE_VERSION
    (APP_DIR / "settings.json").write_text(json.dumps(s, indent=1))
    return s
