# Architecture

FreeCallNotes is a small Python app that ships with its own embedded Python, so users don't install anything. The interface is a local web page shown in a Microsoft Edge "app mode" window.

## Processes

```
FreeCallNotes.exe ─► pythonw -m callrec  (main process)
                       ├─ HTTP server on 127.0.0.1:47123 (UI + JSON API + server-sent events)
                       ├─ Edge window (--app, its own profile in window-profile/)
                       ├─ recorder: capture threads, saver thread, display thread
                       └─ transcription jobs (one subprocess per model):
                            python -m callrec.post nemotron during <call dir> live
                            python -m callrec.post moonshine after <call dir>
```

Why separate processes:

- **Recording can never be slowed down by transcription.** The recorder only captures and writes WAV files. Speech models run in their own processes and read the WAV files while they grow.
- **Both models bundle their own `onnxruntime.dll`**, which conflict if loaded into one process.
- If a transcription job crashes, the recording is unaffected and the job can be rerun later ("unfinished calls" are finished on the next start).

## Recording (`capture.py`, `engine.py`)

- Microphone: WASAPI shared mode (via PyAudioWPatch), so other apps keep using the microphone.
- System sound: WASAPI loopback of the default output device.
- Both are converted to float32, resampled to 16 kHz mono (soxr) and handed to the `Session`.
- `Session` runs two threads: **saver** (writes `me.wav` and `them.wav`, flushes every 0.5 s, pads silence from arrival timestamps so both tracks stay aligned, including when loopback delivers nothing during silence), **display** (levels and elapsed time to the UI every 0.15 s).
- On Stop, it writes `live_lines.json`, `telemetry.json` and finally `call.json` (written atomically last; its presence means "recording finished").

Labels: the microphone track is **User** (`me`), the system-sound track is **System** (`them`).

## Transcription (`post.py`, `jobs.py`)

- `TrackReader` follows a growing WAV file (44-byte header) and finishes once `call.json` exists.
- **Nemotron** (default, live): NVIDIA Nemotron Speech Streaming EN 0.6B, int8, through sherpa-onnx's online transducer. Audio is fed in 0.5 s steps; stretches of more than 1.5 s of digital silence are skipped. `LineSplitter` turns the running text into lines at sentence ends (with fallbacks for long run-ons). Output: `nemotron_lines.json`.
- **Moonshine** (optional, usually "after the call"): Moonshine v2 Medium Streaming. Processes 30 s windows during a call or 90 s windows afterwards, cutting at quiet points. Output: `second_pass_me.json`, `second_pass_them.json`.
- Only one model may run during the call (it's the one shown live). The other can run after the call as a second opinion.
- The main process and every job opt out of Windows power throttling (EcoQoS, `winperf.py`) so they run at full speed when the window is in the background.
- `jobs.py` starts and monitors the jobs, reading their JSON-lines output (progress, timing, live lines, partial text).

## Export (`export.py`)

Builds `Transcript for AI - <dd Mon yyyy HH.MM>.txt`: a header (date, duration, devices), instructions for an AI assistant, and the transcript sections (USER and SYSTEM; with Moonshine on, Version A and Version B for each side). Lines from the microphone that mostly repeat what the system sound said at the same time are marked `[possible echo]` (speaker sound leaking into the mic).

A plain `Transcript.txt` is also written for people who just want to read it.

## Interface (`server.py`, `ui.html`)

- States: starting, setup (model download), loading, idle, recording, stopping, processing, exporting, catching_up, done, error. The status rail shows Ready, Recording, Saving, Transcribing, Saved.
- API: `GET /api/state`, `/api/events` (SSE), `/api/settings`, `/api/version`; `POST /api/start`, `/api/stop`, `/api/settings`, `/api/accept_notice`, `/api/quit`, `/api/choose_folder`, `/api/reset_folder`, `/api/finish_pending`, `/api/finish_in_background`, `/api/open`.
- Closing the window while busy asks the user to wait or to "finish in background and close".
- If a newer copy of the app is started while an older idle copy is running, the older one is asked to quit (`/api/version`).
- First run shows a notice (recording consent, accuracy, AI assistants, privacy, no warranty). Accepting it stores `notice_accepted` in `settings.json`; bump `NOTICE_VERSION` in `config.py` to show it again after changing the text.

## Files and folders (portable)

```
FreeCallNotes/
  FreeCallNotes.exe      launcher (launcher/launcher.c)
  python/                embedded Python 3.12 + packages
  callrec/               the app
  models/                downloaded speech models
  Call Notes/<date>/     one folder per call (default save location; configurable)
  legal/                 license, notices, disclaimer, privacy
  settings.json, freecallnotes.log, window-profile/
```

`config.SAVE_IN_APP_FOLDER = True` keeps calls inside the app folder by default (portable). Set it to `False` to default to `Documents\Call Notes`. The environment variable `CALLREC_NOTES_DIR` overrides the save folder (used for testing).

## Known gaps / ideas

- Echo cancellation (removing speaker sound from the microphone track) is not implemented; echo is only flagged in the export.
- Changing audio devices mid-call is not handled.
- Windows only. macOS would need a different system-audio capture method.
- No code signing yet, so Windows SmartScreen or company policies may warn about the unsigned `FreeCallNotes.exe`.
