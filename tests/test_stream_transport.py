import struct
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from pathlib import Path
from PIL import Image
from app.adb_client import AdbClient, AdbError
from app.stream_transport import StreamTransport, VideoFrame, touch_packet
from app.monitor import PrizeMonitor


class StreamTransportTests(unittest.TestCase):
    def test_reconnect_resets_video_sequence(self):
        monitor = PrizeMonitor.__new__(PrizeMonitor)
        monitor.config = SimpleNamespace(adb_serial='fake', stream_transport_enabled=True,
                                         stream_server_path=Path('missing'))
        monitor.adb = Mock()
        monitor.adb.connect.return_value = 'connected'
        monitor.adb.devices.return_value = ['fake']
        monitor._stream_sequence = 9000
        with patch('app.stream_transport.StreamTransport') as transport:
            self.assertTrue(monitor.connect()[0])
            transport.return_value.start.assert_called_once()
        self.assertEqual(monitor._stream_sequence, -1)

    def test_failed_connection_closes_partial_transport(self):
        monitor = PrizeMonitor.__new__(PrizeMonitor)
        monitor.config = SimpleNamespace(adb_serial='fake', stream_transport_enabled=True,
                                         stream_server_path=Path('missing'))
        monitor.adb = Mock()
        monitor.adb.devices.return_value = ['fake']
        with patch('app.stream_transport.StreamTransport') as transport:
            transport.return_value.start.side_effect = AdbError('failed')
            self.assertFalse(monitor.connect()[0])
            transport.return_value.close.assert_called_once()
        self.assertIsNone(monitor._stream)

    def setUp(self):
        self.transport = StreamTransport(AdbClient(Path('not-an-adb'), 'fake'), Path('missing'))
        self.transport._clock_ref=(time.monotonic(),0.0)

    def test_touch_coordinates_and_complete_release(self):
        packet = touch_packet(0, 541, 1003, 1080, 1080)
        self.assertEqual(len(packet), 32)
        self.assertEqual(struct.unpack('>BBQiiHHHII', packet), (2,0,0,541,1003,1080,1080,65535,0,0))
        self.assertEqual(touch_packet(1,541,1003,1080,1080)[1],1)

    def test_stale_frame_forbids_tap(self):
        self.transport.latest = VideoFrame(Image.new('RGB',(1080,1080)),1,time.monotonic()-1,0)
        with self.assertRaises(AdbError):
            self.transport.tap(541,1003)

    def test_duplicate_frame_cannot_be_new_observation(self):
        self.transport.latest = VideoFrame(Image.new('RGB',(1080,1080)),1,time.monotonic(),0)
        with self.assertRaises(AdbError):
            self.transport.frame(after=1,timeout=.001)

    def test_control_absent_forbids_input(self):
        self.transport.latest = VideoFrame(Image.new('RGB',(1080,1080)),1,time.monotonic(),0)
        with self.assertRaises(AdbError):
            self.transport.tap(541,1003)

    def test_decode_error_is_reported(self):
        self.transport.error='codec disconnected'
        with self.assertRaisesRegex(AdbError,'codec disconnected'):
            self.transport.frame()

    def test_two_events_sent_in_one_nonqueued_write(self):
        class Control:
            calls=[]
            def sendall(self,data): self.calls.append(data)
        control=Control()
        self.transport.control=control
        self.transport.latest=VideoFrame(Image.new('RGB',(1080,1080)),1,time.monotonic(),0)
        self.transport.tap(541,1003)
        self.assertEqual(len(control.calls),1)
        self.assertEqual(len(control.calls[0]),64)
