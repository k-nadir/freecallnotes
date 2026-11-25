# FreeCallNotes - Windows portable build.
# Copyright (C) 2026 Nadir Khawaja
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the portable Windows folder and zip: dist/FreeCallNotes/ and dist/FreeCallNotes-<version>-windows-x64.zip

Runs on Windows, macOS or Linux (it cross-downloads Windows wheels). Needs Python 3.10+ with pip, internet access,
and, to compile the launcher, the MinGW-w64 cross compiler (x86_64-w64-mingw32-gcc / windres; on Windows install
MSYS2 or use --launcher to pass a prebuilt FreeCallNotes.exe).

    python build/build_windows.py
"""
import argparse, os, re, shutil, subprocess, sys, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_VERSION = "3.12.10"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"


def version():
    return re.search(r'VERSION = "([^"]+)"', (ROOT / "callrec" / "config.py").read_text()).group(1)


def fetch(url, dest):
    if not dest.exists():
        print("download", url)
        urllib.request.urlretrieve(url, dest)
    return dest


def build_launcher(out_exe, given):
    if given:
        shutil.copy(given, out_exe); return
    gcc, windres = shutil.which("x86_64-w64-mingw32-gcc"), shutil.which("x86_64-w64-mingw32-windres")
    if not (gcc and windres):
        sys.exit("MinGW-w64 not found. Install it (e.g. apt install gcc-mingw-w64-x86-64) or pass --launcher FreeCallNotes.exe")
    src, tmp = ROOT / "launcher", ROOT / "build" / "cache" / "launcher"
    tmp.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "assets" / "brand" / "icon.ico", tmp / "icon.ico")
    shutil.copy(src / "res.rc", tmp / "res.rc")
    subprocess.check_call([windres, "res.rc", "-O", "coff", "-o", "res.o"], cwd=tmp)
    subprocess.check_call([gcc, "-municode", "-mwindows", "-Os", "-s", str(src / "launcher.c"), "res.o", "-o", str(out_exe)], cwd=tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--launcher", help="prebuilt FreeCallNotes.exe to use instead of compiling launcher/launcher.c")
    args = ap.parse_args()
    ver = version()
    cache, dist = ROOT / "build" / "cache", ROOT / "dist"
    cache.mkdir(parents=True, exist_ok=True)
    app = dist / "FreeCallNotes"
    if app.exists():
        shutil.rmtree(app)
    app.mkdir(parents=True)

    # 1. embedded Python
    with zipfile.ZipFile(fetch(PY_URL, cache / f"python-{PY_VERSION}-embed-amd64.zip")) as z:
        z.extractall(app / "python")
    pth = next((app / "python").glob("python*._pth"))
    pth.write_text("python312.zip\n.\nLib\\site-packages\n..\nimport site\n")

    # 2. Windows wheels, unpacked into site-packages
    wheels = cache / "wheels"
    subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "-r", str(ROOT / "build" / "requirements-windows.txt"),
                           "--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.12",
                           "--implementation", "cp", "-d", str(wheels)])
    site = app / "python" / "Lib" / "site-packages"
    site.mkdir(parents=True)
    for w in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(w) as z:
            z.extractall(site)
    # place "<pkg>.data" folders the way pip does: data -> Python folder, scripts -> Scripts, purelib/platlib -> site-packages
    for d in list(site.glob("*.data")):
        for sub in d.iterdir():
            dest = {"data": app / "python", "scripts": app / "python" / "Scripts",
                    "purelib": site, "platlib": site}.get(sub.name)
            if dest:
                # skip the duplicate DLLs some wheels put in data/Scripts; the app doesn't need them
                shutil.copytree(sub, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("Scripts") if sub.name == "data" else None)
        shutil.rmtree(d)

    # 3. the app, launcher, docs and licenses
    shutil.copytree(ROOT / "callrec", app / "callrec", ignore=shutil.ignore_patterns("__pycache__"))
    build_launcher(app / "FreeCallNotes.exe", args.launcher)
    legal = app / "legal"
    legal.mkdir()
    for f in ["LICENSE", "THIRD_PARTY_NOTICES.md", "DISCLAIMER.md", "PRIVACY.md"]:
        shutil.copy(ROOT / f, legal / f.replace(".md", ".txt") if f != "LICENSE" else legal / "LICENSE.txt")
    shutil.copy(ROOT / "build" / "README-windows.txt", app / "README.txt")

    # 4. zip
    out = dist / f"FreeCallNotes-{ver}-windows-x64.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(app.rglob("*")):
            z.write(p, p.relative_to(dist))
    print(f"built {out} ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
