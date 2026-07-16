# Third-party components

Dependencies are installed from PyPI and are not vendored in this repository.

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

RapidOCR's recognition model is installed with the RapidOCR package. The PaddleOCR
`PP-OCRv6_medium_rec` ONNX model is downloaded by the dependency installer into
PaddleX's user cache. Refer to each upstream project for its model and data terms.

This project is not affiliated with or endorsed by Kingdom Guard or MEmu.
