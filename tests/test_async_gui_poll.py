import threading
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from app.monitor import MonitorPhase
from app.ui import AppWindow


class AsyncPollTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.withdraw()
        self.app=object.__new__(AppWindow)
        self.app.root=self.root
        self.app.running=True
        self.app.config=SimpleNamespace(poll_interval_ms=200)
        self.app._poll_thread=None
        self.app._poll_result=None
        self.app._poll_error=None
        self.applied=[]
        self.pauses=[]
        def slow_poll():
            time.sleep(.15)
            return SimpleNamespace(phase=MonitorPhase.WAITING)
        self.app.monitor=SimpleNamespace(poll_once=slow_poll,
            state=SimpleNamespace(phase=MonitorPhase.WAITING),
            pause=lambda:self.pauses.append(True),_tap_cancel=threading.Event())
        self.app._apply_snapshot=self.applied.append

    def tearDown(self):
        self.app.running=False
        if self.app._poll_thread is not None:
            self.app._poll_thread.join(1)
        for job in self.root.tk.splitlist(self.root.tk.call('after','info')):
            self.root.after_cancel(job)
        self.root.destroy()

    def pump(self,duration):
        until=time.monotonic()+duration
        while time.monotonic()<until:
            self.root.update()
            time.sleep(.002)

    def test_slow_poll_does_not_block_tk_heartbeat(self):
        beats=[]
        def heartbeat():
            beats.append(time.monotonic())
            self.root.after(10,heartbeat)
        heartbeat()
        started=time.monotonic()
        self.app._schedule_tick()
        self.assertLess(time.monotonic()-started,.05)
        self.pump(.2)
        self.assertGreater(len(beats),10)
        self.assertEqual(len(self.applied),1)

    def test_pause_discards_inflight_result(self):
        self.app._schedule_tick()
        self.app.running=False
        self.app.monitor._tap_cancel.set()
        self.pump(.2)
        self.assertEqual(self.applied,[])
        self.assertTrue(self.pauses)
