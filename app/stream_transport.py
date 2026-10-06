"""Pinned scrcpy 4.1 video/control transport, independent of game internals."""
from __future__ import annotations

import hashlib
import secrets
import socket
import select
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image

from app.adb_client import AdbClient, AdbError

SERVER_SHA256 = 'deacb991ed2509715160ffdc7907e47b4160eb30d1566217e9047fd5b8850cae'


class FreshFrameUnavailable(AdbError):
    pass


@dataclass(frozen=True)
class VideoFrame:
    image: Image.Image
    sequence: int
    received_at: float
    pts_us: int


def touch_packet(action: int, x: int, y: int, width: int, height: int) -> bytes:
    return struct.pack('>BBQiiHHHII', 2, action, 0, x, y, width, height,
                       0xffff if action == 0 else 0, 0, 0)


class StreamTransport:
    def __init__(self, adb: AdbClient, server: Path, max_fps: int = 30, max_size: int = 0) -> None:
        self.adb = adb
        self.server = server
        self.max_fps = max_fps
        self.max_size = max_size
        self.video: socket.socket | None = None
        self.control: socket.socket | None = None
        self.process = None
        self.thread: threading.Thread | None = None
        self.port: int | None = None
        self.condition = threading.Condition()
        self.send_lock = threading.Lock()
        self.latest: VideoFrame | None = None
        self.error: str | None = None
        self.stopping = threading.Event()
        self.size = (0, 0)
        self.log = None
        self._clock_ref = None
        self._clock_thread = None

    def start(self) -> None:
        if hashlib.sha256(self.server.read_bytes()).hexdigest() != SERVER_SHA256:
            raise AdbError('scrcpy server checksum mismatch')
        remote = '/data/local/tmp/kgpm-scrcpy-4.1.jar'
        try:
            self.adb._run('-s', self.adb.serial, 'push', str(self.server), remote)
        except AdbError as exc:
            if 'protocol fault' not in str(exc):
                raise
            # Some BlueStacks adbd versions reject the client's sync protocol.
            # Copy only this verified tool to /data/local/tmp, never game files.
            result = subprocess.run([str(self.adb.adb_path), '-s', self.adb.serial,
                                     'exec-out', "sh -c 'cat > " + remote + "'"],
                                    input=self.server.read_bytes(), capture_output=True, timeout=15,
                                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:
                raise AdbError('Could not install the video helper: ' + result.stderr.decode('utf-8',errors='replace'))
            verified = self.adb._run('-s',self.adb.serial,'exec-out','sha256sum',remote)
            if verified.stdout.decode('ascii',errors='replace').split()[0] != SERVER_SHA256:
                raise AdbError('Remote video helper checksum mismatch')
        scid = secrets.randbelow(0x7fffffff)
        completed = self.adb._run('-s', self.adb.serial, 'forward', 'tcp:0', f'localabstract:scrcpy_{scid:08x}')
        self.port = int(completed.stdout.strip())
        args = [str(self.adb.adb_path), '-s', self.adb.serial, 'exec-out',
                f'CLASSPATH={remote}', 'app_process', '/', 'com.genymobile.scrcpy.Server', '4.1',
                f'scid={scid:08x}', 'tunnel_forward=true', 'audio=false', 'control=true',
                'cleanup=false', 'clipboard_autosync=false', 'send_dummy_byte=true',
                'send_device_meta=false', f'max_size={self.max_size}', f'max_fps={self.max_fps}', 'video_bit_rate=12000000',
                'ignore_video_encoder_constraints=true',
                'power_on=false', 'log_level=warn']
        self.log = (self.server.parent / f'scrcpy-server-{scid:08x}.log').open('wb')
        self.process = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            self.video = self._connect(first=True)
            self.control = self._connect()
            self.control.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.control.settimeout(.25)
            self._sync_clock()
            self._clock_thread = threading.Thread(target=self._clock_loop,name='kgpm-video-clock',daemon=True)
            self._clock_thread.start()
            self.thread = threading.Thread(target=self._read_video, name='kgpm-video-stream', daemon=True)
            self.thread.start()
            self.frame(timeout=8)
        except Exception:
            self.close()
            raise

    def _connect(self, first: bool = False) -> socket.socket:
        deadline = time.monotonic() + 5
        while True:
            try:
                connection = socket.create_connection(('127.0.0.1', self.port), timeout=.5)
                connection.settimeout(2)
                if first and connection.recv(1) != b'\0':
                    connection.close()
                    raise OSError('Server is not listening yet')
                return connection
            except OSError:
                if time.monotonic() >= deadline:
                    raise AdbError('scrcpy connection timed out')
                time.sleep(.05)

    def _read(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            if self.stopping.is_set() or self.video is None:
                raise EOFError('video closed')
            part = self.video.recv(size-len(data))
            if not part:
                raise EOFError('video disconnected')
            data.extend(part)
        return bytes(data)

    def _read_video(self) -> None:
        try:
            import av
            if self._read(4) != b'h264':
                raise AdbError('Unexpected scrcpy codec')
            decoder = av.CodecContext.create('h264', 'r')
            config = b''
            sequence = 0
            while not self.stopping.is_set():
                flags, length = struct.unpack('>QI', self._read(12))
                if flags & (1 << 63):
                    self.size = (flags & 0xffffffff, length)
                    continue
                if length > 20_000_000:
                    raise AdbError('Invalid video packet size')
                payload = self._read(length)
                if flags & (1 << 62):
                    config = payload
                    continue
                packet = av.Packet(config + payload)
                config = b''
                for decoded in decoder.decode(packet):
                    sequence += 1
                    if select.select([self.video],[],[],0)[0]:
                        # Decode dependencies, but do not convert/display old
                        # frames while newer packets are already waiting.
                        continue
                    image = decoded.to_image()
                    pts_us = flags & ((1 << 61)-1)
                    arrived = time.monotonic()
                    frame = VideoFrame(image, sequence, arrived, pts_us)
                    with self.condition:
                        self.latest = frame
                        self.condition.notify_all()
        except Exception as exc:
            if not self.stopping.is_set():
                self.error = str(exc)
            with self.condition:
                self.condition.notify_all()

    def frame(self, after: int = -1, timeout: float = .75) -> VideoFrame:
        deadline = time.monotonic()+timeout
        with self.condition:
            while True:
                if self.error or self.stopping.is_set():
                    raise AdbError(self.error or 'Video stream closed')
                now=time.monotonic()
                if self.latest is not None and self.latest.sequence > after and self._clock_ref is not None:
                    host,android=self._clock_ref
                    source_received=min(self.latest.received_at,host+self.latest.pts_us/1_000_000-android)
                    if now-host<=2 and now-source_received<=.25:
                        return replace(self.latest,received_at=source_received)
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise FreshFrameUnavailable('No fresh synchronized video frame')
                self.condition.wait(remaining)

    def _sync_clock(self) -> None:
        before=time.monotonic()
        result=self.adb._run('-s',self.adb.serial,'exec-out','cat','/proc/uptime',timeout=.75)
        after=time.monotonic()
        android=float(result.stdout.split()[0])
        self._clock_ref=((before+after)/2,android)

    def _clock_loop(self) -> None:
        while not self.stopping.wait(.5):
            try:
                self._sync_clock()
            except Exception:
                # An expired clock prevents input; never invent freshness.
                pass

    def tap(self, x: int, y: int, expected_size=None) -> None:
        frame = self.frame()
        width, height = frame.image.size
        if expected_size is not None and expected_size != (width, height):
            raise FreshFrameUnavailable('Screen size changed after the safety check')
        if self.control is None or not (0 <= x < width and 0 <= y < height):
            raise AdbError('Control channel or coordinates invalid')
        with self.send_lock:
            # One complete press/release. No command queue and no automatic retry.
            self.control.sendall(touch_packet(0, x, y, width, height) +
                                 touch_packet(1, x, y, width, height))

    def close(self) -> None:
        self.stopping.set()
        for connection in [self.control, self.video]:
            if connection is not None:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        self.control = self.video = None
        with self.condition:
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=3)
        if self._clock_thread is not None:
            self._clock_thread.join(timeout=1)
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=3)
        if self.port is not None:
            try:
                self.adb._run('-s', self.adb.serial, 'forward', '--remove', f'tcp:{self.port}', check=False)
            except AdbError:
                # Local sockets/processes are already closed; scarce memory
                # must not prevent the rest of shutdown from completing.
                pass
            finally:
                self.port = None
        if self.log is not None:
            self.log.close()
            self.log = None
