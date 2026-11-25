# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Builds the "Transcript for AI" file you drop into any AI assistant after a call."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from .engine import fmt_ts, is_echo, overlaps

HEADER_TWO = """INSTRUCTIONS FOR THE AI ASSISTANT

This file contains a recorded call, transcribed by two different speech recognition models.
Neither transcript is fully correct. Your job is to work out what was actually said, then write up notes.
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
MODELS = {
    "A": """- Version A (NVIDIA Nemotron): good with jargon, names and numbers, but tends to DROP words,
  especially the first word or two after a pause, fillers and repetitions.""",
    "B": """- Version B (Moonshine): drops fewer words, but tends to MISHEAR words,
  especially company names, acronyms, finance terms and sound-alikes (e.g. "eighteen" vs "eighty").""",
}
STEPS_TWO = """
Please:
1. For each side, compare Version A and Version B line by line (use the timestamps) and reconstruct the
   most likely wording: pick the more plausible version, restore words one version dropped, and fix
   obvious misspellings of names and terms. Do not invent anything neither version supports.
"""
STEPS_ONE = """
Please:
1. For each side, fix obvious mis-hearings of names, companies and terms where the intended word is clear
   from context. Do not invent anything the transcript doesn't support.
"""
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
    src = call_dir / "nemotron_lines.json"
    if not src.exists():
        src = call_dir / "live_lines.json"
    live = json.loads(src.read_text()) if src.exists() else []
    second = {k: json.loads(p.read_text()) if (p := call_dir / f"second_pass_{k}.json").exists() else []
              for k in ("me", "them")}
    a = {k: [l for l in live if l["key"] == k] for k in ("me", "them")}
    _flag_echo(a["me"], a["them"])
    _flag_echo(second["me"], second["them"])

    start = datetime.fromisoformat(meta["started"])
    end = start + timedelta(seconds=meta["duration_sec"])
    mins = round(meta["duration_sec"] / 60)
    devices = meta.get("devices", {})
    header = (f"CALL RECORDING TRANSCRIPTS\n"
              f"Recorded: {start:%A %d %B %Y}, {start:%H:%M} to {end:%H:%M} ({mins} min)\n"
              f"User (microphone): {devices.get('me', 'not recorded')}\n"
              f"System sound: {devices.get('them', 'not recorded')}\n")
    have_a = (call_dir / "nemotron_lines.json").exists()
    have_b = any((call_dir / f"second_pass_{k}.json").exists() for k in ("me", "them"))
    if have_a and have_b:
        instr = HEADER_TWO + SIDES + "\nFor each side there are two versions:\n" + MODELS["A"] + "\n" + MODELS["B"] + "\n" + STEPS_TWO + STEPS_REST
        sections = [_section("USER - Version A (Nemotron)", a["me"]), _section("USER - Version B (Moonshine)", second["me"]),
                    _section("SYSTEM - Version A (Nemotron)", a["them"]), _section("SYSTEM - Version B (Moonshine)", second["them"])]
    elif have_b:
        instr = HEADER_ONE.format(model="Moonshine") + SIDES + STEPS_ONE + STEPS_REST
        sections = [_section("USER", second["me"]), _section("SYSTEM", second["them"])]
    else:
        instr = HEADER_ONE.format(model="NVIDIA Nemotron") + SIDES + STEPS_ONE + STEPS_REST
        sections = [_section("USER", a["me"]), _section("SYSTEM", a["them"])]
    parts = [header, instr] + sections
    out = call_dir / f"Transcript for AI - {start:%d %b %Y %H.%M}.txt"
    out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return out
