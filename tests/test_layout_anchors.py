import unittest
from PIL import Image
from app.config import AppConfig
from app.vision import analyze_anchors


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.c = AppConfig()
        self.screen = Image.new('RGB', (1080, 1080), (30, 45, 60))
        r = self.c.button_crop
        self.screen.paste((220, 175, 50), (r.left, r.top, r.right, r.bottom))
        for name, rect in [('prize', self.c.prize_label_crop), ('daily', self.c.daily_label_crop), ('wish', self.c.wish_label_crop)]:
            with Image.open(self.c.layout_template_dir / f'{name}.png') as crop:
                self.screen.paste(crop, (rect.left, rect.top))

    def test_invariant_layout(self):
        a = analyze_anchors(self.screen, self.c, None)
        self.assertTrue(a.event_screen_ok and a.button_visible)

    def test_any_season_title(self):
        r = self.c.event_title_crop
        for color in ['red', 'white', 'black', 'blue']:
            self.screen.paste(color, (r.left, r.top, r.right, r.bottom))
            self.assertTrue(analyze_anchors(self.screen, self.c, None).event_screen_ok)

    def test_missing_either_label(self):
        for rect in [self.c.prize_label_crop, self.c.daily_label_crop]:
            other = self.screen.copy()
            other.paste('black', (rect.left, rect.top, rect.right, rect.bottom))
            self.assertFalse(analyze_anchors(other, self.c, None).event_screen_ok)

    def test_generic_gold_button_is_not_wish(self):
        r = self.c.wish_label_crop
        self.screen.paste((220, 175, 50), (r.left, r.top, r.right, r.bottom))
        self.assertFalse(analyze_anchors(self.screen, self.c, None).button_visible)

    def test_reward_label_only_authorizes_continuation(self):
        for rect in [self.c.prize_label_crop, self.c.daily_label_crop]:
            self.screen.paste('black', (rect.left, rect.top, rect.right, rect.bottom))
        rect = self.c.reward_label_crop
        with Image.open(self.c.layout_template_dir / 'reward.png') as crop:
            self.screen.paste(crop, (rect.left, rect.top))
        result = analyze_anchors(self.screen, self.c, None)
        self.assertFalse(result.event_screen_ok)
        self.assertTrue(result.continuation_screen_ok)
        rect = self.c.wish_label_crop
        self.screen.paste('black', (rect.left, rect.top, rect.right, rect.bottom))
        self.assertFalse(analyze_anchors(self.screen, self.c, None).continuation_screen_ok)

    def test_pressed_wish_is_recognized(self):
        with Image.open(self.c.layout_template_dir / 'wish_pressed.png') as im:
            self.screen.paste(im, (self.c.wish_label_crop.left, self.c.wish_label_crop.top))
        self.assertTrue(analyze_anchors(self.screen, self.c, None).button_visible)

    def test_new_wish_wording_is_recognized(self):
        with Image.open(self.c.layout_template_dir / 'wish_infinitive.png') as im:
            self.screen.paste(im, (self.c.wish_label_crop.left, self.c.wish_label_crop.top))
        self.assertTrue(analyze_anchors(self.screen, self.c, None).button_visible)

    def test_partial_button_text(self):
        r = self.c.wish_label_crop
        self.screen.paste('black', (r.left, r.top, r.left+100, r.bottom))
        self.assertFalse(analyze_anchors(self.screen, self.c, None).button_visible)

    def test_wrong_resolution(self):
        a = analyze_anchors(self.screen.resize((540, 540)), self.c, None)
        self.assertFalse(a.event_screen_ok or a.button_visible)

    def test_blank_screen(self):
        a = analyze_anchors(Image.new('RGB', (1080,1080)), self.c, None)
        self.assertFalse(a.event_screen_ok or a.button_visible)
