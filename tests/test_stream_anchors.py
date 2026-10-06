import unittest
from PIL import Image
from app.config import AppConfig
from app.stream_anchors import analyze_stream_anchors


class StreamAnchorTests(unittest.TestCase):
    def setUp(self):
        self.config=AppConfig()
        self.image=Image.new('RGB',(1080,1080),(30,40,50))
        for name,rect in [('prize',self.config.prize_label_crop),('daily',self.config.daily_label_crop),
                          ('reward',self.config.reward_label_crop),('wish_infinitive',self.config.wish_label_crop)]:
            with Image.open(self.config.layout_template_dir/(name+'.png')) as crop:
                self.image.paste(crop,(rect.left,rect.top))

    def test_normal_and_pressed_buttons(self):
        self.assertTrue(analyze_stream_anchors(self.image,self.config).button_visible)
        r=self.config.wish_label_crop
        with Image.open(self.config.layout_template_dir/'wish_infinitive_pressed.png') as crop:
            self.image.paste(crop,(r.left,r.top))
        self.assertTrue(analyze_stream_anchors(self.image,self.config).button_visible)

    def test_missing_button_never_authorizes_continuation(self):
        r=self.config.wish_label_crop
        self.image.paste((220,175,50),(r.left-3,r.top-3,r.right+3,r.bottom+3))
        result=analyze_stream_anchors(self.image,self.config)
        self.assertFalse(result.button_visible or result.continuation_screen_ok)

    def test_pressed_two_percent_scale_is_supported(self):
        r=self.config.wish_label_crop
        self.image.paste((220,175,50),(r.left-8,r.top-8,r.right+8,r.bottom+8))
        with Image.open(self.config.layout_template_dir/'wish_infinitive.png') as crop:
            scaled=crop.resize((round(crop.width*.98),round(crop.height*.98)),Image.Resampling.BILINEAR)
            self.image.paste(scaled,(r.left+2,r.top+1))
        self.assertTrue(analyze_stream_anchors(self.image,self.config).button_visible)

    def test_reward_label_does_not_authorize_start(self):
        for r in [self.config.prize_label_crop,self.config.daily_label_crop]:
            self.image.paste('black',(r.left-3,r.top-3,r.right+3,r.bottom+3))
        result=analyze_stream_anchors(self.image,self.config)
        self.assertFalse(result.event_screen_ok)
        self.assertTrue(result.continuation_screen_ok)

    def test_wrong_size_never_authorizes_input(self):
        result=analyze_stream_anchors(self.image.resize((540,540)),self.config)
        self.assertFalse(result.event_screen_ok or result.button_visible or result.continuation_screen_ok)
