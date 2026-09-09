"""Indirect exercise of progress reporting via wrap_file, seek, and track."""

import io
import threading
import unittest
from unittest.mock import patch

from rich.console import Console
from rich.progress import Progress


def _build_payload(seed: int, blocks: int, base_size: int) -> list[bytes]:
    rng = __import__("random").Random(seed)
    chunks: list[bytes] = []
    for index in range(blocks):
        span = base_size + (index % 11) * 17 + (index * 5) % 13 + rng.randint(0, 4)
        body = bytes((seed + index * 31 + byte) % 251 for byte in range(span))
        chunks.append(body)
    return chunks


def _build_seek_offsets(length: int, seed: int, count: int) -> list[int]:
    rng = __import__("random").Random(seed ^ 0xA5A5)
    offsets: list[int] = []
    cursor = 0
    for step in range(count):
        jump = 1 + (step * 7 + rng.randint(0, 9)) % max(1, length // 4)
        cursor = min(length, cursor + jump)
        if step % 5 == 4 and cursor > 0:
            cursor = max(0, cursor - (step % 3) * 11)
        offsets.append(cursor)
    return offsets


class TestProgressUpdateCallOrder(unittest.TestCase):
    def test_indirect_progress_via_reader_and_track(self) -> None:
        seed = 0x51EED
        blocks = _build_payload(seed=seed, blocks=18, base_size=96)
        primary = b"".join(blocks)
        secondary = b"".join(reversed(blocks))

        clock = {"tick": 0.0}

        def fake_get_time() -> float:
            clock["tick"] += 0.37
            return clock["tick"]

        offsets = _build_seek_offsets(len(primary), seed=seed ^ 0xBEEF, count=24)
        console = Console(file=io.StringIO(), force_terminal=False, width=120)

        def _run_track_thread_on_join(self, timeout=None):  # type: ignore[no-untyped-def]
            self.run()

        with patch.object(threading.Thread, "start", lambda self: None), patch.object(
            threading.Thread, "join", _run_track_thread_on_join
        ):
            with Progress(
                console=console,
                disable=False,
                auto_refresh=True,
                speed_estimate_period=2.5,
                get_time=fake_get_time,
                transient=True,
            ) as progress:
                initial_total = 120 + (len(primary) % 37)
                task_id = progress.add_task("ingest", total=initial_total)

                first_reader = progress.wrap_file(
                    io.BytesIO(primary),
                    total=len(primary),
                    task_id=task_id,
                )
                first_reader.seek(offsets[0])

                for offset in offsets[1:12]:
                    first_reader.seek(offset)

                second_reader = progress.wrap_file(
                    io.BytesIO(secondary),
                    total=len(secondary) + 64,
                    task_id=task_id,
                )
                for offset in offsets[12:]:
                    second_reader.seek(offset)

                stepped = [index * 3 + (index % 5) for index in range(16)]
                consumed = list(
                    progress.track(
                        stepped,
                        task_id=task_id,
                        total=float(sum(stepped)),
                        update_period=0.05,
                    )
                )

        self.assertEqual(len(primary), sum(len(block) for block in blocks))
        self.assertEqual(len(secondary), len(primary))
        self.assertEqual(len(consumed), 16)
        self.assertGreater(max(offsets), 0)
        self.assertGreater(clock["tick"], 5.0)
