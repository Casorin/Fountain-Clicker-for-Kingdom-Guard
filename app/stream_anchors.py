from __future__ import annotations

import cv2
import numpy as np
from PIL import Image
from app.capture import crop_rect
from app.config import AppConfig, Rect
from app.vision import AnchorStatus


def analyze_stream_anchors(image: Image.Image, config: AppConfig) -> AnchorStatus:
    def score(name: str, rect: Rect, animated: bool = False) -> float:
        path = config.layout_template_dir / (name+'.png')
        if not path.is_file():
            return 0.0
        template = cv2.imread(str(path), 0)
        if template is None:
            return 0.0
        margin=8 if animated else 3
        search = crop_rect(image, Rect(rect.left-margin,rect.top-margin,rect.right+margin,rect.bottom+margin))
        gray = cv2.cvtColor(np.asarray(search), cv2.COLOR_RGB2GRAY)
        # The game shrinks the wish button by about 2% while it is pressed.
        scales=(.98,1.0,1.02) if animated else (1.0,)
        return max(float(cv2.minMaxLoc(cv2.matchTemplate(gray,
            cv2.resize(template,None,fx=scale,fy=scale),cv2.TM_CCOEFF_NORMED))[1]) for scale in scales)
    prize = score('prize',config.prize_label_crop)
    daily = score('daily',config.daily_label_crop)
    reward = score('reward',config.reward_label_crop)
    button = max(score(name,config.wish_label_crop,animated=True) for name in ['wish','wish_pressed','wish_infinitive','wish_infinitive_pressed'])
    star_scores = (score('prize_star_vase',config.prize_label_crop),
                   score('daily_star_vase',config.daily_label_crop),
                   score('wish_star_vase',config.wish_label_crop,animated=True))
    star_layout = min(star_scores[:2]) >= .90 and star_scores[2] >= .95
    prize = max(prize,star_scores[0])
    daily = max(daily,star_scores[1])
    button = max(button,star_scores[2])
    supported = image.size == (1080,1080)
    button_ok = supported and button >= .95
    screen_ok = supported and min(prize,daily) >= .90
    return AnchorStatus(screen_ok,button_ok,daily,prize,button,0.0,
                        'Призовой фонд / Получено сегодня' if screen_ok else '',
                        'Желание' if button_ok else '', 'star_vase' if star_layout else 'stream_layout','stream_wish',
                        crop_rect(image,config.event_title_crop),crop_rect(image,config.button_crop),
                        supported and max(daily,reward)>=.95 and button_ok)
