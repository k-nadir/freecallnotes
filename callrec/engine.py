# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Recording session: saves both tracks to disk and transcribes them live with Nemotron.

Data flow (nothing here ever blocks the audio capture):
  capture callback --> queue --> worker thread --> (1) append to me.wav / them.wav
                                                  (2) feed that track's Nemotron stream
                                                  (3) emit live lines / partial text to the window
After Stop, the after-call pass (post.py) runs in a separate process.
"""
import difflib
import json
import os
import logging
import queue
import re
import subprocess
import sys
from pathlib import Path as _P
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config
from .config import SR

log = logging.getLogger("callrec")
LABEL = {"me": "User", "them": "System"}


def fmt_ts(sec):
    sec = int(max(0, sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _words(t):
    return re.sub(r"[^a-z0-9 ]+", " ", t.lower()).split()


def is_echo(me_text, them_text):
    """True if a 'Me' line is mostly the other side's words leaking from the speakers into the mic.
    Compares word overlap, since each side's transcript of the same speech differs slightly."""
    a, b = _words(me_text), _words(them_text)
    if len(a) < 3 or not b:
        return False
    pool = {}
    for w in b:
        pool[w] = pool.get(w, 0) + 1
    hit = 0
    for w in a:
        if pool.get(w, 0) > 0:
            pool[w] -= 1
            hit += 1
    return hit >= 0.6 * len(a)


def overlaps(x, y, slack=3.0):
    return x["start"] - slack <= y["end"] and y["start"] - slack <= x["end"]


class LiveASR:
    """One Nemotron model, one independent stream per track."""

    _recognizer = None
    threads = None

    @classmethod
    def load(cls):
        if cls._recognizer is None:
            import os
            import sherpa_onnx
            t0 = time.perf_counter()
            threads = int(config.settings().get("threads") or 4)
            cls.threads = threads
            d = config.NEMOTRON_DIR
            cls._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(d / "tokens.txt"), encoder=str(d / "encoder.int8.onnx"),
                decoder=str(d / "decoder.int8.onnx"), joiner=str(d / "joiner.int8.onnx"),
                num_threads=threads, sample_rate=SR, feature_dim=128, decoding_method="greedy_search",
                enable_endpoint_detection=True, rule1_min_trailing_silence=2.4,
                rule2_min_trailing_silence=1.2, rule3_min_utterance_length=300)
            log.info("PERF live model loaded in %.1fs using %d threads", time.perf_counter() - t0, threads)
        return cls._recognizer


