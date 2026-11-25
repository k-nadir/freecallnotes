# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Call pop-ups: a small helper that runs in the background (if the user leaves "Call pop-ups" on).

It does no polling. It asks Windows to notify it whenever an app opens a microphone (the same audio-session
notifications volume mixers use), then sleeps. When Zoom, Teams, Webex, Slack, WhatsApp or a browser opens
the microphone and FreeCallNotes isn't already open, it shows a small pop-up in the corner of the screen:
"Call starting in Zoom" with Open FreeCallNotes / Not now / Don't show again. It never records anything.

    pythonw -m callrec.watcher            run the helper (started at sign-in from the Startup folder)
    pythonw -m callrec.watcher --demo X   just show the pop-up for app X (for testing)
"""
import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path

from . import config

log = logging.getLogger("callrec")
MUTEX_NAME = "Local\\FreeCallNotesCallPopups"
QUIT_EVENT_NAME = "Local\\FreeCallNotesCallPopupsQuit"
SHORTCUT_NAME = "FreeCallNotes call pop-ups.lnk"
APP_PORT = int(os.environ.get("CALLREC_APP_PORT", "47123"))   # the env var is only for testing
REPEAT_AFTER_S = 5 * 60          # the same app doesn't trigger another pop-up within 5 minutes
SHOW_FOR_S = 30                  # the pop-up closes itself after 30 seconds

CALL_APPS = {"zoom.exe": "Zoom", "ms-teams.exe": "Microsoft Teams", "msteams.exe": "Microsoft Teams",
             "teams.exe": "Microsoft Teams", "ciscocollabhost.exe": "Webex", "webexmta.exe": "Webex",
             "atmgr.exe": "Webex", "webex.exe": "Webex", "slack.exe": "Slack", "whatsapp.exe": "WhatsApp",
             "whatsapp.root.exe": "WhatsApp", "skype.exe": "Skype", "discord.exe": "Discord"}
BROWSERS = {"chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "brave.exe": "Brave",
            "opera.exe": "Opera", "vivaldi.exe": "Vivaldi", "arc.exe": "Arc"}

k32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
if k32:
    for _f in ("CreateMutexW", "OpenMutexW", "CreateEventW", "OpenEventW", "OpenProcess"):
        getattr(k32, _f).restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.SetEvent.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
    k32.WaitForMultipleObjects.restype = wintypes.DWORD
    k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k32.GetModuleHandleW.restype = wintypes.HMODULE


# ---------- used by the app: switch the helper on and off ----------

def _startup_dir() -> Path:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 7, None, 0, buf)          # CSIDL_STARTUP (this user only)
    return Path(buf.value)


def shortcut_path() -> Path:
    return _startup_dir() / SHORTCUT_NAME


def _pythonw() -> Path:
    return config.APP_DIR / "python" / "pythonw.exe"


def ensure_shortcut():
    """Start the helper when this user signs in to Windows (no admin rights needed)."""
    lnk = shortcut_path()
    target = _pythonw()
    if not target.exists():
        return
    icon = config.APP_DIR / "callrec" / "icon.ico"
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('" + str(lnk).replace("'", "''") + "');"
          "$s.TargetPath='" + str(target).replace("'", "''") + "';$s.Arguments='-m callrec.watcher';"
          "$s.WorkingDirectory='" + str(config.APP_DIR).replace("'", "''") + "';"
          "$s.IconLocation='" + str(icon).replace("'", "''") + ",0';"
          "$s.Description='FreeCallNotes call pop-ups';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   creationflags=0x08000000, timeout=30, capture_output=True)


def remove_shortcut():
    try:
        shortcut_path().unlink(missing_ok=True)
    except OSError:
        log.exception("remove pop-up shortcut")


def is_running() -> bool:
    h = k32.OpenMutexW(0x00100000, False, MUTEX_NAME)          # SYNCHRONIZE
    if h:
        k32.CloseHandle(h)
        return True
    return False


def start():
    if is_running() or not _pythonw().exists():
        return
    cmd = [str(_pythonw()), "-m", "callrec.watcher"]
    kw = dict(cwd=str(config.APP_DIR), close_fds=True, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:                                   # its own process group, outside any job the app runs in
        subprocess.Popen(cmd, creationflags=0x00000200 | 0x01000000, **kw)
    except OSError:
        subprocess.Popen(cmd, creationflags=0x00000200, **kw)


def stop():
    """Ask a running helper to exit (it is waiting on this event)."""
    h = k32.OpenEventW(0x0002, False, QUIT_EVENT_NAME)          # EVENT_MODIFY_STATE
    if h:
        k32.SetEvent(h)
        k32.CloseHandle(h)


def enable():
    ensure_shortcut()
    start()


def disable():
    remove_shortcut()
    stop()


def sync():
    """At app start: make the helper match the setting (and repair the shortcut if the folder moved)."""
    if sys.platform != "win32":
        return
    try:
        if config.settings().get("call_popups", True):
            enable()
        else:
            disable()
    except Exception:
        log.exception("call pop-ups")


# ---------- the helper ----------

def _process_name(pid: int) -> str:
    h = k32.OpenProcess(0x1000, False, pid)                       # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        k32.CloseHandle(h)


def _app_is_open() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{APP_PORT}/api/version", timeout=0.5):
            return True
    except Exception:
        return False


def open_app():
    exe = config.APP_DIR / "FreeCallNotes.exe"
    target = [str(exe)] if exe.exists() else [str(_pythonw()), "-m", "callrec"]
    subprocess.Popen(target, cwd=str(config.APP_DIR), close_fds=True)


class Helper:
    def __init__(self, quit_event, rescan_event):
        self.quit_event, self.rescan_event = quit_event, rescan_event
        self.registered = []                 # (session manager, callback) pairs, kept alive while registered
        self.last_shown = {}
        self.popup_lock = threading.Lock()

    def register(self):
        """Ask every active microphone to tell us when an app opens it."""
        import comtypes
        from comtypes import COMObject
        from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2, IAudioSessionNotification
        from pycaw.api.mmdeviceapi import IMMDeviceEnumerator, IMMNotificationClient
        from pycaw.constants import CLSID_MMDeviceEnumerator
        self.unregister()
        helper = self

        class OnSession(COMObject):
            _com_interfaces_ = (IAudioSessionNotification,)

            def OnSessionCreated(self, new_session):
                try:
                    pid = new_session.QueryInterface(IAudioSessionControl2).GetProcessId()
                    helper.on_mic_opened(pid)
                except Exception:
                    log.exception("pop-up session")
                return 0

        class OnDevices(COMObject):
            _com_interfaces_ = (IMMNotificationClient,)

            def OnDeviceStateChanged(self, device_id, state):
                k32.SetEvent(helper.rescan_event); return 0

            def OnDeviceAdded(self, device_id):
                k32.SetEvent(helper.rescan_event); return 0

            def OnDeviceRemoved(self, device_id):
                k32.SetEvent(helper.rescan_event); return 0

            def OnDefaultDeviceChanged(self, flow, role, device_id):
                k32.SetEvent(helper.rescan_event); return 0

            def OnPropertyValueChanged(self, device_id, key):
                return 0

        en = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
        devices = en.EnumAudioEndpoints(1, 1)                          # eCapture, DEVICE_STATE_ACTIVE
        for i in range(devices.GetCount()):
            mgr = devices.Item(i).Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
            mgr = mgr.QueryInterface(IAudioSessionManager2)
            cb = OnSession()
            mgr.RegisterSessionNotification(cb)
            mgr.GetSessionEnumerator()                                 # notifications only start after this
            self.registered.append((mgr, cb))
        if not getattr(self, "device_cb", None):
            self.enumerator, self.device_cb = en, OnDevices()
            en.RegisterEndpointNotificationCallback(self.device_cb)
        log.info("call pop-ups: watching %d microphone(s)", len(self.registered))

    def unregister(self):
        for mgr, cb in self.registered:
            try:
                mgr.UnregisterSessionNotification(cb)
            except Exception:
                pass
        self.registered = []

    def on_mic_opened(self, pid):
        name = _process_name(pid)
        label = CALL_APPS.get(name) or BROWSERS.get(name)
        if not label:
            return
        now = time.monotonic()
        if now - self.last_shown.get(label, -1e9) < REPEAT_AFTER_S:
            return
        if not config.settings().get("call_popups", True) or _app_is_open():
            return
        if not self.popup_lock.acquire(blocking=False):            # one pop-up at a time
            return
        self.last_shown[label] = now
        log.info("call pop-up for %s", label)

        def run():
            try:
                choice = Popup(label, browser=name in BROWSERS).show()
                if choice == "open":
                    open_app()
                elif choice == "never":
                    config.update_settings(call_popups=False)
                    remove_shortcut()
                    k32.SetEvent(self.quit_event)
            except Exception:
                log.exception("call pop-up")
            finally:
                self.popup_lock.release()
        threading.Thread(target=run, daemon=True).start()


def _dpi_aware():
    """Draw the pop-up at the screen's real resolution (sharp at 150%, 200%, 300% scaling)."""
    try:
        u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))      # per-monitor aware (v2)
    except Exception:
        pass


