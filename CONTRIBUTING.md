# Contributing to FreeCallNotes

Thanks for helping. FreeCallNotes aims to stay **simple enough for anyone to use**: unzip, double-click, record. Please keep that in mind with every change.

## Before you start

- For anything bigger than a small fix, open an issue first so we can agree on the approach.
- Read the [Contributor License Agreement](CLA.md). You'll be asked to agree to it on your first pull request. It lets the project change license terms in future (for example, to offer a paid edition) while every version already released as open source stays open source.

## Ground rules

1. **Nothing leaves the user's computer.** No analytics, telemetry, crash reporting, accounts or cloud calls. The only network access allowed is downloading model files. See [PRIVACY.md](PRIVACY.md).
2. **No installation, no admin rights.** The app must keep working as an unzipped folder on a locked-down work laptop.
3. **Never block the meeting app.** Audio capture must stay in shared mode so Zoom, Teams, etc. keep working.
4. **Recording is sacred.** Transcription may lag or fail, but the audio must always be saved. Keep capture/saving (the recorder process) separate from transcription (job processes).
5. **Plain-English interface.** Short, clear words, no jargon. The status rail (Ready, Recording, Saving, Transcribing, Saved) must always show what is happening.
6. **Licenses.** Only add dependencies whose licenses are compatible with GPL-3.0, and add them to [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `build/requirements-windows.txt`. Speech models must allow commercial use.
7. **No personal data in the repo.** Never commit recordings, transcripts, model files, logs, `settings.json` or anything with real names, numbers or paths from your machine.

## Development

- Code layout and data flow: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- Run from source on Windows: install Python 3.12 and `pip install -r build/requirements-windows.txt`, then `python -m callrec` from the repository folder. Models download into `models/` on first run.
- Test without a microphone: `python -m callrec --test-files me.wav them.wav` plays two 16 kHz mono WAV files as if they were the live inputs.
- Build the portable zip: `python build/build_windows.py`.

## Pull requests

- One topic per pull request, with a short description of what changed and how you tested it (ideally on Windows 10 and 11).
- Add a line to [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
- New source files start with the license header used in the existing files (`SPDX-License-Identifier: GPL-3.0-or-later`).
