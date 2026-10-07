"""Read-only replay of recorded notification crops; never opens ADB."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.production_ocr import ProductionOcrPipeline, digit_visibility
from app.recognition import extract_digit_roi


def previous_visibility(crop):
    rgb = np.asarray(extract_digit_roi(crop), dtype=np.float32)[3:-3, 3:-3]
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    white = (rgb.min(axis=2) > 150) & (rgb.max(axis=2)-rgb.min(axis=2) < 30)
    cool = ((blue > red+15) | (green > red+25)) & (rgb.max(axis=2) > 90)
    yellow = (red > 90) & (green > 70) & (red-blue > 25) & (green-blue > 20)
    return not (white.mean() > .05 or cool.mean() > .01 or yellow.sum() < 40)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('folders', nargs='+', type=Path)
    args = parser.parse_args()
    pipeline = ProductionOcrPipeline()
    changed = []
    total = before = after = 0
    for folder in args.folders:
        for path in sorted(folder.glob('frame_[0-9][0-9][0-9].png')):
            with Image.open(path) as image:
                crop = image.convert('RGB')
            old = previous_visibility(crop)
            new = digit_visibility(crop)[0]
            total += 1
            before += old
            after += new
            if new and not old:
                result = pipeline.process(crop, str(path), frame_local_control=True)
                changed.append({'file': str(path), 'value': result.current.value if result.current else None,
                    'rapid': result.rapid.value if result.rapid else None,
                    'paddle': result.paddle.value if result.paddle else None})
    print(json.dumps({'frames': total, 'visible_before': before, 'visible_after': after,
                      'changed': changed}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
