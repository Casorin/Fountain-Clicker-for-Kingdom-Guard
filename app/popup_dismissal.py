"""Whitelist dismissal of two known game dialogs, independent of paid wishes."""
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Popup:
    kind: str
    point: tuple[int, int]


class PopupDismissal:
    def __init__(self):
        self.assets = Path(__file__).resolve().parent.parent / "assets" / "popups"
        self.previous = None
        self.previous_frame = None
        self.attempted = False
        self.clear_frames = 0
        self.templates = {p.stem: np.asarray(Image.open(p).convert("L"))
                          for p in self.assets.glob("*.png")}

    def detect(self, image):
        # These references are calibrated for the currently supported Android profile.
        if image.size != (1080, 1080):
            return None
        gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        for kind, offsets in (("rating", [(-375, -5), (-474, 174)]),
                              ("alliance", [(-590, 117)])):
            close = self.templates.get(f"{kind}_close")
            if close is None:
                continue
            score, location = cv2.minMaxLoc(cv2.matchTemplate(gray, close, cv2.TM_CCOEFF_NORMED))[1::2]
            if score < .96:
                continue
            x, y = location
            valid = True
            for index, (dx, dy) in enumerate(offsets):
                reference = self.templates[f"{kind}_{index}"]
                h, w = reference.shape
                left, top = x + dx, y + dy
                if left < 0 or top < 0 or left + w > 1080 or top + h > 1080:
                    valid = False
                    break
                observed = gray[top:top+h, left:left+w]
                if cv2.matchTemplate(observed, reference, cv2.TM_CCOEFF_NORMED)[0, 0] < .93:
                    valid = False
                    break
            if valid:
                return Popup(kind, (x + close.shape[1]//2, y + close.shape[0]//2))
        return None

    def observe(self, popup, frame_id):
        if frame_id == self.previous_frame:
            return False
        self.previous_frame = frame_id
        if popup is None:
            self.clear_frames += 1
            if self.clear_frames >= 3:
                self.previous = None
                self.attempted = False
            return False
        self.clear_frames = 0
        confirmed = popup == self.previous and not self.attempted
        self.previous = popup
        return confirmed

    def reserve_attempt(self):
        # Reserve before input: transport failure must not cause a blind retry.
        self.attempted = True
