# Changelog

## 1.4.2
- New: **Check for updates** in Options. When a newer release is out, one click downloads it, checks it against its published SHA-256 checksum, installs it and reopens the app. Your calls, settings and speech models are kept.
- FreeCallNotes looks for a new version at most once every 30 days and shows "Update available" if there is one. Updating is always optional: nothing is installed unless you click Update. You can turn the 30-day check off in Options.

## 1.4.1
- Opening the app again now starts on a clean screen instead of showing the last call. Past calls are still in Saved calls.
- The app notices a closed window within a few seconds, so reopening it straight away no longer brings back the previous session.

## 1.4 (first public release)
- Records your microphone ("User") and the computer's system sound ("System") as two separate tracks, without blocking Zoom, Teams or any other app from using the microphone.
- Live transcription during the call with NVIDIA Nemotron (default) or Moonshine; optional second transcription after the call with the other model.
- Exports a "Transcript for AI" text file with instructions, so any AI assistant can clean up the transcript and write notes.
- Portable: unzip and run, no installation and no admin rights. Speech models download on first run.
- First-run notice about recording consent, accuracy and AI assistants; About section with licenses.
- Released under GPL-3.0-or-later.
