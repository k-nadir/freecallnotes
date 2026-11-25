# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Runs the transcription jobs for one call, each in its own background process.

"during" jobs start when Record is pressed and follow the audio files as they're written;
"after" jobs start when Stop is pressed. Either way, nothing here can slow down the recording.
"""
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config

log = logging.getLogger("callrec")
RUNNING = []          # every job process, so closing the window can stop them all


def console_python():
    exe = Path(sys.executable)
    alt = exe.with_name("python.exe")
    return str(alt) if exe.name.lower() == "pythonw.exe" and alt.exists() else sys.executable


class Job:
    def __init__(self, model, mode, call_dir, live, emit):
        self.model, self.mode = model, mode
        self.emit = emit
        self.fraction, self.behind, self.timing, self.error = 0.0, None, None, None
        cmd = [console_python(), "-m", "callrec.post", model, mode, str(call_dir)] + (["live"] if live else [])
        flags = 0x08000000 if sys.platform == "win32" else 0        # no console window
        self.p = subprocess.Popen(cmd, cwd=str(config.APP_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding="utf-8", creationflags=flags)
        RUNNING.append(self.p)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for raw in self.p.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            t = msg.get("type")
            if t == "progress":
                self.fraction = msg.get("fraction", 0.0)
                self.behind = msg.get("behind_s")
            elif t == "timing":
                self.timing = msg
            elif t in ("line", "partial"):
                self.emit(msg)
        err = self.p.stderr.read()
        if self.p.wait() != 0:
            self.error = err.strip().splitlines()[-1] if err.strip() else "failed"
            log.error("%s %s job failed: %s", self.model, self.mode, err[-3000:])

    def wait(self):
        self.reader.join()

    def status(self):
        running = self.p.poll() is None
        state = "running" if running else ("failed" if self.error or self.p.returncode else "done")
        return {"model": self.model, "mode": self.mode, "state": state,
                "fraction": round(self.fraction, 3), "behind": self.behind}


class CallJobs:
    def __init__(self, call_dir, emit, settings=None):
        self.call_dir = Path(call_dir)
        self.emit = emit
        self.s = settings or config.settings()
        self.jobs = []

    def models(self, mode):
        return [m for m in ("nemotron", "moonshine") if self.s.get(m) == mode]

    def start_during(self):
        """At Record. Live display goes to the first model running during the call."""
        live_model = self.models("during")[0] if self.s.get("show_live") and self.models("during") else None
        for m in self.models("during"):
            self.jobs.append(Job(m, "during", self.call_dir, m == live_model, self._live_emit))

    def _live_emit(self, msg):
        self.emit({"type": "live_" + msg["type"], **{k: v for k, v in msg.items() if k != "type"}})

    def finish(self, all_after=False):
        """At Stop (call.json already written): start the 'after' jobs, wait for everything, return timings.
        all_after=True runs every enabled model from scratch (finishing a call that was interrupted)."""
        t0 = time.perf_counter()
        if all_after:
            self.jobs = [Job(m, "after", self.call_dir, False, self._live_emit)
                         for m in ("nemotron", "moonshine") if self.s.get(m) != "off"]
        else:
            for m in self.models("after"):
                self.jobs.append(Job(m, "after", self.call_dir, False, self._live_emit))
        while any(j.p.poll() is None for j in self.jobs):
            time.sleep(0.3)
        for j in self.jobs:
            j.wait()
        total = time.perf_counter() - t0
        timings = {j.model: j.timing for j in self.jobs}
        errors = {j.model: j.error for j in self.jobs if j.error}
        log.info("PERF after Stop: transcripts ready in %.0fs; %s", total, json.dumps(timings))
        try:
            tel = json.loads((self.call_dir / "telemetry.json").read_text())
        except Exception:
            tel = {}
        tel["transcription"] = {"ready_after_stop_s": round(total, 1), "settings": self.s, **timings}
        if errors:
            tel["errors"] = errors
        (self.call_dir / "telemetry.json").write_text(json.dumps(tel, indent=1))
        if self.jobs and len(errors) == len(self.jobs):
            raise RuntimeError("; ".join(f"{k}: {v}" for k, v in errors.items()))
        return errors

    def status(self):
        """What each model is doing, for the status display (models not started yet show as waiting)."""
        out = [j.status() for j in self.jobs]
        started = {(j.model) for j in self.jobs}
        for m in self.models("after"):
            if m not in started:
                out.append({"model": m, "mode": "after", "state": "waiting", "fraction": 0, "behind": None})
        return out

    def kill(self):
        for j in self.jobs:
            if j.p.poll() is None:
                j.p.kill()
