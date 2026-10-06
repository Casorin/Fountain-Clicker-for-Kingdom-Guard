from pathlib import Path
import unittest
from PIL import Image
from app.production_ocr import EngineReading, ProductionOcrPipeline, digit_visibility


FIXTURES = Path(__file__).parent / "fixtures" / "notification_digits"


def frame(number):
    with Image.open(FIXTURES / f"crop_{number:03d}.png") as image:
        return image.convert("RGB")


class Engines:
    def __init__(self):
        self.value = 10200
        self.paddle_value = 10200
        self.confidence = 0.99
        self.calls = []

    def rapid(self, crop):
        self.calls.append("rapid")
        return EngineReading("rapid", str(self.value), self.value, self.confidence, 1)

    def paddle(self, crop):
        self.calls.append("paddle")
        return EngineReading("paddle", str(self.paddle_value), self.paddle_value, self.confidence, 1)


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.engines = Engines()
        self.pipeline = ProductionOcrPipeline(engines=self.engines)

    def test_dark_but_readable_number_requires_both_engines(self):
        result = self.pipeline.process(frame(5), "independent-1")
        self.assertGreater(result.notification.dark_ratio, 0.15)
        self.assertFalse(result.notification.veto)
        self.assertEqual(result.current.value, 10200)
        self.assertEqual(self.engines.calls, ["rapid", "paddle"])
        self.assertIn("digit_visibility_control", result.control_reasons)

    def test_video_visible_frame_does_not_wait_for_consecutive_fade_frames(self):
        self.pipeline.process(frame(8),'hidden',frame_local_control=True)
        result=self.pipeline.process(frame(5),'visible',frame_local_control=True)
        self.assertEqual(result.current.value,10200)
        self.assertFalse(result.notification.veto)
        self.assertEqual(self.engines.calls,['rapid','paddle'])
        self.assertIn('confirmed by PaddleOCR',result.reason)

    def test_video_overlap_still_blocks_before_ocr(self):
        result=self.pipeline.process(frame(8),'hidden',frame_local_control=True)
        self.assertIsNone(result.current)
        self.assertTrue(result.notification.veto)
        self.assertEqual(self.engines.calls,[])

    def test_video_disagreement_and_low_confidence_remain_blocked(self):
        self.engines.paddle_value=999999
        self.assertIsNone(self.pipeline.process(frame(5),'a',frame_local_control=True).current)
        self.engines.paddle_value=10200
        self.engines.confidence=.5
        self.assertIsNone(self.pipeline.process(frame(5),'b',frame_local_control=True).current)

    def test_video_duplicate_or_bad_button_is_not_trusted(self):
        self.assertIsNone(self.pipeline.process(frame(5),'a',frame_local_control=True,recovery_allowed=False).current)
        self.assertIsNone(self.pipeline.process(frame(5),'a',frame_local_control=True).current)

    def test_real_white_text_over_digits_blocks_ocr_before_false_high(self):
        self.engines.value = self.engines.paddle_value = 180350
        result = self.pipeline.process(frame(8), "overlap")
        self.assertTrue(result.notification.veto)
        self.assertIsNone(result.current)
        self.assertEqual(self.engines.calls, [])

    def test_reward_icons_over_digits_are_blocked(self):
        for index in (10, 17, 22):
            with self.subTest(index=index):
                result = self.pipeline.process(frame(index), str(index))
                self.assertTrue(result.notification.veto)
                self.assertIsNone(result.current)

    def test_blank_crop_is_never_visible(self):
        for color in ("black", "white", "gray"):
            self.assertFalse(digit_visibility(Image.new("RGB", (183, 42), color))[0])

    def test_disagreement_on_readable_dim_number_is_rejected(self):
        self.engines.paddle_value = 180350
        self.assertIsNone(self.pipeline.process(frame(5), "dim").current)

    def test_low_confidence_agreement_is_rejected(self):
        self.engines.confidence = 0.50
        self.assertIsNone(self.pipeline.process(frame(5), "dim").current)

    def test_recovery_uses_independent_readings_and_paddle(self):
        self.pipeline.process(frame(8), "blocked")
        self.assertIsNone(self.pipeline.process(frame(5), "guard").current)
        self.assertIsNone(self.pipeline.process(frame(6), "first").current)
        self.assertIsNone(self.pipeline.process(frame(6), "first").current)
        result = self.pipeline.process(frame(7), "second")
        self.assertEqual(result.current.value, 10200)
        self.assertTrue(result.recovered_after_notification)

    def test_recovery_cannot_override_bad_anchors(self):
        self.pipeline.process(frame(8), "blocked")
        self.pipeline.process(frame(5), "guard")
        self.pipeline.process(frame(6), "first")
        result = self.pipeline.process(frame(7), "second", recovery_allowed=False)
        self.assertIsNone(result.current)
        self.assertTrue(self.pipeline.notification_tracker.latched)

    def test_recovery_cannot_accept_low_confidence_agreement(self):
        self.pipeline.process(frame(8), "blocked")
        self.pipeline.process(frame(5), "guard")
        self.engines.confidence = 0.5
        self.pipeline.process(frame(6), "first")
        self.assertIsNone(self.pipeline.process(frame(7), "second").current)

    def test_clean_frame_does_not_need_notification_control(self):
        result = self.pipeline.process(frame(0), "clean")
        self.assertIsNotNone(result.current)
        self.assertEqual(self.engines.calls, ["rapid"])
