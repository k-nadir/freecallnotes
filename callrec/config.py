# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Paths and settings shared by every part of the app."""
import os
import sys
from pathlib import Path

APP_NAME = "FreeCallNotes"
VERSION = "1.5"
# Portable mode: by default calls are saved in a "Call Notes" folder inside the app folder, so the
# whole app (and everything it records) lives in one folder that can be moved or deleted.
# Set to False to default to Documents\Call Notes instead. Users can pick any folder in Options.
SAVE_IN_APP_FOLDER = True
NOTICE_VERSION = 2   # bump when the first-run notice text changes, so users see it again
SR = 16000  # every track is stored and transcribed as 16 kHz mono

# The app folder is two levels above this file: <app>/callrec/config.py
APP_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = APP_DIR / "models"
NEMOTRON_DIR = MODELS_DIR / "nemotron"
MOONSHINE_DIR = MODELS_DIR / "moonshine"
WHISPER_DIR = MODELS_DIR / "whisper"
LOG_FILE = APP_DIR / "freecallnotes.log"

NEMOTRON_REPO = "csukuangfj/sherpa-onnx-nemotron-speech-streaming-en-0.6b-int8-2026-01-14"
NEMOTRON_FILES = ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"]
# Whisper large-v3 turbo (OpenAI, MIT License) in the int8 ONNX export for sherpa-onnx: about 100 languages.
WHISPER_REPO = "csukuangfj/sherpa-onnx-whisper-turbo"
WHISPER_FILES = ["turbo-encoder.int8.onnx", "turbo-decoder.int8.onnx", "turbo-tokens.txt"]
# Silero VAD (MIT License): finds the stretches of speech so Whisper never sees silence (where it invents text).
VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
VAD_FILE = "silero_vad.onnx"
MODELS = ("nemotron", "moonshine", "whisper")      # Whisper runs after the call only


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


def whisper_ready() -> bool:
    need = WHISPER_FILES + [VAD_FILE]
    return all((WHISPER_DIR / f).exists() and (WHISPER_DIR / f).stat().st_size > 0 for f in need)


def installed(model: str) -> bool:
    return {"nemotron": nemotron_ready, "moonshine": moonshine_ready, "whisper": whisper_ready}[model]()


DEFAULT_SETTINGS = {
    "nemotron": "during",     # "during" the call, "after" the call, or "off"
    "moonshine": "off",
    "whisper": "off",         # "after" the call, or "off" (Whisper is too slow to run during a call)
    "whisper_language": "auto",   # "auto" (detected from the call) or a language code such as "es"
    "call_popups": True,      # small background helper: "Call starting in Zoom. Open FreeCallNotes?"
    "show_live": True,        # the model running during the call is shown live
    "notes_dir": None,        # where calls are saved (None = the default folder)
    "notice_accepted": 0,     # NOTICE_VERSION the user last accepted
    "auto_update_check": True,   # look for a new release at most once every UPDATE_CHECK_DAYS (never installs by itself)
    "last_update_check": 0,      # when GitHub was last asked (seconds since 1970)
    "update_available": None,    # newest version seen that is newer than this one, until installed or dismissed
}
UPDATE_CHECK_DAYS = 30


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
    if s.get("whisper") == "during":                                 # Whisper only runs after the call
        s["whisper"] = "after"
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
    """Rules: at most one model during the call (it is shown live; Whisper can't run during the call);
    a model running during the call is not run again afterwards; only installed models can be chosen;
    at least one model must run."""
    import json
    s = settings()
    during = new.get("during", "nemotron")
    if during == "whisper" or (during in MODELS and not installed(during)):
        during = "none"
    after = {m for m in new.get("after", []) if m in MODELS and installed(m)}
    for m in MODELS:
        s[m] = "during" if m == during else ("after" if m in after else "off")
    if all(s[m] == "off" for m in MODELS):
        s.update(_fallback_model())
    if new.get("whisper_language"):
        s["whisper_language"] = str(new["whisper_language"])[:12]
    s["show_live"] = "during" in (s["nemotron"], s["moonshine"])
    (APP_DIR / "settings.json").write_text(json.dumps(s, indent=1))
    return s


def _fallback_model() -> dict:
    """Something has to transcribe: the first installed model (Nemotron if none is installed yet)."""
    for m in MODELS:
        if installed(m):
            return {m: "after" if m == "whisper" else "during"}
    return {"nemotron": "during"}


def update_settings(**changes) -> dict:
    """Change individual settings (update preferences, call pop-ups, Whisper language)."""
    import json
    s = settings()
    s.update(changes)
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