def main():
    _dpi_aware()
    logging.basicConfig(filename=str(config.LOG_FILE), level=logging.INFO,
                        format="%(asctime)s %(levelname)s [pop-ups] %(message)s")
    if "--demo" in sys.argv:
        label = sys.argv[sys.argv.index("--demo") + 1] if len(sys.argv) > sys.argv.index("--demo") + 1 else "Zoom"
        print(Popup(label, browser=label.lower() in ("chrome", "edge", "firefox")).show())
        return
    mutex = k32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:                                 # ERROR_ALREADY_EXISTS: one helper only
        return
    if not config.settings().get("call_popups", True):
        return
    quit_event = k32.CreateEventW(None, True, False, QUIT_EVENT_NAME)
    rescan_event = k32.CreateEventW(None, False, False, None)
    sys.coinit_flags = 0                                               # COM multithreaded: callbacks on COM's threads
    import comtypes  # noqa: F401  (initialises COM for this thread)
    helper = Helper(quit_event, rescan_event)
    try:
        helper.register()
    except Exception:
        log.exception("call pop-ups: couldn't watch the microphone")
        return
    handles = (wintypes.HANDLE * 2)(quit_event, rescan_event)
    while True:                                                        # sleeps until Windows signals something
        r = k32.WaitForMultipleObjects(2, handles, False, 0xFFFFFFFF)
        if r == 1:
            time.sleep(1)                                              # let a device change settle
            try:
                helper.register()
            except Exception:
                log.exception("call pop-ups: rescan")
            continue
        break
    helper.unregister()
    log.info("call pop-ups: stopped")
    k32.CloseHandle(mutex)


