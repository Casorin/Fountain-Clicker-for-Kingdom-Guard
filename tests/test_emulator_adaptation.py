from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock
from PIL import Image

from app.config import AppConfig
from app.emulator_discovery import ld_windows, parse_blue_config
from app.screen_geometry import ScreenGeometry
from app.stream_anchors import analyze_stream_anchors
from app.stream_transport import StreamTransport, VideoFrame, FreshFrameUnavailable
from app.adb_client import AdbClient
from app.window_picker import supported_preview
from app.memu_windows import MemuWindow, config_for_window


class GeometryTests(unittest.TestCase):
    def test_known_native_button_positions(self):
        for size, expected in [((1080,1080),(541,1003)), ((720,1280),(361,1189)),
                               ((1080,1920),(542,1783)), ((1920,1080),(961,1003))]:
            with self.subTest(size=size):
                geometry = ScreenGeometry(*size)
                self.assertEqual(geometry.to_native(541,1003),expected)
                self.assertEqual(geometry.normalize(Image.new('RGB',size)).size,(1080,1080))

    def test_out_of_screen_coordinates_never_clamped_to_another_control(self):
        with self.assertRaises(ValueError):
            ScreenGeometry(720,1280).to_native(0,100)

    def test_geometry_change_rejected(self):
        with self.assertRaises(ValueError):
            ScreenGeometry(720,1280).normalize(Image.new('RGB',(1080,1920)))

    def test_too_small_or_extreme_aspect_blocked(self):
        for size in [(200,200),(100,1920),(6000,1080),(1080,5000)]:
            self.assertFalse(supported_preview(Image.new('RGB',size)))
            with self.assertRaises(ValueError):
                ScreenGeometry(*size).normalize(Image.new('RGB',size))

    def test_wrong_screen_and_missing_button_fail_closed_for_all_profiles(self):
        config = AppConfig()
        for height in [1080,1280,1920]:
            directory = config.layout_template_dir if height==1080 else Path('assets/templates/layout_profiles')/str(height)
            custom = replace(config,layout_template_dir=directory)
            with self.subTest(height=height):
                blank=Image.new('RGB',(1080,1080))
                anchors=analyze_stream_anchors(blank,custom)
                self.assertFalse(anchors.event_screen_ok)
                self.assertFalse(anchors.button_visible)
                for name,rect in [('prize',config.prize_label_crop),('daily',config.daily_label_crop)]:
                    with Image.open(directory/(name+'.png')) as image:
                        blank.paste(image,(rect.left,rect.top))
                anchors=analyze_stream_anchors(blank,custom)
                self.assertTrue(anchors.event_screen_ok)
                self.assertFalse(anchors.button_visible)

    def test_resize_between_safety_and_send_emits_no_packet(self):
        transport=StreamTransport(AdbClient(Path('not-adb'),'fake'),Path('missing'))
        transport.frame=Mock(return_value=VideoFrame(Image.new('RGB',(720,1280)),1,time.monotonic(),0))
        transport.control=Mock()
        with self.assertRaises(FreshFrameUnavailable):
            transport.tap(541,1003,expected_size=(1080,1080))
        transport.control.sendall.assert_not_called()


class DiscoveryTests(unittest.TestCase):
    def test_bluestacks_keeps_native_video_and_ld_scales_only_video(self):
        base = AppConfig()
        blue = config_for_window(base, MemuWindow('Blue', 'blue-test', '127.0.0.1:5555', 'BlueStacks'))
        ld = config_for_window(base, MemuWindow('LD', 'ld-test', '127.0.0.2:5555', 'LDPlayer'))
        self.assertEqual(blue.stream_max_size, 0)
        self.assertEqual(ld.stream_max_size, 1080)
        self.assertNotEqual(blue.adb_serial, ld.adb_serial)

    def test_bluestacks_excludes_closed_instances_and_ignores_private_fields(self):
        text='bst.instance.Pie64.adb_port="5555"\nbst.instance.Pie64.display_name="Account A"\n'
        text+='bst.instance.Pie64_1.adb_port="5565"\nbst.instance.Pie64.google_account_logins="private"'
        windows=parse_blue_config(text,{5555})
        self.assertEqual(len(windows),1)
        self.assertEqual(windows[0].uuid,'blue-Pie64')
        self.assertNotIn('private',str(windows))
        self.assertEqual(parse_blue_config(text,set()),[])

    def test_ld_actual_owner_port_and_collision_address(self):
        with tempfile.TemporaryDirectory() as folder:
            console=Path(folder)/'ldconsole.exe'
            console.touch()
            processes=[{'Name':'dnplayer.exe','ExecutablePath':str(Path(folder)/'dnplayer.exe')}]
            ports=[{'OwningProcess':12,'LocalAddress':'0.0.0.0','LocalPort':5555},
                   {'OwningProcess':99,'LocalAddress':'127.0.0.1','LocalPort':5555}]
            reader=Mock(return_value='0,One,1,2,1,11,12\n1,Closed,3,4,0,13,14')
            windows=ld_windows(processes,ports,reader)
            self.assertEqual(len(windows),1)
            self.assertEqual(windows[0].serial,'127.0.0.2:5555')
            self.assertEqual(windows[0].provider,'LDPlayer')
            self.assertEqual(ld_windows(processes,[],reader),[])

    def test_ambiguous_ld_ports_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'ldconsole.exe').touch()
            processes=[{'Name':'dnplayer.exe','ExecutablePath':str(Path(folder)/'dnplayer.exe')}]
            ports=[{'OwningProcess':12,'LocalAddress':'0.0.0.0','LocalPort':port} for port in [5555,5557]]
            self.assertEqual(ld_windows(processes,ports,lambda _: '0,One,1,2,1,11,12'),[])


if __name__=='__main__':
    unittest.main()
