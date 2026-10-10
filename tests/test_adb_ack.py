import queue
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from app.adb_client import AdbClient, AdbError


class AckTests(unittest.TestCase):
    def test_read_only_adb_commands_do_not_open_console(self):
        import subprocess
        client = AdbClient(Path('unused-adb'), 'unused-device')
        result = SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        with patch('app.memory_guard.low_memory_message', return_value=None), \
             patch('app.adb_client.subprocess.run', return_value=result) as run:
            client.devices()
        self.assertEqual(run.call_args.kwargs['creationflags'],
                         getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(run.call_args.args[0], ['unused-adb', 'devices'])

    def make_client(self, reply):
        client=AdbClient(Path('unused-adb'), 'unused-device')
        writes=[]
        def write(command):
            writes.append(command)
            token=command.decode().split('echo ')[1].split(':')[0]
            client._shell_output.put(command)
            reply(client._shell_output,token)
        shell=SimpleNamespace(stdin=SimpleNamespace(write=write,flush=lambda:None))
        client._persistent_shell=lambda:shell
        return client,writes

    def test_only_matching_completion_acknowledges_tap(self):
        def reply(q,token):
            q.put(b'KGPM_DONE_other:0\n')
            q.put((token+':0\n').encode())
        c,w=self.make_client(reply)
        c.tap_persistent(541,1003)
        self.assertEqual(len(w),1)

    def test_input_failure_is_not_retried(self):
        c,w=self.make_client(lambda q,t:q.put((t+':1\n').encode()))
        with self.assertRaises(AdbError):c.tap_persistent(541,1003)
        self.assertEqual(len(w),1)

    def test_disconnection_is_not_retried(self):
        c,w=self.make_client(lambda q,t:q.put(None))
        with self.assertRaises(AdbError):c.tap_persistent(541,1003)
        self.assertEqual(len(w),1)

    def test_timeout_is_not_retried(self):
        c,w=self.make_client(lambda q,t:None)
        c._shell_output.get=Mock(side_effect=queue.Empty)
        with self.assertRaises(AdbError):c.tap_persistent(541,1003)
        self.assertEqual(len(w),1)