# ---------- the pop-up (a plain Windows window: always on top, doesn't take focus) ----------

u32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
g32 = ctypes.WinDLL("gdi32") if sys.platform == "win32" else None
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("hwndTrack", wintypes.HWND),
                ("dwHoverTime", wintypes.DWORD)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


if u32:
    u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u32.DefWindowProcW.restype = LRESULT
    u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                    wintypes.HINSTANCE, wintypes.LPVOID]
    u32.CreateWindowExW.restype = wintypes.HWND
    u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    u32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
    u32.LoadCursorW.restype = wintypes.HANDLE
    u32.SetCursor.argtypes = [wintypes.HANDLE]
    u32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    u32.BeginPaint.restype = wintypes.HDC
    u32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    u32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    u32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    u32.InvalidateRect.argtypes = [wintypes.HWND, wintypes.LPVOID, wintypes.BOOL]
    u32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
    u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    u32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u32.DestroyWindow.argtypes = [wintypes.HWND]
    u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
    u32.TrackMouseEvent.argtypes = [wintypes.LPVOID]
    g32.CreateSolidBrush.restype = wintypes.HBRUSH
    g32.CreatePen.restype = wintypes.HANDLE
    g32.CreateFontW.restype = wintypes.HANDLE
    g32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
    g32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    g32.SelectObject.restype = wintypes.HANDLE
    g32.DeleteObject.argtypes = [wintypes.HANDLE]
    g32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
    g32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    g32.RoundRect.argtypes = [wintypes.HDC] + [ctypes.c_int] * 6
    g32.GetStockObject.restype = wintypes.HANDLE
    u32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    u32.PostQuitMessage.argtypes = [ctypes.c_int]


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


