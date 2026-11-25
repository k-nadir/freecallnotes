# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Builds the "Transcript for AI" file you drop into any AI assistant after a call."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from .engine import fmt_ts, is_echo, overlaps

HEADER_MANY = """INSTRUCTIONS FOR THE AI ASSISTANT

This file contains a recorded call, transcribed by {n} different speech recognition models.
None of the transcripts is fully correct. Your job is to work out what was actually said, then write up notes.
"""
HEADER_ONE = """INSTRUCTIONS FOR THE AI ASSISTANT

This file contains a recorded call, transcribed by a speech recognition model ({model}).
The transcript is good but not perfect. Your job is to work out what was actually said, then write up notes.
"""
SIDES = """
The call has two sides, recorded separately:
- USER   = the person who recorded the call (their microphone).
- SYSTEM = everyone else on the call (the computer's system sound). Several people may share this track.
"""
ABOUT = {
    "nemotron": """(NVIDIA Nemotron): English only. Good with jargon, names and numbers, but tends to DROP words,
  especially the first word or two after a pause, fillers and repetitions.""",
    "moonshine": """(Moonshine): English only. Drops fewer words, but tends to MISHEAR words,
  especially company names, acronyms, finance terms and sound-alikes (e.g. "eighteen" vs "eighty").""",
    "whisper": """(Whisper large-v3 turbo): understands about 100 languages and is usually the most accurate,
  but can occasionally repeat itself or add a short phrase that wasn't said, in quiet stretches.""",
}
NAMES = {"nemotron": "NVIDIA Nemotron", "moonshine": "Moonshine", "whisper": "Whisper"}
STEPS_MANY = """
Please:
1. For each side, compare the versions line by line (use the timestamps) and reconstruct the
   most likely wording: pick the more plausible version, restore words one version dropped, and fix
   obvious misspellings of names and terms. Do not invent anything no version supports.
"""
STEPS_ONE = """
Please:
1. For each side, fix obvious mis-hearings of names, companies and terms where the intended word is clear
   from context. Do not invent anything the transcript doesn't support.
"""
LANG_NOTE = """
LANGUAGE: Whisper detected that this call is in {language}. The English-only versions above (if any) will be
unreliable for it: rely on the Whisper version. Keep the reconstructed transcript in the original language,
and write the notes in English unless I ask for another language.
"""
LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
             "nl": "Dutch", "ru": "Russian", "uk": "Ukrainian", "pl": "Polish", "tr": "Turkish", "ar": "Arabic",
             "ur": "Urdu", "hi": "Hindi", "bn": "Bengali", "pa": "Punjabi", "fa": "Persian", "zh": "Chinese",
             "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese", "th": "Thai", "id": "Indonesian", "ms": "Malay",
             "tl": "Tagalog", "sw": "Swahili", "he": "Hebrew", "el": "Greek", "sv": "Swedish", "no": "Norwegian",
             "da": "Danish", "fi": "Finnish", "cs": "Czech", "ro": "Romanian", "hu": "Hungarian", "ta": "Tamil"}
STEPS_REST = """2. Merge USER and SYSTEM into one conversation in time order. Lines from both sides at the same moment mean
   people were talking over each other: keep both.
3. Lines marked [possible echo] are probably the other side's voice leaking from the speakers into the
   microphone. If a USER line repeats what SYSTEM said at about the same time, treat it as echo and drop it.
4. Where a number, name or figure is uncertain, keep the most likely one and flag it, e.g. "18% [or 80%?]".
5. Then give me:
   a) The clean, reconstructed transcript (USER / SYSTEM labels, timestamps every few lines).
   b) Notes: a short summary, key points and figures, decisions, action items (with owner if stated),
      and open questions or follow-ups.
"""


def _section(title, lines):
    out = [f"===== {title} ====="]
    if not lines:
        out.append("(nothing transcribed)")
    for ln in lines:
        tag = " [possible echo]" if ln.get("echo") else ""
        out.append(f"[{fmt_ts(ln['start'])}]{tag} {ln['text']}")
    return "\n".join(out)


def _flag_echo(me_lines, them_lines):
    for a in me_lines:
        near = " ".join(b["text"] for b in them_lines if overlaps(a, b))
        a["echo"] = a.get("echo", False) or bool(near and is_echo(a["text"], near))


def build_export(call_dir):
    call_dir = Path(call_dir)
    meta = json.loads((call_dir / "call.json").read_text())

    def load(name):
        p = call_dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    versions = []                       # (model, {"me": lines, "them": lines})
    live = load("nemotron_lines.json")
    if live is None and not any((call_dir / f).exists() for f in ("second_pass_me.json", "whisper_me.json",
                                                                    "second_pass_them.json", "whisper_them.json")):
        live = load("live_lines.json")
    if live is not None:
        versions.append(("nemotron", {k: [l for l in live if l["key"] == k] for k in ("me", "them")}))
    for model, prefix in (("moonshine", "second_pass"), ("whisper", "whisper")):
        if any((call_dir / f"{prefix}_{k}.json").exists() for k in ("me", "them")):
            versions.append((model, {k: load(f"{prefix}_{k}.json") or [] for k in ("me", "them")}))
    for _, v in versions:
        _flag_echo(v["me"], v["them"])
    wmeta = load("whisper_meta.json") or {}
    language = wmeta.get("language")

    start = datetime.fromisoformat(meta["started"])
    end = start + timedelta(seconds=meta["duration_sec"])
    mins = round(meta["duration_sec"] / 60)
    devices = meta.get("devices", {})
    header = (f"CALL RECORDING TRANSCRIPTS\n"
              f"Recorded: {start:%A %d %B %Y}, {start:%H:%M} to {end:%H:%M} ({mins} min)\n"
              f"User (microphone): {devices.get('me', 'not recorded')}\n"
              f"System sound: {devices.get('them', 'not recorded')}\n")
    note = LANG_NOTE.format(language=LANGUAGES.get(language, language)) if language and language != "en" else ""
    if len(versions) >= 2:
        letters = "ABC"
        about = "\n".join(f"- Version {letters[i]} {ABOUT[m]}" for i, (m, _) in enumerate(versions))
        instr = (HEADER_MANY.format(n=len(versions)) + SIDES + f"\nFor each side there are {len(versions)} versions:\n"
                 + about + "\n" + note + STEPS_MANY + STEPS_REST)
        sections = [_section(f"{side} - Version {letters[i]} ({NAMES[m]})", v[k])
                    for k, side in (("me", "USER"), ("them", "SYSTEM")) for i, (m, v) in enumerate(versions)]
    elif versions:
        m, v = versions[0]
        instr = HEADER_ONE.format(model=NAMES[m]) + SIDES + note + STEPS_ONE + STEPS_REST
        sections = [_section("USER", v["me"]), _section("SYSTEM", v["them"])]
    else:
        instr = HEADER_ONE.format(model="none") + SIDES + STEPS_ONE + STEPS_REST
        sections = [_section("USER", []), _section("SYSTEM", [])]
    parts = [header, instr] + sections
    out = call_dir / f"Transcript for AI - {start:%d %b %Y %H.%M}.txt"
    out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return out
