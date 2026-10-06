from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image

from app.diagnostics_writer import DiagnosticsWriter


class DiagnosticsWriterTests(unittest.TestCase):
    def test_background_writer_flushes_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "event"
            writer = DiagnosticsWriter(max_queue_size=2)

            accepted = writer.submit(
                target,
                {"prize_crop.png": Image.new("RGB", (32, 16), "white")},
                "value=123000",
            )

            self.assertTrue(accepted)
            self.assertTrue(writer.close(timeout=3.0))
            self.assertFalse(writer.is_alive)
            self.assertTrue((target / "prize_crop.png").exists())
            self.assertTrue((target / "decision.txt").exists())
            stats = writer.stats_snapshot()
            self.assertEqual(stats[-1]["status"], "written")
            self.assertGreaterEqual(float(stats[-1]["queue_latency_ms"]), 0.0)

    def test_full_queue_drops_png_without_blocking_and_writes_metadata(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class BlockingImage:
            def copy(self):
                return self

            def save(self, path: Path, **kwargs) -> None:
                started.set()
                release.wait(timeout=2.0)
                path.write_bytes(b"image")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = DiagnosticsWriter(max_queue_size=1)
            self.assertTrue(writer.submit(root / "first", {"image.png": BlockingImage()}, "first"))
            self.assertTrue(started.wait(timeout=1.0))
            self.assertTrue(writer.submit(root / "second", {"image.png": BlockingImage()}, "second"))

            accepted = writer.submit(root / "overflow", {"image.png": BlockingImage()}, "overflow")

            self.assertFalse(accepted)
            self.assertTrue((root / "overflow" / "diagnostics_queue_overflow.txt").exists())
            release.set()
            self.assertTrue(writer.close(timeout=3.0))
            self.assertFalse(writer.is_alive)
            self.assertIn("overflow", [row["status"] for row in writer.stats_snapshot()])


if __name__ == "__main__":
    unittest.main()