BG, LINE, TEXT, MUTED, PRIMARY, PRIMARY_HOVER, PRIMARY_INK = (
    _rgb("#1c2430"), _rgb("#3a4656"), _rgb("#eef1f5"), _rgb("#a7b2c1"), _rgb("#9db8ff"), _rgb("#b4c8ff"), _rgb("#10151c"))


class Popup:
    """A small card in the bottom-right corner. show() blocks until it closes and returns
    "open", "later", "never" or "timeout"."""
    W, H = 384, 128

    def __init__(self, label, browser=False):
        if browser:
            self.title = f"{label} is using your microphone"
            self.body = "In a call? Open FreeCallNotes to record and transcribe it."
        else:
            self.title = f"Call starting in {label}"
            self.body = "Open FreeCallNotes to record and transcribe it."
        self.choice = "timeout"
        self.hover = None

    def _layout(self):
        s = self.scale
        px = lambda v: int(round(v * s))
        w, h = px(self.W), px(self.H)
        self.btn = {
            "open": (w - px(16) - px(150), h - px(16) - px(34), w - px(16), h - px(16)),
            "later": (w - px(16) - px(150) - px(8) - px(86), h - px(16) - px(34), w - px(16) - px(150) - px(8), h - px(16)),
            "never": (px(14), h - px(16) - px(34), px(14) + px(116), h - px(16)),
            "close": (w - px(34), px(8), w - px(8), px(34)),
        }

    def _hit(self, x, y):
        for k, (l, t, r, b) in self.btn.items():
            if l <= x < r and t <= y < b:
                return k
        return None

    def _paint(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = u32.BeginPaint(hwnd, ctypes.byref(ps))
        s = self.scale
        px = lambda v: int(round(v * s))
        w, h = px(self.W), px(self.H)
        objs = []

        def brush(c):
            b = g32.CreateSolidBrush(c); objs.append(b); return b

        def pen(c, width=1):
            p = g32.CreatePen(0, max(1, px(width)), c); objs.append(p); return p

        def font(size, weight=400):
            f = g32.CreateFontW(-px(size), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI"); objs.append(f); return f

        def text(t, rect, color, f, flags):
            g32.SelectObject(hdc, f)
            g32.SetTextColor(hdc, color)
            r = wintypes.RECT(*rect)
            u32.DrawTextW(hdc, t, -1, ctypes.byref(r), flags)

        u32.FillRect(hdc, ctypes.byref(wintypes.RECT(0, 0, w, h)), brush(BG))
        g32.SetBkMode(hdc, 1)                                           # transparent text background
        text(self.title, (px(18), px(14), w - px(40), px(38)), TEXT, font(15, 600), 0x20 | 0x8000)   # single line, ellipsis
        text(self.body, (px(18), px(40), w - px(18), px(64)), MUTED, font(13), 0x20 | 0x8000)
        l, t, r, b = self.btn["open"]
        g32.SelectObject(hdc, pen(PRIMARY_HOVER if self.hover == "open" else PRIMARY))
        g32.SelectObject(hdc, brush(PRIMARY_HOVER if self.hover == "open" else PRIMARY))
        g32.RoundRect(hdc, l, t, r, b, px(10), px(10))
        text("Open FreeCallNotes", (l, t, r, b), PRIMARY_INK, font(13, 600), 0x1 | 0x4 | 0x20)
        l, t, r, b = self.btn["later"]
        g32.SelectObject(hdc, pen(MUTED if self.hover == "later" else LINE))
        g32.SelectObject(hdc, brush(BG))
        g32.RoundRect(hdc, l, t, r, b, px(10), px(10))
        text("Not now", (l, t, r, b), TEXT, font(13), 0x1 | 0x4 | 0x20)
        f = g32.CreateFontW(-px(12), 0, 0, 0, 400, 0, 1 if self.hover == "never" else 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        objs.append(f)
        text("Don't show again", self.btn["never"], TEXT if self.hover == "never" else MUTED, f, 0x4 | 0x20)
        text("✕", self.btn["close"], TEXT if self.hover == "close" else MUTED, font(12), 0x1 | 0x4 | 0x20)
        g32.SelectObject(hdc, pen(LINE))
        g32.SelectObject(hdc, g32.GetStockObject(5))                    # NULL_BRUSH: border only
        g32.RoundRect(hdc, 0, 0, w, h, px(16), px(16))
        u32.EndPaint(hwnd, ctypes.byref(ps))
        for o in objs:
            g32.DeleteObject(o)

    def _proc(self, hwnd, msg, wp, lp):
        if msg == 0x000F:                                               # WM_PAINT
            self._paint(hwnd); return 0
        if msg == 0x0200:                                               # WM_MOUSEMOVE
            x, y = ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short((lp >> 16) & 0xFFFF).value
            hv = self._hit(x, y)
            if hv != self.hover:
                self.hover = hv; u32.InvalidateRect(hwnd, None, False)
            tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), 0x2, hwnd, 0)     # TME_LEAVE
            u32.TrackMouseEvent(ctypes.byref(tme))
            return 0
        if msg == 0x02A3:                                               # WM_MOUSELEAVE
            if self.hover:
                self.hover = None; u32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == 0x0020:                                               # WM_SETCURSOR
            u32.SetCursor(u32.LoadCursorW(None, ctypes.c_void_p(32649 if self.hover else 32512)))   # hand / arrow
            return 1
        if msg == 0x0021:                                               # WM_MOUSEACTIVATE: don't take focus
            return 3                                                    # MA_NOACTIVATE
        if msg == 0x0202:                                               # WM_LBUTTONUP
            x, y = ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short((lp >> 16) & 0xFFFF).value
            hit = self._hit(x, y)
            if hit:
                self.choice = {"close": "later"}.get(hit, hit)
                u32.DestroyWindow(hwnd)
            return 0
        if msg == 0x0113:                                               # WM_TIMER: time's up
            u32.DestroyWindow(hwnd); return 0
        if msg == 0x0002:                                               # WM_DESTROY
            u32.PostQuitMessage(0); return 0
        return u32.DefWindowProcW(hwnd, msg, wp, lp)

    def show(self):
        try:
            u32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            u32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))      # per-monitor DPI aware (v2)
        except Exception:
            pass
        try:
            dpi = u32.GetDpiForSystem()
        except Exception:
            dpi = 96
        self.scale = dpi / 96
        self._layout()
        self._wndproc = WNDPROC(self._proc)                             # keep a reference while the window lives
        hinst = k32.GetModuleHandleW(None)
        cls = f"FreeCallNotesPopup{id(self)}"
        wc = WNDCLASSW(0, self._wndproc, 0, 0, hinst, None, None, None, None, cls)
        u32.RegisterClassW(ctypes.byref(wc))
        work = wintypes.RECT()
        u32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)    # SPI_GETWORKAREA (excludes the taskbar)
        w, h = int(self.W * self.scale), int(self.H * self.scale)
        margin = int(16 * self.scale)
        ex = 0x00000008 | 0x00000080 | 0x08000000                       # TOPMOST | TOOLWINDOW | NOACTIVATE
        hwnd = u32.CreateWindowExW(ex, cls, "FreeCallNotes", 0x80000000, work.right - w - margin,
                                   work.bottom - h - margin, w, h, None, None, hinst, None)
        try:                                                            # rounded corners on Windows 11
            pref = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(pref), 4)
        except Exception:
            pass
        u32.ShowWindow(hwnd, 4)                                         # SW_SHOWNOACTIVATE
        u32.SetTimer(hwnd, 1, SHOW_FOR_S * 1000, None)
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
        u32.UnregisterClassW(cls, hinst)
        return self.choice


if __name__ == "__main__":
    main()
