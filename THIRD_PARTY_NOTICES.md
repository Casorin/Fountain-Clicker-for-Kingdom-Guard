# Third-party components

Python dependencies are installed from PyPI. The pinned official scrcpy server is
bundled in assets/scrcpy with its Apache-2.0 license.

The portable Windows archive also includes the CPython runtime (PSF License;
see .python/LICENSE.txt), Tcl/Tk from that Python distribution, dependency
license files in .python/Lib/site-packages, and the PaddleX recognition model.
Local runtime data, account selections, and user diagnostics are not distributed.

The Windows archive includes the unmodified open-source Android Debug Bridge
37.0.1 and its Windows support DLLs from Google's SDK Platform-Tools archive.
See assets/adb/NOTICE.txt for the upstream notices and licenses, and
assets/adb/source.json for the download source and pinned SHA256 hashes.
No fastboot, disk tools, or vendor-modified ADB clients are distributed.

| Component | Version | License |
|---|---:|---|
| RapidOCR | 3.9.1 | Apache-2.0 |
| PaddleOCR | 3.7.0 | Apache-2.0 |
| PaddleX OCR core | 3.7.2 | Apache-2.0 |
| ONNX Runtime | 1.27.0 | MIT |
| NumPy | 2.3.5 | BSD-3-Clause and bundled third-party notices |
| Pillow | 12.3.0 | MIT-CMU |
| OpenCV Python | 5.0.0.93 (transitive) | Apache-2.0 and bundled notices |
| OpenCV contrib Python | 4.10.0.84 (transitive) | Apache-2.0 and bundled notices |
| PyAV | 19.0.1 | BSD-3-Clause and bundled FFmpeg notices |
| scrcpy server | 4.1 | Apache-2.0 |
| Android Debug Bridge | 37.0.1 | Apache-2.0 and bundled third-party notices |

scrcpy server source: https://github.com/Genymobile/scrcpy/tree/v4.1
Release SHA256: deacb991ed2509715160ffdc7907e47b4160eb30d1566217e9047fd5b8850cae

RapidOCR's recognition model is installed with the RapidOCR package. The PaddleOCR
`PP-OCRv6_medium_rec` ONNX model is downloaded by the dependency installer into
PaddleX's user cache. Refer to each upstream project for its model and data terms.

This project is not affiliated with or endorsed by Kingdom Guard or MEmu.
