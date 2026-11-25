# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Transcription jobs, each run as its own process:
    python -m callrec.post nemotron|moonshine during|after <call folder> [live]
    python -m callrec.post download          (fetch the Moonshine model)
Prints one JSON message per line on stdout so the window can show progress.
"""
import json
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

from . import config
from .config import SR


_last_log = [0.0]


def say(**msg):
    try:
        print(json.dumps(msg), flush=True)
    except (BrokenPipeError, OSError, ValueError):
        pass                      # the window/app went away; keep working and save results anyway
    import logging
    if msg.get("type") == "timing" or (msg.get("type") == "progress" and time.perf_counter() - _last_log[0] > 15):
        _last_log[0] = time.perf_counter()
        logging.info("PERF %s", json.dumps(msg))


def moonshine_model():
    import moonshine_voice as m
    arch = m.ModelArch.MEDIUM_STREAMING

    def prog(frac, what=""):
        try:
            say(type="progress", stage="download_moonshine", fraction=round(float(frac), 3))
        except Exception:
            pass

    config.MOONSHINE_DIR.mkdir(parents=True, exist_ok=True)
    path, arch = m.get_model_for_language("en", arch, cache_root=config.MOONSHINE_DIR, on_progress=prog)
    (config.MOONSHINE_DIR / ".ready").write_text(json.dumps({"path": str(path)}))
    return path, arch


def load_wav(p):
    w = wave.open(str(p))
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


class TrackReader:
    """Reads a track's audio as it is being written. During a call the recorder keeps appending to
    me.wav / them.wav; this picks up whatever is new each time. 'Recording finished' is signalled by
    call.json appearing in the call folder."""

    HEADER = 44

    def __init__(self, path):
        self.f = open(path, "rb")
        self.f.seek(self.HEADER)
        self.carry = b""

    def read_new(self, max_seconds=10):
        data = self.carry + self.f.read(int(max_seconds * SR) * 2)
        n = len(data) // 2 * 2
        self.carry = data[n:]
        return np.frombuffer(data[:n], dtype="<i2").astype(np.float32) / 32768

    def size_samples(self, path):
        return max(0, (Path(path).stat().st_size - self.HEADER) // 2)


def _tracks(call_dir):
    return [k for k in ("me", "them") if (call_dir / f"{k}.wav").exists()]


def _finished(call_dir):
    return (call_dir / "call.json").exists()


def _progress(stage, call_dir, done_samples):
    total = sum((Path(call_dir) / f"{k}.wav").stat().st_size - 44 for k in _tracks(call_dir)) // 2
    say(type="progress", stage=stage, fraction=round(min(1.0, done_samples / max(1, total)), 3),
        behind_s=round((total - done_samples) / SR / max(1, len(_tracks(call_dir))), 1))


# ---------------- Nemotron ----------------

def nemotron_run(call_dir, follow, live):
    """follow=True: runs during the call, transcribing audio as it is saved, then finishes the rest
    after Stop. follow=False: transcribes the finished files. live=True also reports lines as they come."""
    import sherpa_onnx
    call_dir = Path(call_dir)
    t0 = time.perf_counter()
    d = config.NEMOTRON_DIR
    threads = int(config.settings().get("threads") or 4)
    rec = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(d / "tokens.txt"), encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
        joiner=str(d / "joiner.int8.onnx"), num_threads=threads, sample_rate=SR, feature_dim=128,
        decoding_method="greedy_search", enable_endpoint_detection=True, rule1_min_trailing_silence=2.4,
        rule2_min_trailing_silence=1.2, rule3_min_utterance_length=300)
    load_s = time.perf_counter() - t0
    st = {}
    for k in _tracks(call_dir):
        st[k] = {"reader": TrackReader(call_dir / f"{k}.wav"), "s": rec.create_stream(), "sp": LineSplitter(k),
                 "pos": 0, "seg_start": 0, "zero_run": 0, "sent": 0, "partial": ""}
    step = SR // 2
    decode_s, last_say = 0.0, 0.0

    def emit_new(k, x):
        if not live:
            return
        for l in x["sp"].lines[x["sent"]:]:
            say(type="line", model="nemotron", line=l)
        x["sent"] = len(x["sp"].lines)

    while True:
        done = _finished(call_dir) if follow else True
        got_any = False
        for k, x in st.items():
            a = x["reader"].read_new()
            if not len(a):
                continue
            got_any = True
            s, sp = x["s"], x["sp"]
            c0 = time.perf_counter()
            for i in range(0, len(a), step):
                y = a[i:i + step]
                x["zero_run"] = x["zero_run"] + len(y) if not np.any(y) else 0
                if x["zero_run"] > int(1.5 * SR):            # nothing playing: skip dead air
                    if x["zero_run"] - len(y) <= int(1.5 * SR):
                        while rec.is_ready(s):
                            rec.decode_stream(s)
                        sp.update(rec.get_result(s).strip(), x["pos"], x["seg_start"], final=True)
                        rec.reset(s); sp.reset()
                    x["pos"] += len(y); x["seg_start"] = x["pos"]
                    continue
                s.accept_waveform(SR, y)
                x["pos"] += len(y)
                while rec.is_ready(s):
                    rec.decode_stream(s)
                if rec.is_endpoint(s):
                    sp.update(rec.get_result(s).strip(), x["pos"], x["seg_start"], final=True)
                    rec.reset(s); sp.reset(); x["seg_start"] = x["pos"]
                else:
                    sp.update(rec.get_result(s).strip(), x["pos"], x["seg_start"])
            decode_s += time.perf_counter() - c0
            emit_new(k, x)
            if live:
                part = rec.get_result(s).strip()[sp.committed:].strip()
                if part != x["partial"]:
                    x["partial"] = part
                    say(type="partial", model="nemotron", key=k, text=part)
        if time.perf_counter() - last_say > 2:
            last_say = time.perf_counter()
            _progress("nemotron", call_dir, sum(x["pos"] for x in st.values()))
        if not got_any:
            if done:
                break
            time.sleep(0.3)
    for k, x in st.items():
        s, sp = x["s"], x["sp"]
        s.accept_waveform(SR, np.zeros(SR * 2, dtype=np.float32))
        s.input_finished()
        while rec.is_ready(s):
            rec.decode_stream(s)
        sp.update(rec.get_result(s).strip(), x["pos"], x["seg_start"], final=True)
        emit_new(k, x)
        if live:
            say(type="partial", model="nemotron", key=k, text="")
    lines = sorted([l for x in st.values() for l in x["sp"].lines], key=lambda l: l["start"])
    for n, l in enumerate(lines):
        l["id"] = n
    (call_dir / "nemotron_lines.json").write_text(json.dumps(lines, indent=1))
    audio_s = sum(x["pos"] for x in st.values()) / SR
    say(type="progress", stage="nemotron", fraction=1.0, behind_s=0)
    say(type="timing", model="nemotron", mode="during" if follow else "after", seconds=round(time.perf_counter() - t0, 1),
        busy_s=round(decode_s, 1), load_s=round(load_s, 1), audio_s=round(audio_s, 1), threads=threads,
        speed_x=round(audio_s / decode_s, 2) if decode_s else None)


# ---------------- Moonshine ----------------

def moonshine_run(call_dir, follow, live):
    """Moonshine works on chunks of audio (about 30 s during a call, 90 s after), cut at quiet moments."""
    import moonshine_voice as m
    call_dir = Path(call_dir)
    t0 = time.perf_counter()
    path, arch = moonshine_model()
    tr = m.Transcriber(path, arch)
    target = 30 if follow else 90
    st = {k: {"reader": TrackReader(call_dir / f"{k}.wav"), "buf": np.zeros(0, np.float32), "offset": 0, "lines": []}
          for k in _tracks(call_dir)}
    busy, last_say = 0.0, 0.0

    def do_chunk(k, x, n):
        nonlocal busy
        seg = x["buf"][:n]
        if len(seg) and float(np.max(np.abs(seg))) >= 1e-4:
            c0 = time.perf_counter()
            res = tr.transcribe_without_streaming(seg.tolist(), SR)
            busy += time.perf_counter() - c0
            for ln in res.lines:
                txt = (ln.text or "").strip()
                if txt:
                    l = {"key": k, "start": round(x["offset"] / SR + ln.start_time, 2),
                         "end": round(x["offset"] / SR + ln.start_time + ln.duration, 2), "text": txt, "echo": False}
                    x["lines"].append(l)
                    if live:
                        say(type="line", model="moonshine", line=l)
        x["buf"] = x["buf"][n:]
        x["offset"] += n

    def cut_point(a):
        lo, hi = (target - 10) * SR, min(len(a), (target + 10) * SR)
        hop = SR // 5
        best, best_e = target * SR, None
        for i in range(lo, hi - hop, hop // 2):
            e = float(np.mean(a[i:i + hop] ** 2))
            if best_e is None or e < best_e:
                best_e, best = e, i + hop // 2
        return best

    while True:
        done = _finished(call_dir) if follow else True
        got_any = False
        for k, x in st.items():
            a = x["reader"].read_new(max_seconds=60)
            if len(a):
                got_any = True
                x["buf"] = np.concatenate([x["buf"], a])
            while len(x["buf"]) >= (target + 10) * SR:
                do_chunk(k, x, cut_point(x["buf"]))
        if time.perf_counter() - last_say > 2:
            last_say = time.perf_counter()
            _progress("moonshine", call_dir, sum(x["offset"] for x in st.values()))
        if not got_any:
            if done:
                break
            time.sleep(1.0)
    for k, x in st.items():
        if len(x["buf"]):
            do_chunk(k, x, len(x["buf"]))
        (call_dir / f"second_pass_{k}.json").write_text(json.dumps(x["lines"], indent=1))
    audio_s = sum(x["offset"] for x in st.values()) / SR
    say(type="progress", stage="moonshine", fraction=1.0, behind_s=0)
    say(type="timing", model="moonshine", mode="during" if follow else "after", seconds=round(time.perf_counter() - t0, 1),
        busy_s=round(busy, 1), audio_s=round(audio_s, 1), speed_x=round(audio_s / busy, 2) if busy else None)


class LineSplitter:
    """Turns Nemotron's running text into lines: split at sentence ends, or at the model's own pauses."""

    def __init__(self, key):
        self.key, self.committed, self.pend_start, self.lines = key, 0, None, []

    def update(self, txt, pos, seg_start, final=False):
        pend = txt[self.committed:]
        lead = len(pend) - len(pend.lstrip())
        pend = pend.strip()
        if not pend:
            self.pend_start = None
            return
        if self.pend_start is None:
            self.pend_start = max(seg_start, pos - SR) / SR
        cut = len(pend) if final else None
        if cut is None:
            # a sentence ends at . ? ! followed by a space (not at the very end: "1." may become "1.696")
            for mt in re.finditer(r"(?<!\d)[.?!]\s|(?<=\d)[.?!]\s(?=\D)", pend):
                if len(pend[:mt.end()].split()) >= 6:
                    cut = mt.end()
            if cut is None and len(pend.split()) > 45:
                commas = [mt.end() for mt in re.finditer(r",\s", pend) if len(pend[:mt.end()].split()) >= 15]
                cut = commas[-1] if commas else len(" ".join(pend.split()[:40]))
        if cut:
            text = re.sub(r"(?<=[A-Za-z0-9])\$", " $", pend[:cut].strip())     # "at$1.6bn" -> "at $1.6bn"
            if text:
                self.lines.append({"key": self.key, "start": round(self.pend_start, 2), "end": round(pos / SR, 2),
                                   "text": text, "echo": False})
            self.committed += lead + cut
            self.pend_start = (pos / SR) if pend[cut:].strip() else None

    def reset(self):
        self.committed, self.pend_start = 0, None


if __name__ == "__main__":
    import logging
    logging.basicConfig(filename=str(config.LOG_FILE), level=logging.INFO,
                        format="%(asctime)s %(levelname)s [" + " ".join(sys.argv[1:3]) + "] %(message)s")
    from .winperf import opt_out_of_throttling
    logging.info("PERF pass start: %s", opt_out_of_throttling())
    try:
        _main_t0 = time.perf_counter()
        cmd = sys.argv[1]
        if cmd == "download":
            moonshine_model()
            say(type="result", ok=True)
        elif cmd in ("nemotron", "moonshine"):
            mode = sys.argv[2]                      # "during" (follow the recording) or "after"
            call_dir = sys.argv[3]
            live = len(sys.argv) > 4 and sys.argv[4] == "live"
            (nemotron_run if cmd == "nemotron" else moonshine_run)(call_dir, mode == "during", live)
    except Exception:
        logging.exception("pass failed")
        raise
    logging.info("PERF pass done in %.1fs", time.perf_counter() - _main_t0)