class Session:
    """One recorded call. Four independent jobs run side by side, so none can hold up another:
      1. capture   (audio driver thread): measures volume instantly, timestamps each chunk, queues it
      2. saver     (thread): writes both tracks to disk and keeps them on the real clock
      3. transcriber (thread): feeds the saved audio to Nemotron and produces live lines
      4. display   (thread): sends the timer and volume bars to the window every 0.15 s
    """

    def __init__(self, emit, capture_factory, want_me=True, want_them=True):
        self.emit = emit
        self.started = datetime.now()
        self.dir = config.notes_root() / self.started.strftime("%Y-%m-%d %H.%M.%S")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.q = queue.Queue()
        self.capture = capture_factory(self._on_audio)
        self.want = {"me": want_me, "them": want_them}
        self.live = False      # transcription now runs in separate background jobs (see jobs.py)
        self.rec = LiveASR.load() if self.live else None
        self.tracks = {}
        self.lines = []
        self.lock = threading.Lock()
        self.capturing = threading.Event()
        self.saver_done = threading.Event()
        self.t0 = None
        self.warnings = []
        self.decode_time = 0.0
        self.decoded = 0
        self.live_truncated = False
        self.tm = {"samples": [], "step_ms": [], "steps": 0, "w_audio": 0, "w_decode": 0.0,
                   "max_lag": 0.0, "cpu_last": time.process_time()}

    # ---------- 1. capture callback: must be instant ----------
    def _on_audio(self, key, x):
        now = time.monotonic()
        t = self.tracks.get(key)
        if t is not None and len(x):
            t["level"] = float(np.sqrt(np.mean(x * x)))
            t["last_arrival"] = now
        self.q.put((key, x, now))

    # ---------- lifecycle ----------
    def start(self):
        t_start = time.perf_counter()
        self.t0 = time.monotonic()
        # create track slots before audio starts flowing
        self.capturing.set()
        self.warnings = self.capture.start(self.want["me"], self.want["them"]) or []
        log.info("PERF capture started in %.2fs: %s", time.perf_counter() - t_start, self.capture.devices)
        for key in ("me", "them"):
            if key in self.capture.devices:
                w = wave.open(str(self.dir / f"{key}.wav"), "wb")
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
                self.tracks[key] = {
                    "wav": w, "written": 0, "fed": 0, "pos": 0, "skip": 0, "seg_start": 0,
                    "noise": 0.003, "quiet": 0, "gated": False, "ring": [], "partial": "", "committed": 0,
                    "pend_start": None, "last_arrival": time.monotonic(), "pending": [],
                    "stream": self.rec.create_stream() if self.live else None, "level": 0.0,
                    "device": self.capture.devices[key]}
        self.live_file = open(self.dir / "live transcript.txt", "w", encoding="utf-8")
        jobs = [(self._saver, "saver"), (self._display, "display")]
        if self.live:
            jobs.append((self._transcriber, "transcriber"))
        self.threads = [threading.Thread(target=f, daemon=True, name=n) for f, n in jobs]
        for th in self.threads:
            th.start()
        return {"devices": {k: t["device"] for k, t in self.tracks.items()}, "warnings": self.warnings}

    def stop(self):
        try:
            self.capture.stop()
        except Exception:
            log.exception("capture stop")
        self.capturing.clear()
        for th in self.threads:
            th.join(timeout=600)          # transcriber finishes any backlog before we close
        for key, t in self.tracks.items():
            if self.live:
                s = t["stream"]
                s.accept_waveform(SR, np.zeros(SR * 2, dtype=np.float32))
                s.input_finished()
                while self.rec.is_ready(s):
                    self.rec.decode_stream(s)
                self._update(key, t, final=True)
            t["wav"].close()
        self.live_file.close()
        with open(self.dir / "live transcript.txt", "w", encoding="utf-8") as f:
            for l in sorted(self.lines, key=lambda l: l["start"]):
                f.write(f"[{fmt_ts(l['start'])}] {LABEL[l['key']]}: {l['text']}\n")
        duration = max((t["written"] for t in self.tracks.values()), default=0) / SR
        meta = {"started": self.started.isoformat(timespec="seconds"), "duration_sec": round(duration, 1),
                "live_transcription": self.live, "live_transcript_incomplete": self.live_truncated,
                "devices": {k: t["device"] for k, t in self.tracks.items()}, "app_version": config.VERSION}
        (self.dir / "live_lines.json").write_text(json.dumps(self.lines, indent=1))
        (self.dir / "telemetry.json").write_text(json.dumps({"duration_s": round(duration, 1)}, indent=1))
        tmp = self.dir / "call.json.tmp"
        tmp.write_text(json.dumps(meta, indent=2))
        tmp.replace(self.dir / "call.json")       # appears in one step, so jobs never read half a file
        overall = (self.decoded / SR) / self.decode_time if self.decode_time else None
        if not self.live:
            return duration
        summary = {"duration_s": round(duration, 1), "overall_speed_x": round(overall, 2) if overall else None,
                   "needed_speed_x": len(self.tracks), "max_lag_s": round(self.tm["max_lag"], 1),
                   "skipped_pct": {k: round(100 * t["skip"] / max(t["pos"], 1)) for k, t in self.tracks.items()},
                   "live_transcription": self.live, "live_transcript_incomplete": self.live_truncated, "threads": LiveASR.threads,
                   "samples": self.tm["samples"]}
        (self.dir / "telemetry.json").write_text(json.dumps(summary, indent=1))
        log.info("PERF summary: speed %.2fx (need %d.0x), max lag %.1fs, skipped %s",
                 overall or 0, len(self.tracks), self.tm["max_lag"], summary["skipped_pct"])
        return duration

    # ---------- 2. saver ----------
    def _write(self, t, x):
        t["wav"].writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
        t["written"] += len(x)
        if self.live:
            with self.lock:
                t["pending"].append(x)

    def _saver(self):
        last_flush = time.monotonic()
        while True:
            if time.monotonic() - last_flush > 0.5:
                last_flush = time.monotonic()
                for t in self.tracks.values():
                    try:
                        t["wav"]._file.flush()
                    except Exception:
                        pass
            try:
                key, x, arrived = self.q.get(timeout=0.1)
                t = self.tracks.get(key)
                if t is not None and len(x):
                    # if this chunk arrived later than the track's clock says, the gap was silence
                    expected_start = int((arrived - self.t0) * SR) - len(x)
                    if expected_start - t["written"] > int(0.3 * SR):
                        self._write(t, np.zeros(expected_start - t["written"], dtype=np.float32))
                    self._write(t, x)
            except queue.Empty:
                if not self.capturing.is_set():
                    self.saver_done.set()
                    break
            # the computer's sound delivers nothing while silent: keep its track on the clock
            now = time.monotonic()
            for t in self.tracks.values():
                behind = int((now - self.t0) * SR) - t["written"]
                if now - t["last_arrival"] > 0.4 and behind > int(0.3 * SR):
                    self._write(t, np.zeros(behind - int(0.1 * SR), dtype=np.float32))

    # ---------- 3. transcriber ----------
    def _transcriber(self):
        last_perf = time.monotonic()
        while True:
            got = 0
            stopping = not self.capturing.is_set()
            for key, t in self.tracks.items():
                with self.lock:
                    chunks, t["pending"] = t["pending"], []
                if chunks and stopping and (t["written"] - t["pos"]) > 20 * SR:
                    # Stop pressed while live text was far behind: the audio is saved and the
                    # double-check will transcribe it, so skip the backlog instead of making you wait.
                    t["pos"] += sum(len(c) for c in chunks)
                    t["skip"] += sum(len(c) for c in chunks)
                    self.live_truncated = True
                    continue
                if chunks:
                    got += self._gate_and_feed(key, t, np.concatenate(chunks))
            if got:
                t0 = time.perf_counter()
                while True:
                    ready = [t["stream"] for t in self.tracks.values() if self.rec.is_ready(t["stream"])]
                    if not ready:
                        break
                    c0 = time.perf_counter()
                    self.rec.decode_streams(ready)
                    self.tm["step_ms"].append((time.perf_counter() - c0) * 1000)
                    self.tm["steps"] += 1
                dt = time.perf_counter() - t0
                self.decode_time += dt
                self.decoded += got
                self.tm["w_decode"] += dt
                self.tm["w_audio"] += got
                for key, t in self.tracks.items():
                    s = t["stream"]
                    if self.rec.is_endpoint(s):
                        self._update(key, t, final=True)
                        self.rec.reset(s)
                        t["committed"] = 0
                        t["seg_start"] = t["pos"]
                    else:
                        self._update(key, t)
            else:
                if self.saver_done.is_set() and all(not t["pending"] for t in self.tracks.values()):
                    break
                time.sleep(0.03)
            now = time.monotonic()
            lag_now = max(((t["written"] - t["pos"]) / SR for t in self.tracks.values()), default=0)
            self.tm["max_lag"] = max(self.tm["max_lag"], lag_now)
            if now - last_perf > 10:
                self._telemetry_sample(now, now - last_perf)
                last_perf = now

    def _gate_and_feed(self, key, t, x):
        """Only transcribe when someone is speaking on this track (roughly halves the work in a call).
        Quiet stretches longer than 1.5 s are skipped; the last 0.6 s before speech resumes is kept
        so first words aren't clipped. The track clock (pos) always advances, so timestamps stay right."""
        F = SR // 10
        fed = 0
        out = []
        for i in range(0, len(x), F):
            f = x[i:i + F]
            rms = float(np.sqrt(np.mean(f * f))) if len(f) else 0.0
            thr = max(0.004, t["noise"] * 3)
            if rms < thr:
                t["noise"] = 0.98 * t["noise"] + 0.02 * rms
                t["quiet"] += len(f)
            else:
                t["quiet"] = 0
            if t["gated"]:
                if rms >= thr:                                # speech resumes: replay the lead-in
                    t["gated"] = False
                    lead = np.concatenate(t["ring"]) if t["ring"] else np.zeros(0, np.float32)
                    t["ring"] = []
                    t["pos"] -= len(lead)                     # those samples were counted as skipped
                    t["skip"] -= len(lead)
                    t["seg_start"] = t["pos"]
                    out.append(lead)
                    out.append(f)
                else:
                    t["ring"].append(f)
                    while sum(len(r) for r in t["ring"]) > int(0.6 * SR):
                        t["ring"].pop(0)
                    t["pos"] += len(f)
                    t["skip"] += len(f)
                continue
            out.append(f)
            if t["quiet"] > int(1.5 * SR):                    # long pause: stop transcribing until speech
                if out:
                    a = np.concatenate(out); out = []
                    t["stream"].accept_waveform(SR, a); t["fed"] += len(a); t["pos"] += len(a); fed += len(a)
                    while self.rec.is_ready(t["stream"]):
                        self.rec.decode_stream(t["stream"])
                self._update(key, t, final=True)              # close the line before pausing
                self.rec.reset(t["stream"])
                t["committed"] = 0
                t["gated"] = True
                t["ring"] = []
        if out:
            a = np.concatenate(out)
            t["stream"].accept_waveform(SR, a)
            t["fed"] += len(a); fed += len(a)
            t["pos"] += len(a)
        return fed

    def _telemetry_sample(self, now, window):
        """Every 10 s: how fast the transcriber ran in THIS window, CPU use, step times, lag, power."""
        tm = self.tm
        cpu = time.process_time()
        cpu_pct = 100 * (cpu - tm["cpu_last"]) / max(window, 1e-6) / (os.cpu_count() or 1)
        tm["cpu_last"] = cpu
        steps = sorted(tm["step_ms"]) or [0]
        sample = {
            "t": round(now - self.t0),
            "speed_x": round((tm["w_audio"] / SR) / tm["w_decode"], 2) if tm["w_decode"] else None,
            "busy_pct": round(100 * tm["w_decode"] / window),
            "step_ms_p50": round(steps[len(steps) // 2], 1), "step_ms_p95": round(steps[int(len(steps) * .95)], 1),
            "lag_s": {k: round((t["written"] - t["pos"]) / SR, 1) for k, t in self.tracks.items()},
            "skipped_pct": {k: round(100 * t["skip"] / max(t["pos"], 1)) for k, t in self.tracks.items()},
            "cpu_pct_of_machine": round(cpu_pct), "queue": self.q.qsize(),
        }
        try:
            from .winperf import power_status
            sample["power"] = power_status()
        except Exception:
            pass
        tm["samples"].append(sample)
        log.info("PERF %s", json.dumps(sample))
        tm["w_audio"] = 0; tm["w_decode"] = 0.0; tm["step_ms"] = []

    # ---------- 4. display ----------
    def _display(self):
        while self.capturing.is_set():
            now = time.monotonic()
            levels = {k: (round(t["level"], 4) if now - t["last_arrival"] < 0.3 else 0.0) for k, t in self.tracks.items()}
            behind = max(((t["written"] - t["pos"]) / SR for t in self.tracks.values()), default=0) if self.live else 0
            self.emit({"type": "levels", "levels": levels, "elapsed": round(now - self.t0, 1), "behind": round(behind, 1)})
            time.sleep(0.15)

    # ---------- live lines ----------
    def _update(self, key, t, final=False):
        """The model keeps running without interruption (restarting it loses context and accuracy).
        Its running text is split into display lines at sentence ends; the rest shows as live text."""
        txt = self.rec.get_result(t["stream"]).strip()
        pend = txt[t["committed"]:]
        lead = len(pend) - len(pend.lstrip())
        pend = pend.strip()
        if not pend:
            t["pend_start"] = None
        else:
            if t["pend_start"] is None:   # speech for this line began a moment before its text appeared
                t["pend_start"] = max(t["seg_start"], t["pos"] - SR) / SR
            cut = len(pend) if final else None
            if cut is None:
                for m in re.finditer(r"[.?!](\s|$)", pend):
                    if len(pend[:m.end()].split()) >= 6:
                        cut = m.end()
                if cut is None and len(pend.split()) > 45:      # very long run-on: break at a comma, else after 40 words
                    commas = [m.end() for m in re.finditer(r",\s", pend) if len(pend[:m.end()].split()) >= 15]
                    cut = commas[-1] if commas else len(" ".join(pend.split()[:40]))
            if cut:
                self._add_line(key, pend[:cut].strip(), t["pend_start"], t["pos"] / SR)
                t["committed"] += lead + cut
                rest = pend[cut:].strip()
                t["pend_start"] = (t["pos"] / SR) if rest else None
                pend = rest
        if pend != t["partial"]:
            t["partial"] = pend
            self.emit({"type": "partial", "key": key, "text": pend})

    def _add_line(self, key, text, start, end):
        if not text:
            return
        line = {"id": len(self.lines), "key": key, "start": round(start, 2), "end": round(end, 2),
                "text": text, "echo": False}
        self.lines.append(line)
        # Echo check against the other side's lines around the same time
        me_lines = [l for l in self.lines if l["key"] == "me" and not l["echo"]]
        if key == "me":
            me_lines = [line]
        for m in me_lines:
            if m["echo"]:
                continue
            near = " ".join(o["text"] for o in self.lines if o["key"] == "them" and overlaps(m, o))
            if near and is_echo(m["text"], near):
                m["echo"] = True
                self.emit({"type": "echo", "id": m["id"]})
        self.live_file.write(f"[{fmt_ts(line['start'])}] {LABEL[key]}: {text}\n")
        self.live_file.flush()
        self.emit({"type": "line", "line": line})


def console_python():
    """pythonw.exe has no console; use python.exe (with no window) so progress messages reach us."""
    exe = _P(sys.executable)
    alt = exe.with_name("python.exe")
    return str(alt) if exe.name.lower() == "pythonw.exe" and alt.exists() else sys.executable
