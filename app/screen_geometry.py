"""Height-scaled, centered game layout; native coordinates remain explicit."""
from dataclasses import dataclass
from PIL import Image
from pathlib import Path
import numpy as np


@dataclass(frozen=True)
class ScreenGeometry:
    width: int
    height: int

    @property
    def scale(self):
        return self.height / 1080

    def to_native(self, x, y):
        point = (round((x - 540) * self.scale + self.width / 2), round(y * self.scale))
        if not (0 <= point[0] < self.width and 0 <= point[1] < self.height):
            raise ValueError('Target is outside the Android screen')
        return point

    def normalize(self, image):
        if image.size != (self.width, self.height):
            raise ValueError('Screen dimensions changed')
        if not (480 <= self.height <= 4096 and .5 <= self.width / self.height <= 2.5):
            raise ValueError('Unsupported screen geometry')
        columns = np.asarray(image)[::max(1,self.height//100), :, :3].max(axis=(0,2))
        right = self.width
        while right > self.width * .92 and columns[right-1] < 8:
            right -= 1
        if image.size == (1080, 1080) and right == self.width:
            return image
        scale = self.scale
        normalized = image.transform((1080,1080), Image.Transform.AFFINE,
            (scale, 0, self.width / 2 - 540 * scale, 0, scale, 0),
            Image.Resampling.BICUBIC)
        # Wallet is attached to the right edge, unlike the centered event panel.
        wallet = image.crop((round(right - 135 * scale), round(25 * scale),
                             round(right - 49 * scale), round(55 * scale)))
        normalized.paste(wallet.resize((86,30), Image.Resampling.LANCZOS), (945,25))
        return normalized

    def template_directory(self, base):
        profile_height = 1920 if self.width/self.height < .8 and self.height == 1080 else self.height
        candidate = Path(base).parent / 'layout_profiles' / str(profile_height)
        return candidate if candidate.is_dir() and self.width != self.height else Path(base)
