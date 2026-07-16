from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.production_ocr import ProductionOcrEngines


def main() -> None:
    crop = Image.new("RGB", (183, 42), (80, 80, 80))
    report = ProductionOcrEngines().warm_up(crop)

    import onnxruntime
    import paddleocr
    import rapidocr

    report.update(
        {
            "python": sys.executable,
            "onnxruntime": onnxruntime.__version__,
            "rapidocr_module": str(Path(rapidocr.__file__).resolve()),
            "paddleocr_module": str(Path(paddleocr.__file__).resolve()),
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
