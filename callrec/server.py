# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Local web server behind the app window (only reachable from this computer)."""
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, models
from .engine import Session
from .jobs import CallJobs, RUNNING

log = logging.getLogger("callrec")
UI_FILE = Path(__file__).with_name("ui.html")


class App:
    def __init__(self, capture_factory):
        self.capture_factory = capture_factory
        self.clients = []
        self.lock = threading.Lock()
        self.state = "starting"          # setup | idle | recording | stopping | processing | done | error
        self.session = None
        self.lines = []
        self.info = {}
        self.setup = {"nemotron": 0.0, "moonshine": 0.0}
        self.last_result = None
        self.jobs = None
        self.code_stamp = config.code_stamp()
        self.quit_requested = False             # a newer version is starting and asked us to step aside
        self.close_window_requested = False   # "finish in background": close the window now,
        self.quit_when_done = False           # quit once the double-check is done

    # ---------- events to the window ----------
    def emit(self, ev):
        if ev.get("type") == "line":
            self.lines.append(ev["line"])
        elif ev.get("type") == "echo":
            for l in self.lines:
                if l["id"] == ev["id"]:
                    l["echo"] = True
        with self.lock:
            for q in list(self.clients):
                q.put(ev)

    def set_state(self, state, **extra):
        self.state = state
        self.info.update(extra)
        self.emit({"type": "state", "state": state, **self.info})

    def snapshot(self):
        return {"type": "snapshot", "state": self.state, "info": self.info, "lines": self.lines,
                "settings": self.settings_view(),
                "jobs": self.jobs.status() if self.jobs else [],
                "pending": len(self.pending_calls()) if self.state in ("idle", "done") else 0,
                "setup": self.setup, "result": self.last_result, "notes_dir": str(config.notes_root())}

    # ---------- first run ----------
    def ensure_models(self):
        """Download whatever models the current options need (Moonshine only if it is switched on)."""
        s = config.settings()
        need_moon = s.get("moonshine") != "off" and not config.moonshine_ready()
        if config.nemotron_ready() and not need_moon:
            self._preload()
            return
        self.set_state("setup")
        try:
            def p(name):
                def f(x):
                    self.setup[name] = round(x, 3)
                    self.emit({"type": "setup", "setup": self.setup})
                return f
            if not config.nemotron_ready():
                models.download_nemotron(p("nemotron"))
            self.setup["nemotron"] = 1.0
            if need_moon:
                models.download_moonshine(p("moonshine"))
            self.setup["moonshine"] = 1.0
            self._preload()
        except Exception as e:
            log.exception("model download")
            self.set_state("error", error=f"Could not download the speech models ({e}). "
                                          "Check your internet connection and reopen the app.")

    def _ticker(self):
        """Every half second while a call is active: what each transcription model is doing."""
        while self.state in ("recording", "stopping", "processing", "exporting"):
            if self.jobs:
                try:
                    self.emit({"type": "jobs", "jobs": self.jobs.status()})
                except Exception:
                    pass
            time.sleep(0.5)
        if self.jobs:
            self.emit({"type": "jobs", "jobs": self.jobs.status()})

    def save_settings(self, new):
        s = config.save_settings(new)
        log.info("settings: %s", s)
        if s.get("moonshine") != "off" and not config.moonshine_ready() and self.state in ("idle", "done"):
            self.setup = {"nemotron": 1.0, "moonshine": 0.0}
            threading.Thread(target=self.ensure_models, daemon=True).start()
        self.emit({"type": "settings", "settings": self.settings_view()})
        return {"ok": True, "settings": self.settings_view()}

    def _preload(self):
        """Load the live model once at startup so pressing Record is instant (only if live mode is on)."""
        from .engine import LiveASR
        if config.settings().get("live_transcription", False):
            self.set_state("loading")
            LiveASR.load()
        self.set_state("idle", pending=len(self.pending_calls()))

    # ---------- recording ----------
    def start(self, want_me=True, want_them=True):
        if self.state not in ("idle", "done"):
            return {"ok": False, "error": f"busy ({self.state})"}
        self.lines = []
        self.last_result = None
        self.info = {}
        try:
            self.session = Session(self.emit, self.capture_factory, want_me, want_them)
            res = self.session.start()
            self.jobs = CallJobs(self.session.dir, self.emit)
            self.jobs.start_during()
        except Exception as e:
            log.exception("start")
            self.set_state("idle", error=f"Could not start recording: {e}")
            return {"ok": False, "error": str(e)}
        log.info("PERF record pressed -> recording")
        self.set_state("recording", devices=res["devices"], warnings=res["warnings"],
                       folder=str(self.session.dir), error=None, notice=None, export=None,
                       started=self.session.started.isoformat(timespec="seconds"))
        threading.Thread(target=self._ticker, daemon=True).start()
        return {"ok": True}

    def stop(self):
        if self.state != "recording":
            return {"ok": False}
        self.set_state("stopping")
        threading.Thread(target=self._finish, daemon=True).start()
        return {"ok": True}

    def _finish(self):
        s = self.session
        try:
            s.stop()
            dur = json.loads((s.dir / "call.json").read_text()).get("duration_sec")
            self.set_state("processing", duration=dur)
            errors = self.jobs.finish()
            self.set_state("exporting")
            self.last_result = self._complete(s.dir)
            self.last_result["files"] = sorted(p.name for p in s.dir.iterdir() if not p.name.startswith("."))
            msg = ("Note: " + "; ".join(f"{k} failed ({v})" for k, v in errors.items())) if errors else None
            self.set_state("done", **self.last_result, pending=len(self.pending_calls()), error=msg)
        except Exception as e:
            log.exception("finish")
            self.last_result = {"export": None, "folder": str(s.dir)}
            self.set_state("done", folder=str(s.dir), export=None,
                           error=f"The recording is saved, but transcription failed: {e}")

    def _complete(self, call_dir, show=True):
        from .export import build_export
        out = build_export(call_dir)
        (call_dir / ".double-checked").write_text("1")
        self._show_transcript(call_dir, show=show)
        return {"export": str(out), "folder": str(call_dir)}

    def shutdown(self):
        """Window closed: save whatever is being recorded, stop everything, exit."""
        from . import engine
        log.info("shutdown requested in state %s", self.state)
        try:
            if self.state == "recording" and self.session:
                self.state = "stopping"
                self.session.stop()                       # closes and saves the audio files
                for p in list(RUNNING):                   # stop the background transcription
                    if p.poll() is None:
                        p.kill()
            elif self.state in ("stopping", "processing", "exporting", "catching_up"):
                for p in list(RUNNING):
                    if p.poll() is None:
                        p.kill()
                if self.session:
                    for _ in range(100):                  # let an in-progress stop finish saving
                        if (self.session.dir / "live_lines.json").exists():
                            break
                        __import__("time").sleep(0.1)
                    self._export_live_only(self.session.dir)
        except Exception:
            log.exception("shutdown")

    def _export_live_only(self, call_dir):
        try:
            from .export import build_export
            build_export(call_dir)
        except Exception:
            log.exception("export on shutdown")

    def pending_calls(self):
        """Calls whose double-check never ran (e.g. the window was closed early)."""
        root = config.notes_root()
        out = []
        if root.exists():
            for d in sorted(root.iterdir()):
                if d.is_dir() and (d / "live_lines.json").exists() and not (d / ".double-checked").exists() \
                        and (self.session is None or d != self.session.dir or self.state in ("idle", "done")):
                    out.append(d)
        return out

    def finish_pending(self):
        if self.state not in ("idle", "done"):
            return {"ok": False}
        dirs = self.pending_calls()
        if not dirs:
            return {"ok": False}
        threading.Thread(target=self._run_pending, args=(dirs,), daemon=True).start()
        return {"ok": True}

    def _run_pending(self, dirs):
        """Transcribe earlier calls that were interrupted. Their transcripts are saved to their own
        folders; the screen keeps showing the current call."""
        prev_state, prev_info, prev_result = self.state, dict(self.info), self.last_result
        self.set_state("catching_up", pending_total=len(dirs), notice=None)
        done, failed = [], []
        for d in dirs:
            try:
                self.jobs = CallJobs(d, self.emit)
                threading.Thread(target=self._ticker, daemon=True).start()
                self.jobs.finish(all_after=True)
                self._complete(d, show=False)
                done.append(d)
            except Exception:
                log.exception("pending")
                failed.append(d.name)
        self.jobs = None
        self.info = prev_info
        self.last_result = prev_result
        note = (f"Transcribed {len(done)} earlier call{'s' if len(done) != 1 else ''}. "
                "Find them in Saved calls.") if done else None
        self.set_state(prev_state if prev_state in ("idle", "done") else "idle",
                       pending=len(self.pending_calls()), notice=note,
                       error=("Could not transcribe: " + ", ".join(failed)) if failed else None)

    def finish_in_background(self):
        if self.state in ("stopping", "processing", "exporting", "catching_up"):
            self.quit_when_done = True
            self.close_window_requested = True
            return {"ok": True}
        return {"ok": False}

    def _show_transcript(self, call_dir, show=True):
        import json as _j
        from .export import _flag_echo
        try:
            if (call_dir / "nemotron_lines.json").exists():
                lines = _j.loads((call_dir / "nemotron_lines.json").read_text())
            else:
                lines = []
                for k in ("me", "them"):
                    f = call_dir / f"second_pass_{k}.json"
                    if f.exists():
                        lines += [dict(l, key=k) for l in _j.loads(f.read_text())]
                lines.sort(key=lambda l: l["start"])
                for n, l in enumerate(lines):
                    l["id"] = n
        except Exception:
            return
        _flag_echo([l for l in lines if l["key"] == "me"], [l for l in lines if l["key"] == "them"])
        if show:
            self.lines = lines
        try:                                   # a plain, readable transcript next to the audio
            from .engine import fmt_ts, LABEL
            with open(call_dir / "Transcript.txt", "w", encoding="utf-8") as f:
                for l in lines:
                    f.write(f"[{fmt_ts(l['start'])}] {LABEL[l['key']]}: {l['text']}"
                            f"{'  (echo from speakers)' if l.get('echo') else ''}\n")
            old = call_dir / "live transcript.txt"
            if old.exists() and old.stat().st_size == 0:
                old.unlink()
        except Exception:
            log.exception("transcript file")
        if show:
            self.emit({"type": "lines", "lines": lines})

    def choose_folder(self):
        """Ask Windows for a folder (the standard folder picker), then save calls there."""
        if self.busy():
            return {"ok": False, "error": "Wait until the current call is finished."}
        current = str(config.notes_root())
        if sys.platform != "win32":
            return {"ok": False, "error": "Folder picker is only available on Windows."}
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$f.Description = 'Choose where FreeCallNotes saves your calls';"
            "$f.ShowNewFolderButton = $true;"
            f"$f.SelectedPath = '{current.replace(chr(39), chr(39) * 2)}';"
            "$o = New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
            "if ($f.ShowDialog($o) -eq 'OK') { [Console]::Out.Write($f.SelectedPath) }"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", ps],
                           capture_output=True, text=True, encoding="utf-8", creationflags=0x08000000)
        path = (r.stdout or "").strip()
        if not path:
            return {"ok": False, "cancelled": True}
        return self.set_folder(path)

    def set_folder(self, path):
        p = Path(path) if path else None
        try:
            if p:
                p.mkdir(parents=True, exist_ok=True)
                test = p / ".callrec-write-test"
                test.write_text("1"); test.unlink()
        except Exception as e:
            return {"ok": False, "error": f"Can't save to that folder ({e}). Choose another."}
        s = config.set_notes_dir(p)
        log.info("notes folder: %s", config.notes_root())
        self.emit({"type": "settings", "settings": self.settings_view()})
        return {"ok": True, "settings": self.settings_view()}

    def settings_view(self):
        s = config.settings()
        s["notes_dir_effective"] = str(config.notes_root())
        s["notes_dir_default"] = str(config.default_notes_root())
        s["notice_version"] = config.NOTICE_VERSION
        s["app_version"] = config.VERSION
        return s

    def busy(self):
        return self.state in ("recording", "stopping", "processing", "exporting", "catching_up")

    def fresh_start(self):
        """The app was opened again: clear the last call off the screen (it stays in Saved calls)."""
        if self.state not in ("idle", "done"):
            return {"ok": False}
        self.lines = []
        self.last_result = None
        self.info = {}
        self.set_state("idle", pending=len(self.pending_calls()))
        return {"ok": True}


