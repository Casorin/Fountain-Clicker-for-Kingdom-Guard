import unittest
from unittest.mock import Mock, patch
from app.hotkeys import GlobalHotkey, EmergencyHotkey


class FakeUser32:
    def __init__(self, registered=True, identifier=0x4B48):
        self.registered=registered
        self.identifier=identifier
        self.registration=[]
        self.released=[]
        self.sent=False

    def RegisterHotKey(self, hwnd, identifier, modifiers, key):
        self.registration.append((identifier,modifiers,key))
        return self.registered

    def PeekMessageW(self, pointer, *_):
        if self.sent:
            return 0
        self.sent=True
        pointer._obj.message=0x0312
        pointer._obj.wParam=self.identifier
        return 1

    def UnregisterHotKey(self, hwnd, identifier):
        self.released.append(identifier)


class HotkeyTests(unittest.TestCase):
    def test_f8_registered_without_repeat_and_delivered_once(self):
        user=FakeUser32()
        root=Mock()
        callback=Mock()
        with patch('app.hotkeys.ctypes.windll.user32',user):
            key=GlobalHotkey(root,callback,0x77,0x4B48)
            try:
                self.assertTrue(key.pressed.wait(.5))
                self.assertEqual(user.registration,[(0x4B48,0x4000,0x77)])
                key._deliver()
                key._deliver()
                callback.assert_called_once_with()
            finally:
                key.close()
        self.assertFalse(key.thread.is_alive())
        self.assertEqual(user.released,[0x4B48])

    def test_registration_conflict_does_not_claim_global_key(self):
        user=FakeUser32(registered=False)
        with patch('app.hotkeys.ctypes.windll.user32',user):
            key=GlobalHotkey(Mock(),Mock(),0x77,0x4B48)
            key.close()
        self.assertFalse(key.registered)
        self.assertEqual(user.released,[])

    def test_f9_keeps_its_own_identifier_and_virtual_key(self):
        user=FakeUser32(identifier=0x4B47)
        callback=Mock()
        with patch('app.hotkeys.ctypes.windll.user32',user):
            key=EmergencyHotkey(Mock(),callback)
            try:
                self.assertTrue(key.pressed.wait(.5))
                key._deliver()
                callback.assert_called_once_with()
            finally:
                key.close()
        self.assertEqual(user.registration,[(0x4B47,0x4000,0x78)])
        self.assertEqual(user.released,[0x4B47])

    def test_closed_key_cannot_deliver_queued_action(self):
        user=FakeUser32()
        callback=Mock()
        with patch('app.hotkeys.ctypes.windll.user32',user):
            key=GlobalHotkey(Mock(),callback,0x77,0x4B48)
            key.close()
            key.pressed.set()
            key._deliver()
        callback.assert_not_called()
