"""Global Windows keys, delivered once on the Tk main thread."""
import ctypes
from ctypes import wintypes
import threading
import json
import time
import uuid
from pathlib import Path


class GlobalHotkey:
    def __init__(self, root, callback, virtual_key, identifier, retry=False):
        self.root = root
        self.callback = callback
        self.virtual_key = virtual_key
        self.identifier = identifier
        self.retry = retry
        self.stop = threading.Event()
        self.pressed = threading.Event()
        self.ready = threading.Event()
        self.registered = False
        self.thread = threading.Thread(target=self._listen, name=f'kgpm-hotkey-{virtual_key:02x}', daemon=True)
        self.thread.start()
        self.ready.wait(0.25)
        self.root.after(50, self._deliver)

    def _listen(self):
        user = ctypes.windll.user32
        self.registered = bool(user.RegisterHotKey(None, self.identifier, 0x4000, self.virtual_key))
        self.ready.set()
        if not self.registered and not self.retry:
            return
        try:
            msg = wintypes.MSG()
            while not self.stop.wait(0.02):
                if not self.registered:
                    if self.stop.wait(.5):
                        break
                    self.registered = bool(user.RegisterHotKey(None, self.identifier, 0x4000, self.virtual_key))
                    continue
                while user.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == 0x0312 and msg.wParam == self.identifier:
                        self.pressed.set()
        finally:
            if self.registered:
                user.UnregisterHotKey(None, self.identifier)

    def _deliver(self):
        if self.stop.is_set():
            return
        if self.pressed.is_set():
            self.pressed.clear()
            self.callback()
        self.root.after(50, self._deliver)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=0.3)


class EmergencyHotkey(GlobalHotkey):
    def __init__(self, root, callback):
        super().__init__(root, callback, 0x78, 0x4B47)


class CommandBus:
    """Atomic local messages; commands created before startup are never replayed."""
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.seen = {p.name for p in self.folder.glob('*.json')}

    def send(self, command):
        if command not in {'toggle', 'stop'}:
            raise ValueError('Unknown hotkey command')
        target = self.folder / (str(time.time_ns()) + '-' + uuid.uuid4().hex + '.json')
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps({'command': command}), encoding='ascii')
        temporary.replace(target)

    def receive(self):
        commands = []
        paths = sorted(self.folder.glob('*.json'))
        self.seen.intersection_update(path.name for path in paths)
        for path in paths:
            if path.name in self.seen:
                continue
            try:
                command = json.loads(path.read_text(encoding='ascii')).get('command')
            except (OSError, ValueError):
                continue
            self.seen.add(path.name)
            if command in {'toggle', 'stop'}:
                commands.append(command)
        return commands


class SharedHotkeys:
    def __init__(self, root, toggle, stop, folder):
        self.root, self.callbacks = root, {'toggle': toggle, 'stop': stop}
        self.bus = CommandBus(folder)
        self.closed = False
        self.keys = [GlobalHotkey(root, lambda: self.send('toggle'), 0x77, 0x4B48, retry=True),
                     GlobalHotkey(root, lambda: self.send('stop'), 0x78, 0x4B47, retry=True)]
        root.bind('<F8>', lambda _event: self.send('toggle'))
        root.bind('<F9>', lambda _event: self.send('stop'))
        root.after(50, self.deliver)

    def send(self, command):
        try:
            self.bus.send(command)
        except OSError:
            # Never lose the local emergency stop if disk messaging fails.
            self.callbacks[command]()

    def deliver(self):
        if self.closed:
            return
        try:
            commands = self.bus.receive()
        except OSError:
            commands = []
        if 'stop' in commands:
            self.callbacks['stop']()
        else:
            for command in commands:
                self.callbacks[command]()
        self.root.after(50, self.deliver)

    def close(self):
        self.closed = True
        for key in self.keys:
            key.close()
