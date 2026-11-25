# Changelog

## 1.5
- New: **Whisper large-v3 turbo**, an optional model for calls in other languages (about 100). It runs after the call, detects the language automatically or uses the one you pick, and skips silence so it doesn't invent text. For a call that isn't in English its transcript is the one shown, and the transcript for AI tells the assistant which language the call is in.
- New: models are installed and removed in Options. The table shows which models are installed, with Install and Remove buttons, and a short description of each.
- New: **call pop-ups**. When Zoom, Teams, Webex, Slack, WhatsApp or a browser starts using the microphone, a small pop-up offers to open FreeCallNotes. It never records on its own. A tiny helper waits for Windows to signal this rather than checking repeatedly. Turn it off in Options or with "Don't show again" on the pop-up.
- The transcript for AI can now include up to three versions of each side.

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
