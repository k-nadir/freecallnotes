# FreeCallNotes - records and transcribes calls on your own computer.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full terms. This program comes with ABSOLUTELY NO WARRANTY.
"""Updates the app from the latest GitHub release, only when the user asks.

1. check():    asks GitHub which release is the latest (one small request, nothing about the user is sent).
2. stage():    downloads that release's zip, checks its SHA-256 against the one GitHub publishes,
               and unpacks it into <app>/.update/staging.
3. apply():    starts a small PowerShell helper and returns; the app then quits. The helper waits until
               the app has closed, copies the new program files over the old ones and reopens the app.
               Recordings, models, settings and the window profile are never touched.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import config

log = logging.getLogger("callrec")
REPO = "k-nadir/freecallnotes"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_RE = re.compile(r"^FreeCallNotes-[0-9][0-9.]*-windows-x64\.zip$")
UPDATE_DIR = config.APP_DIR / ".update"
# Program folders replaced by an update. Everything else in the app folder (Call Notes, models,
# settings.json, window-profile, the log) is left exactly as it is.
PROGRAM_DIRS = ("python", "callrec", "legal")


def current_version() -> str:
    # CALLREC_PRETEND_VERSION is only for testing the update flow.
    return os.environ.get("CALLREC_PRETEND_VERSION") or config.VERSION


def _vtuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"FreeCallNotes/{config.VERSION}",
        "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def check() -> dict:
    with _get(LATEST_API) as r:
        rel = json.loads(r.read())
    latest = str(rel.get("tag_name", "")).lstrip("vV")
    asset = next((a for a in rel.get("assets", []) if ASSET_RE.match(a.get("name", ""))), None)
    if not latest or not asset:
        raise RuntimeError("the latest release has no Windows download")
    cur = current_version()
    return {
        "ok": True,
        "current": cur,
        "latest": latest,
        "newer": _vtuple(latest) > _vtuple(cur),
        "size": asset.get("size", 0),
        "url": asset["browser_download_url"],
        "digest": asset.get("digest") or "",
        "page": rel.get("html_url", ""),
    }


def stage(info: dict, progress) -> Path:
    """Download, verify and unpack the release. Returns the folder holding the new app files."""
    if not str(info.get("digest", "")).startswith("sha256:"):
        raise RuntimeError("the release has no published checksum, so it can't be verified")
    want = info["digest"].split(":", 1)[1].lower()
    if UPDATE_DIR.exists():
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    zpath = UPDATE_DIR / "download.zip"
    h, done, total = hashlib.sha256(), 0, max(int(info.get("size") or 0), 1)
    with _get(info["url"], timeout=60) as r, open(zpath, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress(min(done / total, 1.0))
    if h.hexdigest() != want:
        raise RuntimeError("the download didn't match its published checksum")
    staging = UPDATE_DIR / "staging"
    with zipfile.ZipFile(zpath) as z:
        root = staging.resolve()
        for name in z.namelist():                      # refuse any entry that would land outside staging
            if not (staging / name).resolve().is_relative_to(root):
                raise RuntimeError("the download contains an unexpected file path")
        z.extractall(staging)
    new = staging / "FreeCallNotes"
    for need in ("FreeCallNotes.exe", "python/pythonw.exe", "callrec/__main__.py"):
        if not (new / need).exists():
            raise RuntimeError("the download is missing program files")
    zpath.unlink(missing_ok=True)
    return new


APPLY_PS1 = r"""
param([int]$AppPid, [string]$App, [string]$Staging)
$log = Join-Path $App '.update\apply.log'
function Write-Log($m) { Add-Content -Path $log -Value ((Get-Date -Format s) + ' ' + $m) }
Write-Log "waiting for the app (pid $AppPid) to close"
try { Wait-Process -Id $AppPid -Timeout 120 -ErrorAction Stop } catch {}
$py = Join-Path $App 'python'
for ($i = 0; $i -lt 60; $i++) {
  $left = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($py, [StringComparison]::OrdinalIgnoreCase) }
  if (-not $left) { break }
  Start-Sleep -Milliseconds 500
}
$ok = $true
foreach ($d in @(__DIRS__)) {
  $src = Join-Path $Staging $d
  if (Test-Path $src) {
    robocopy $src (Join-Path $App $d) /MIR /R:10 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { $ok = $false; Write-Log "copying $d failed (robocopy $LASTEXITCODE)" }
  }
}
Get-ChildItem -Path $Staging -File | ForEach-Object {
  try { Copy-Item -Path $_.FullName -Destination (Join-Path $App $_.Name) -Force -ErrorAction Stop }
  catch { $ok = $false; Write-Log ("copying " + $_.Name + " failed") }
}
Write-Log "update applied: $ok"
if ($ok) { Remove-Item -Path (Join-Path $App '.update\staging') -Recurse -Force -ErrorAction SilentlyContinue }
Start-Process -FilePath (Join-Path $App 'FreeCallNotes.exe') -WorkingDirectory $App
"""


def apply(new_dir: Path):
    """Start the helper that swaps the files once this process has exited."""
    if sys.platform != "win32":
        raise RuntimeError("updating is only supported on Windows")
    script = UPDATE_DIR / "apply.ps1"
    script.write_text(APPLY_PS1.replace("__DIRS__", ",".join(f"'{d}'" for d in PROGRAM_DIRS)), encoding="utf-8")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
           "-File", str(script), "-AppPid", str(os.getpid()), "-App", str(config.APP_DIR), "-Staging", str(new_dir)]
    # The helper must outlive the app. PowerShell needs a console, so give it a hidden one
    # (CREATE_NO_WINDOW, not DETACHED_PROCESS, which makes it exit at once), its own process group, and
    # null standard handles (the app has none). Also leave any job object the app was started in, where
    # allowed: some launchers kill a job's processes when the parent exits.
    base = 0x08000000 | 0x00000200
    kw = dict(close_fds=True, cwd=str(UPDATE_DIR), stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        subprocess.Popen(cmd, creationflags=base | 0x01000000, **kw)
    except OSError:                       # the job doesn't allow breaking away
        subprocess.Popen(cmd, creationflags=base, **kw)
    log.info("update helper started for %s", new_dir)