def open_path(path, select=False):
    if sys.platform == "win32":
        if select:
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path))
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent if select else path)])


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                b = UI_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)
            elif self.path == "/api/state":
                self._json(app.snapshot())
            elif self.path == "/api/settings":
                self._json(config.settings())
            elif self.path == "/api/version":
                self._json({"code_stamp": app.code_stamp, "busy": app.busy()})
            elif self.path == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                q = queue.Queue()
                with app.lock:
                    app.clients.append(q)
                try:
                    self.wfile.write(f"data: {json.dumps(app.snapshot())}\n\n".encode())
                    self.wfile.flush()
                    while True:
                        try:
                            ev = q.get(timeout=2)   # short ping, so a closed window is noticed quickly
                            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with app.lock:
                        if q in app.clients:
                            app.clients.remove(q)
            else:
                self.send_error(404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            try:
                if self.path == "/api/start":
                    self._json(app.start(body.get("me", True), body.get("them", True)))
                elif self.path == "/api/stop":
                    self._json(app.stop())
                elif self.path == "/api/settings":
                    self._json(app.save_settings(body))
                elif self.path == "/api/accept_notice":
                    config.accept_notice()
                    app.emit({"type": "settings", "settings": app.settings_view()})
                    self._json({"ok": True})
                elif self.path == "/api/quit":
                    if app.busy():
                        self._json({"ok": False, "busy": True})
                    else:
                        self._json({"ok": True})
                        app.quit_requested = True
                elif self.path == "/api/choose_folder":
                    self._json(app.choose_folder())
                elif self.path == "/api/reset_folder":
                    self._json(app.set_folder(None))
                elif self.path == "/api/finish_pending":
                    self._json(app.finish_pending())
                elif self.path == "/api/fresh":
                    self._json(app.fresh_start())
                elif self.path == "/api/finish_in_background":
                    self._json(app.finish_in_background())
                elif self.path == "/api/open":
                    what = body.get("what")
                    if what == "export" and app.last_result and app.last_result.get("export"):
                        open_path(app.last_result["export"], select=True)
                    elif what == "folder" and app.last_result:
                        open_path(app.last_result["folder"])
                    elif what == "legal":
                        open_path(config.APP_DIR / "legal")
                    elif what == "all":
                        config.notes_root().mkdir(parents=True, exist_ok=True)
                        open_path(config.notes_root())
                    self._json({"ok": True})
                else:
                    self.send_error(404)
            except Exception as e:
                log.error(traceback.format_exc())
                self._json({"ok": False, "error": str(e)}, 500)
    return H


def serve(app, port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
