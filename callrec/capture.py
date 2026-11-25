# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Audio capture: your microphone and the computer's sound, as two separate 16 kHz mono tracks.

On Windows both come through WASAPI in *shared* mode, the same way Zoom/Teams use them, so
recording never blocks another app from using the microphone. The computer's sound is taken
with WASAPI "loopback": a copy of whatever is playing on the default speakers/headphones.

FileCapture plays WAV files in real time instead, for testing without a microphone.
"""
import threading
import time
import wave

import numpy as np

from .config import SR


class CaptureError(Exception):
    pass


class WinCapture:
    """Microphone + system-sound capture on Windows (PyAudioWPatch)."""

    def __init__(self, on_audio):
        import pyaudiowpatch as pyaudio  # Windows only
        self.pa = pyaudio
        self.p = pyaudio.PyAudio()
        self.on_audio = on_audio          # on_audio(key, float32 mono 16 kHz samples)
        self.streams = []
        self.devices = {}

    def describe(self):
        """Names of the devices that will be used, for display."""
        out = {}
        try:
            wasapi = self.p.get_host_api_info_by_type(self.pa.paWASAPI)
            if wasapi.get("defaultInputDevice", -1) >= 0:
                out["me"] = self.p.get_device_info_by_index(wasapi["defaultInputDevice"])["name"]
        except Exception:
            pass
        try:
            out["them"] = self.p.get_default_wasapi_loopback()["name"].replace(" [Loopback]", "")
        except Exception:
            pass
        return out

    def _open(self, key, dev):
        import soxr
        ch = max(1, int(dev["maxInputChannels"]))
        rate = int(dev["defaultSampleRate"])
        rs = soxr.ResampleStream(rate, SR, 1, dtype="float32")
        pa = self.pa

        def cb(in_data, frame_count, time_info, status):
            try:
                x = np.frombuffer(in_data, dtype=np.float32)
                if ch > 1:
                    x = x.reshape(-1, ch).mean(axis=1)
                y = rs.resample_chunk(x)
                if len(y):
                    self.on_audio(key, y.astype(np.float32, copy=False))
            except Exception:
                pass
            return (None, pa.paContinue)

        st = self.p.open(format=pa.paFloat32, channels=ch, rate=rate, input=True,
                         input_device_index=dev["index"], frames_per_buffer=int(rate * 0.05),
                         stream_callback=cb)
        st.start_stream()
        self.streams.append(st)
        self.devices[key] = dev["name"]

    def start(self, want_me=True, want_them=True):
        errors = []
        if want_me:
            try:
                wasapi = self.p.get_host_api_info_by_type(self.pa.paWASAPI)
                idx = wasapi.get("defaultInputDevice", -1)
                if idx < 0:
                    raise CaptureError("no microphone found")
                self._open("me", self.p.get_device_info_by_index(idx))
            except Exception as e:
                errors.append(f"Microphone: {e}")
        if want_them:
            try:
                self._open("them", self.p.get_default_wasapi_loopback())
            except Exception as e:
                errors.append(f"Computer sound: {e}")
        if not self.streams:
            raise CaptureError("; ".join(errors) or "nothing to record")
        return errors

    def stop(self):
        for st in self.streams:
            try:
                st.stop_stream()
                st.close()
            except Exception:
                pass
        self.streams = []
        try:
            self.p.terminate()
        except Exception:
            pass


class FileCapture:
    """Plays WAV files (16 kHz mono) as if they were live inputs. For testing."""

    def __init__(self, on_audio, files, speed=1.0):
        self.on_audio = on_audio
        self.files = files            # {"me": path, "them": path}
        self.speed = speed
        self._stop = threading.Event()
        self.threads = []
        self.devices = {k: f"file:{v}" for k, v in files.items()}

    def describe(self):
        return dict(self.devices)

    def _play(self, key, path):
        w = wave.open(str(path))
        assert w.getframerate() == SR and w.getnchannels() == 1
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        step = SR // 10
        t0 = time.monotonic()
        for i in range(0, len(a), step):
            if self._stop.is_set():
                return
            self.on_audio(key, a[i:i + step])
            wait = t0 + (i + step) / SR / self.speed - time.monotonic()
            if wait > 0:
                time.sleep(wait)

    def start(self, want_me=True, want_them=True):
        for key, path in self.files.items():
            if (key == "me" and want_me) or (key == "them" and want_them):
                t = threading.Thread(target=self._play, args=(key, path), daemon=True)
                t.start()
                self.threads.append(t)
        return []

    def stop(self):
        self._stop.set()
        for t in self.threads:
            t.join(timeout=2)
