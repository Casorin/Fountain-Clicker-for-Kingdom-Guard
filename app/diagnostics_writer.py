from __future__ import annotations

from collections import deque
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import time

from PIL import Image


@dataclass(frozen=True)
class DiagnosticsTask:
    target_dir: Path
    images: dict[str, Image.Image]
    decision_text: str
    enqueued_at: float


class DiagnosticsWriter:
    def __init__(self, max_queue_size: int = 20) -> None:
        self._queue: Queue[DiagnosticsTask] = Queue(maxsize=max_queue_size)
        self._stop = threading.Event()
        self._stats_lock = threading.Lock()
        self._stats: deque[dict[str, float | str]] = deque(maxlen=200)
        self._thread = threading.Thread(
            target=self._run,
            name="kgpm-diagnostics-writer",
            daemon=True,
        )
        self._thread.start()

    def submit(
        self,
        target_dir: Path,
        images: dict[str, Image.Image],
        decision_text: str,
    ) -> bool:
        if self._stop.is_set():
            return False
        copies={}
        copied_images={}
        for name,image in images.items():
            if id(image) not in copies:
                copies[id(image)]=image.copy()
            copied_images[name]=copies[id(image)]
        task = DiagnosticsTask(
            target_dir=target_dir,
            images=copied_images,
            decision_text=decision_text,
            enqueued_at=time.perf_counter(),
        )
        try:
            self._queue.put_nowait(task)
            return True
        except Full:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "diagnostics_queue_overflow.txt").write_text(
                decision_text + "\nwarning=diagnostics queue full; PNG files skipped\n",
                encoding="utf-8",
            )
            with self._stats_lock:
                self._stats.append(
                    {
                        "target_dir": str(target_dir),
                        "queue_latency_ms": 0.0,
                        "write_ms": 0.0,
                        "status": "overflow",
                    }
                )
            return False

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                task = self._queue.get(timeout=0.1)
            except Empty:
                continue
            queue_latency_ms = (time.perf_counter() - task.enqueued_at) * 1000.0
            started = time.perf_counter()
            status = "written"
            try:
                task.target_dir.mkdir(parents=True, exist_ok=True)
                written={}
                for name, image in task.images.items():
                    path=task.target_dir/name
                    if id(image) in written:
                        try:
                            os.link(written[id(image)],path)
                        except OSError:
                            shutil.copyfile(written[id(image)],path)
                    else:
                        temporary=path.with_suffix(path.suffix+'.part')
                        image.save(temporary,format='PNG',compress_level=1)
                        os.replace(temporary,path)
                        written[id(image)]=path
                (task.target_dir / "decision.txt").write_text(
                    task.decision_text
                    + f"\ndiagnostics_queue_latency_ms={queue_latency_ms:.3f}\n",
                    encoding="utf-8",
                )
            except Exception as exc:
                status = f"error:{type(exc).__name__}"
            finally:
                write_ms = (time.perf_counter() - started) * 1000.0
                with self._stats_lock:
                    self._stats.append(
                        {
                            "target_dir": str(task.target_dir),
                            "queue_latency_ms": queue_latency_ms,
                            "write_ms": write_ms,
                            "status": status,
                        }
                    )
                self._queue.task_done()

    def stats_snapshot(self) -> list[dict[str, float | str]]:
        with self._stats_lock:
            return list(self._stats)

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def close(self, timeout: float | None = 3.0) -> bool:
        self._stop.set()
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()
