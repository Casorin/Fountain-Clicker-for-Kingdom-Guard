import unittest
from pathlib import Path
from unittest.mock import patch

from app.adb_client import AdbClient, AdbError
from app.memory_guard import low_memory_message
from app.stream_transport import StreamTransport
from unittest.mock import Mock


class MemoryGuardTests(unittest.TestCase):
    def test_low_commit_is_reported(self):
        self.assertIsNotNone(low_memory_message(470 * 1024 * 1024))
        self.assertIsNone(low_memory_message(2 * 1024 ** 3))

    def test_no_adb_process_is_spawned_under_memory_pressure(self):
        with patch('app.memory_guard.available_commit_bytes', return_value=470 * 1024 * 1024), \
                patch('app.adb_client.subprocess.run') as run:
            with self.assertRaisesRegex(AdbError, 'Недостаточно памяти'):
                AdbClient(Path('adb.exe'), 'test-device').devices()
            run.assert_not_called()

    def test_stream_cleanup_finishes_even_if_adb_cannot_start(self):
        adb = Mock()
        adb._run.side_effect = AdbError('Недостаточно памяти')
        stream = StreamTransport(adb, Path('unused'))
        stream.port = 12345
        log = stream.log = Mock()
        stream.close()
        self.assertIsNone(stream.port)
        self.assertIsNone(stream.log)
        log.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
