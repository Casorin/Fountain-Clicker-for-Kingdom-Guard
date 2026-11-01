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

    def test_star_vase_video_marks_verified_background_profile(self):
        for name,rect in [('prize',self.config.prize_label_crop),
                          ('daily',self.config.daily_label_crop),('wish',self.config.wish_label_crop)]:
            with Image.open(self.config.layout_template_dir/(name+'_star_vase.png')) as crop:
                self.image.paste(crop,(rect.left,rect.top))
        anchors=analyze_stream_anchors(self.image,self.config)
        self.assertTrue(anchors.event_screen_ok and anchors.button_visible)
        self.assertEqual(anchors.title_variant,'star_vase')
        from app.production_ocr import ProductionOcrPipeline
        from test_digit_visibility import Engines,FIXTURES
        engines=Engines()
        with Image.open(FIXTURES/'star_vase_video.png') as crop:
            result=ProductionOcrPipeline(engines=engines).process(crop,'video-star',
                frame_local_control=True,recovery_allowed=anchors.button_visible,
                allow_dim_blue_background=(anchors.title_variant=='star_vase'
                    and anchors.event_screen_ok and anchors.button_visible))
        self.assertEqual(result.current.value,10200)
        self.assertFalse(result.notification.veto)
        self.assertEqual(engines.calls,['rapid','paddle'])
        rect=self.config.daily_label_crop
        self.image.paste('black',(rect.left-3,rect.top-3,rect.right+3,rect.bottom+3))
        self.assertNotEqual(analyze_stream_anchors(self.image,self.config).title_variant,'star_vase')

    def test_wrong_size_never_authorizes_input(self):
        result=analyze_stream_anchors(self.image.resize((540,540)),self.config)
        self.assertFalse(result.event_screen_ok or result.button_visible or result.continuation_screen_ok)
