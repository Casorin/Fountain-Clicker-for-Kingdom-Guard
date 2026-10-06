import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from dataclasses import replace
from datetime import timedelta
from PIL import Image
from app.gem_guard import GemGuard, parse_balance
from app.persistence import UserRangeConfig
from tests.test_in_range_confirmation import InRangeConfirmationTests, anchors, recognition
from app.monitor import MonitorPhase


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.now=1.0
        self.guard=GemGuard(None, clock=lambda:self.now)
        self.guard.read=Mock(return_value=40500)
        self.image=Image.new('RGB',(1080,1080))

    def test_floor_reserves_every_sent_command(self):
        for _ in range(5):
            self.assertTrue(self.guard.permits(self.image,40000)[0])
            self.guard.reserve_sent_tap()
        self.assertEqual(self.guard.permits(self.image,40000),(False,'floor'))

    def test_unknown_balance_fails_closed(self):
        self.guard.read.return_value=None
        self.assertEqual(self.guard.permits(self.image,40000),(False,'unknown'))

    def test_old_video_read_cannot_refund_reserved_spending(self):
        self.guard.permits(self.image,40000)
        self.guard.reserve_sent_tap()
        self.now+=.6
        self.guard.refresh(self.image,frame_time=1.0)
        self.assertEqual(self.guard.estimated,40400)

    def test_settled_rejected_commands_are_reconciled_with_actual_wallet(self):
        self.guard.permits(self.image,40000)
        self.guard.reserve_sent_tap()
        self.now+=1
        self.guard.refresh(self.image,frame_time=2.0)
        self.assertEqual(self.guard.estimated,40500)

    def test_balance_parser_rejects_decimals_and_abbreviations(self):
        self.assertEqual(parse_balance('40 200'),40200)
        self.assertEqual(parse_balance('1 226 886'),1226886)
        self.assertEqual(parse_balance('0'),0)
        self.assertIsNone(parse_balance('40.2K'))

    def test_seven_digit_crop_includes_last_digit_and_excludes_plus(self):
        screen = Image.new('RGB', (1080, 1080))
        screen.paste('white', (1020, 25, 1030, 55))
        screen.paste('red', (1031, 25, 1060, 55))
        engines = Mock()
        engines._rapid_engine.return_value.return_value = Mock(txts=['1 226 886'], scores=[.99])
        result = Mock()
        result.json = {'res': {'rec_text': '1 226 886', 'rec_score': .99}}
        engines._paddle_engine.return_value.predict.return_value = [result]
        guard = GemGuard(engines)
        self.assertEqual(guard.read(screen), 1226886)
        roi = engines._rapid_engine.return_value.call_args.args[0]
        self.assertEqual(roi.shape, (120, 344, 3))
        self.assertTrue((roi[:, -24:-12] > 200).all())
        self.assertFalse(((roi[:, :, 0] > 200) & (roi[:, :, 1] < 50)).any())
        self.assertEqual(guard.permits(screen, 1150000), (True, 'ok'))

    def test_settings_are_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'user_config.json'
            UserRangeConfig(60000,500000,True,40000).save(path)
            loaded=UserRangeConfig.load(path,1,2)
            self.assertTrue(loaded.no_upper_limit)
            self.assertEqual(loaded.minimum_gems,40000)


class WalletDecisionTests(InRangeConfirmationTests):
    def test_no_upper_limit_applies_to_both_modes(self):
        self.monitor.user_range=replace(self.monitor.user_range,no_upper_limit=True)
        self.assertTrue(self.monitor.is_target_value(2000000,real_mode=False))
        self.assertTrue(self.monitor.is_target_value(2000000,real_mode=True))
        self.assertFalse(self.monitor.is_target_value(1))

    def test_low_wallet_disarms_before_any_input(self):
        m=self.monitor
        m.user_range=replace(m.user_range,minimum_gems=40000)
        m.gem_guard=Mock()
        m.gem_guard.permits.return_value=(False,'floor')
        m.state.real_mode_armed=True
        m.state.phase=MonitorPhase.ACTIVE_CLICKING
        m.resume=Mock()
        result=m._handle_active_clicking(self.now,Image.new('RGB',(1080,1080)),recognition(),123500,anchors(),[])
        self.assertFalse(result[0])
        self.assertFalse(m.state.real_mode_armed)
        self.assertEqual(m.adb.tap_calls,[])

    def test_unreadable_wallet_waits_without_disarming_or_input(self):
        m=self.monitor
        m.user_range=replace(m.user_range,minimum_gems=40000)
        m.gem_guard=Mock()
        m.gem_guard.permits.return_value=(False,'unknown')
        m.state.real_mode_armed=True
        m.state.phase=MonitorPhase.ACTIVE_CLICKING
        m.resume=Mock()
        result=m._handle_active_clicking(self.now,Image.new('RGB',(1080,1080)),recognition(),123500,anchors(),[])
        self.assertFalse(result[0])
        self.assertTrue(m.state.real_mode_armed)
        self.assertIsNone(m.state.next_click_at)
        self.assertEqual(m.state.phase, MonitorPhase.ACTIVE_CLICKING)
        self.assertIn('Режим «С кликами» сохранён', m.state.last_status)
        self.assertEqual(m.adb.tap_calls,[])

    def test_wallet_recovery_passes_guard_but_still_requires_fresh_safety_frame(self):
        m=self.monitor
        m.user_range=replace(m.user_range,minimum_gems=40000)
        m.gem_guard=Mock()
        m.gem_guard.permits.side_effect=[(False,'unknown'), (True,'ok')]
        m.state.real_mode_armed=True
        m.state.phase=MonitorPhase.ACTIVE_CLICKING
        image=Image.new('RGB',(1080,1080))
        m._handle_active_clicking(self.now,image,recognition(),123500,anchors(),[])
        self.assertTrue(m.state.real_mode_armed)
        # The restored wallet must not bypass freshness or send a test input.
        m._latest_capture_completed_at=self.now-timedelta(seconds=10)
        result=m._handle_active_clicking(self.now,image,recognition(),123500,anchors(),[])
        self.assertFalse(result[0] or result[1])
        self.assertTrue(m.state.real_mode_armed)
        self.assertEqual(m.adb.tap_calls,[])
