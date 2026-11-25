# Third-party notices

FreeCallNotes itself is licensed under the GNU General Public License v3.0 or later (see [LICENSE](LICENSE)). It uses the third-party components below, each under its own license. All of these licenses allow use in, and distribution with, a GPL-3.0 program. Their license texts are included inside each package in the Windows build (`python/Lib/site-packages/<package>-<version>.dist-info/`) and at the links below.

## Speech models (downloaded when installed, not included in this repository or the zip)

| Model | Publisher | License |
|---|---|---|
| Nemotron Speech Streaming EN 0.6B, int8 ONNX conversion for sherpa-onnx (`csukuangfj/sherpa-onnx-nemotron-speech-streaming-en-0.6b-int8-2026-01-14`) | NVIDIA (original model, `nvidia/nemotron-speech-streaming-en-0.6b`); ONNX conversion by the sherpa-onnx project | NVIDIA Open Model License Agreement: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/ |
| Moonshine v2 Medium Streaming (English) | Moonshine AI | MIT License: https://github.com/moonshine-ai/moonshine (Note: Moonshine's non-English models use a separate non-commercial community license. FreeCallNotes only uses the English model.) |
| Whisper large-v3 turbo, int8 ONNX conversion for sherpa-onnx (`csukuangfj/sherpa-onnx-whisper-turbo`), optional | OpenAI (original model, `openai/whisper-large-v3-turbo`); ONNX conversion by the sherpa-onnx project | MIT License: https://github.com/openai/whisper |
| Silero VAD (voice activity detector, downloaded with Whisper) | Silero Team | MIT License: https://github.com/snakers4/silero-vad |

**Notice required by the NVIDIA Open Model License:**

> Licensed by NVIDIA Corporation under the NVIDIA Open Model License

NVIDIA's license includes terms on lawful and ethical use, and does not grant permission to use NVIDIA's trademarks beyond describing the origin of the model.

## Software bundled in the Windows build

| Component | Version | License | Source |
|---|---|---|---|
| Python (embeddable package) | 3.12.10 | Python Software Foundation License | https://www.python.org |
| sherpa-onnx, sherpa-onnx-core | 2.0.3 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |
| ONNX Runtime (inside sherpa-onnx and moonshine-voice) | | MIT | https://github.com/microsoft/onnxruntime |
| moonshine-voice | 0.1.6 | MIT | https://github.com/moonshine-ai/moonshine |
| PyAudioWPatch (includes PortAudio, MIT) | 0.2.12.9 | Apache-2.0 | https://github.com/s0d3s/PyAudioWPatch |
| python-soxr (includes libsoxr) | 1.1.0 | LGPL-2.1-or-later | https://github.com/dofuuz/python-soxr |
| NumPy | 2.5.5 | BSD-3-Clause (and bundled components under 0BSD, MIT, Zlib, CC0-1.0) | https://numpy.org |
| msvc-runtime (Microsoft Visual C++ runtime DLLs) | 14.51.36231 | Microsoft Visual C++ Redistributable license terms | https://pypi.org/project/msvc-runtime/ |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3 |
| certifi | 2026.11.20 | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | 3.5.3 | MIT | https://github.com/jawah/charset_normalizer |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| tqdm | 4.70.1 | MPL-2.0 and MIT | https://github.com/tqdm/tqdm |
| filelock | 4.3.1 | MIT | https://github.com/tox-dev/filelock |
| platformdirs | 4.14.8 | MIT | https://github.com/tox-dev/platformdirs |
| google-crc32c | 1.9.0 | Apache-2.0 | https://github.com/googleapis/python-crc32c |
| sounddevice | 0.5.6 | MIT | https://github.com/spatialaudio/python-sounddevice |
| cffi | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi |
| comtypes (call pop-ups: Windows audio notifications) | 1.5.0 | MIT | https://github.com/enthought/comtypes |
| pycaw (Windows audio interface definitions, used by the call pop-ups) | 20260927 | MIT | https://github.com/AndreMiras/pycaw |
| pycparser | 3.12 | BSD-3-Clause | https://github.com/eliben/pycparser |

Notes:

- **LGPL (python-soxr / libsoxr):** used unmodified. It is a separate Python package in `python/Lib/site-packages/soxr`, so you can replace it with your own build of the same library. Source code is available at the link above.
- **MPL-2.0 (certifi, tqdm):** used unmodified; source code is available at the links above.
- **Microsoft Visual C++ runtime:** redistributed as permitted by Microsoft's redistributable terms. These are system libraries as described in section 1 of the GPL-3.0.
- **Microsoft Edge** is used to display the app window. It is part of Windows and is not distributed with FreeCallNotes.

Versions listed are those pinned in `build/requirements-windows.txt`. If you change them, update this file.
