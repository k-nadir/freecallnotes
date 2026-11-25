# Privacy

FreeCallNotes is built so that your calls never leave your computer.

## What stays on your computer

Everything FreeCallNotes records or creates is saved only on your computer, inside the FreeCallNotes folder unless you choose another folder in Options:

| What | Where | Contains |
|---|---|---|
| Recordings | `Call Notes/<date and time>/me.wav`, `them.wav` | The audio of your microphone ("User") and system sound ("System") |
| Transcripts | `Call Notes/<date and time>/*.txt`, `*.json` | What was said, with timestamps |
| Call details | `Call Notes/<date and time>/call.json`, `telemetry.json` | Start time, length, the names of your audio devices, and processing-speed measurements. These stay on your computer; nothing is reported anywhere. |
| Settings | `settings.json` | Your options and the save folder |
| Log | `freecallnotes.log` | Technical events for troubleshooting (device names, timings, errors). No audio or transcript text. |
| Speech models | `models/` | Downloaded model files |
| Window data | `window-profile/` | The Microsoft Edge profile used only for the FreeCallNotes window |
| Startup shortcut | your Windows Startup folder | `FreeCallNotes call pop-ups.lnk`, only while call pop-ups are on |
| Updates | `.update/` | A downloaded update while it is being installed, and a short install log |

To delete everything, turn off Call pop-ups in Options, close FreeCallNotes and delete its folder (and your chosen save folder, if you picked one elsewhere). Also delete the FreeCallNotes desktop shortcut if you like.

## Internet use

FreeCallNotes connects to the internet only to **download the speech models**, and only when they are missing (on first run, or when you turn on a model you haven't used before), and to **check for updates**: at most once every 30 days, and whenever you click "Check for updates" in Options. You can turn the 30-day check off in Options. A check only asks GitHub which version is the newest; FreeCallNotes downloads and installs an update only when you click Update.

- NVIDIA Nemotron: from Hugging Face (huggingface.co and its download servers).
- Moonshine (only if you install it in Options): from the Moonshine project's server (download.moonshine.ai).
- Whisper (only if you install it in Options): from Hugging Face, plus the small Silero voice detector from GitHub (github.com).

- Updates: from GitHub (api.github.com to see which release is the latest, then github.com and its download servers for the zip file). The download is checked against the SHA-256 checksum GitHub publishes for it before anything is installed.

Those requests contain nothing about you or your calls beyond what any download does (your IP address and standard request headers, handled under those services' own privacy policies). On networks that block these sites, the model files can be copied into the `models` folder by hand.

There is **no account, no analytics, no telemetry, no crash reporting and no automatic upload** of any kind. The interface is a local web page served only to your own computer (127.0.0.1); it is not reachable from other computers.

## Call pop-ups

If "Call pop-ups" is on (it is by default), a small FreeCallNotes helper starts when you sign in to Windows, from a shortcut in your Startup folder (`FreeCallNotes call pop-ups.lnk`). It asks Windows to tell it when an app opens a microphone and otherwise sleeps. When it is told, it looks only at **which program** opened the microphone (for example `Zoom.exe`); it never listens to, records or stores any audio. For Zoom, Teams, Webex, Slack, WhatsApp, Skype, Discord or a web browser it shows a pop-up offering to open FreeCallNotes, and writes one line to the log (for example "call pop-up for Zoom"). It sends nothing anywhere.

Turn it off in Options, or click "Don't show again" on a pop-up: the helper stops and its Startup shortcut is removed.

## When content can leave your computer

Only when **you** move it: for example, when you upload the "Transcript for AI" file to an AI assistant, email it, or copy your recordings elsewhere. Those services handle the content under their own terms. See [DISCLAIMER.md](DISCLAIMER.md).

## Other people's voices

Recordings contain other people's voices and words. Treat them with the same care you would want for your own, and follow the consent and data-protection guidance in [DISCLAIMER.md](DISCLAIMER.md).
