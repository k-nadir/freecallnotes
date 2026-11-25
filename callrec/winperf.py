# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Windows performance helpers.

Windows 11 throttles processes that have no visible window of their own ("EcoQoS" / efficiency mode):
it moves them to the slower efficiency cores at reduced clock speed. Our engine runs without a window,
so it gets throttled unless we opt out. Also reports power state for the telemetry log.
"""
import ctypes
import sys

PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4
ProcessPowerThrottling = 4
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000


class _PPTS(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def opt_out_of_throttling():
    """Ask Windows to run this process at full speed. Returns a short description for the log."""
    if sys.platform != "win32":
        return "n/a"
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Declare the real argument types: without this, ctypes squeezes the 64-bit process handle into
    # 32 bits and Windows rejects the call (that is what happened in v1.2).
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetCurrentProcess.argtypes = []
    k32.SetProcessInformation.restype = wintypes.BOOL
    k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.SetPriorityClass.restype = wintypes.BOOL
    k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    h = k32.GetCurrentProcess()
    s = _PPTS(PROCESS_POWER_THROTTLING_CURRENT_VERSION,
              PROCESS_POWER_THROTTLING_EXECUTION_SPEED | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION, 0)
    ok1 = bool(k32.SetProcessInformation(h, ProcessPowerThrottling, ctypes.byref(s), ctypes.sizeof(s)))
    e1 = ctypes.get_last_error()
    ok2 = bool(k32.SetPriorityClass(h, ABOVE_NORMAL_PRIORITY_CLASS))
    e2 = ctypes.get_last_error()
    if not (ok1 and ok2):
        return f"throttling_off={ok1} (err {e1}) above_normal_priority={ok2} (err {e2})"
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)    # finer timer so short sleeps aren't stretched to 15 ms
    except Exception:
        pass
    return f"throttling_off={ok1} above_normal_priority={ok2}"


class _SPS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


def power_status():
    if sys.platform != "win32":
        return {}
    s = _SPS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return {}
    return {"plugged_in": {0: False, 1: True}.get(s.ACLineStatus, None),
            "battery_pct": None if s.BatteryLifePercent == 255 else s.BatteryLifePercent,
            "battery_saver": bool(s.SystemStatusFlag & 1)}
