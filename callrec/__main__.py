# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Start FreeCallNotes:  pythonw -m callrec
Test mode:      python -m callrec --test-files me.wav them.wav --no-window
"""
import argparse
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import config
from .server import App, serve

PORT = 47123


def setup_logging():
    logging.basicConfig(filename=str(config.LOG_FILE), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    sys.excepthook = lambda *e: logging.getLogger("callrec").error("crash", exc_info=e)


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1):
            return True
    except Exception:
        return False


def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return p
    return None


def open_window(url):
    """Opens the app as its own window (Edge 'app mode': no tabs or address bar).
    Returns the window's process, or None if we fell back to the normal browser."""
    edge = find_edge()
    if edge:
        profile = config.APP_DIR / "window-profile"
        return subprocess.Popen([str(edge), f"--app={url}", f"--user-data-dir={profile}",
                                 "--window-size=560,860", "--no-first-run", "--no-default-browser-check", "--disable-background-mode",
                                 "--disable-features=Translate,msUndersideButton"])
    import webbrowser
    webbrowser.open(url)
    return None


def make_desktop_shortcut():
    """Put a 'FreeCallNotes' icon on the desktop (and remove the shortcut older versions made)."""
    if sys.platform != "win32" or (config.APP_DIR / ".shortcut-v3").exists():
        return
    exe = config.APP_DIR / "FreeCallNotes.exe"
    pyw = Path(sys.executable).with_name("pythonw.exe")
    icon = config.APP_DIR / "callrec" / "icon.ico"
    target, args = (exe, "") if exe.exists() else (pyw, "-m callrec")
    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$old=Join-Path $d 'Call Recorder.lnk'; if (Test-Path $old) { Remove-Item $old -Force };"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'FreeCallNotes.lnk'));"
        f"$s.TargetPath='{target}';$s.Arguments='{args}';$s.WorkingDirectory='{config.APP_DIR}';"
        f"$s.IconLocation='{icon},0';$s.Description='Record and transcribe calls';$s.Save()"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       creationflags=0x08000000, timeout=30)
        (config.APP_DIR / ".shortcut-v3").write_text("1")
    except Exception:
        logging.getLogger("callrec").exception("shortcut")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-files", nargs=2, metavar=("ME_WAV", "THEM_WAV"))
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    setup_logging()
    import platform
    logging.getLogger("callrec").info("START v%s on %s | %s | cores=%s | python %s", config.VERSION, platform.platform(),
                                      platform.processor(), os.cpu_count(), platform.python_version())
    from .winperf import opt_out_of_throttling, power_status
    logging.getLogger("callrec").info("PERF windows: %s | power: %s", opt_out_of_throttling(), power_status())
    os.chdir(config.APP_DIR)
    url = f"http://127.0.0.1:{args.port}/"

    if already_running(args.port):
        # If the app's files were updated since the running copy started, ask it to quit (when it is
        # not in the middle of a call) and start the new version; otherwise just show its window.
        replaced = False
        try:
            import json as _json
            with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/version", timeout=2) as r:
                info = _json.loads(r.read())
            if info.get("code_stamp", 0) < config.code_stamp() and not info.get("busy"):
                req = urllib.request.Request(f"http://127.0.0.1:{args.port}/api/quit", data=b"{}", method="POST")
                urllib.request.urlopen(req, timeout=2).read()
                for _ in range(40):
                    time.sleep(0.25)
                    if not already_running(args.port):
                        replaced = True
                        break
                logging.getLogger("callrec").info("replaced older running copy: %s", replaced)
        except Exception:
            logging.getLogger("callrec").exception("version check")
        if not replaced:
            if not args.no_window:
                open_window(url)
            return

    if args.test_files:
        from .capture import FileCapture
        files = {"me": args.test_files[0], "them": args.test_files[1]}
        factory = lambda on_audio: FileCapture(on_audio, files)
    else:
        from .capture import WinCapture
        factory = WinCapture

    app = App(factory)
    serve(app, args.port)
    threading.Thread(target=app.ensure_models, daemon=True).start()
    threading.Thread(target=make_desktop_shortcut, daemon=True).start()

    if args.no_window:
        while not app.quit_requested:
            time.sleep(0.5)
        os._exit(0)

    win = open_window(url)
    # The window counts as closed when its process ends OR the page has been disconnected for 4 seconds
    # (Edge can keep a hidden background process alive, so we don't rely on the process alone).
    seen_page, gone_since = False, None
    t_open = time.monotonic()
    while True:
        time.sleep(0.5)
        if app.quit_requested:
            break
        if app.close_window_requested:                    # "Finish in background and close"
            app.close_window_requested = False
            if win is not None and win.poll() is None and sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(win.pid), "/T", "/F"], capture_output=True,
                               creationflags=0x08000000)
            while app.busy():
                time.sleep(1)
            break
        if win is not None and win.poll() is not None and (seen_page or time.monotonic() - t_open > 60):
            if not app.clients:
                break
        if app.clients:
            seen_page, gone_since = True, None
        elif seen_page:
            gone_since = gone_since or time.monotonic()
            if time.monotonic() - gone_since > 4:
                break
    if not app.quit_when_done:
        app.shutdown()
    if win is not None and win.poll() is None and sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(win.pid), "/T", "/F"], capture_output=True,
                       creationflags=0x08000000)
    logging.getLogger("callrec").info("exit")
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
