"""Indirect exercise of Progress.open via rich.progress.open and bound dispatch."""

import io
import inspect
import os
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from rich.console import Console
from rich.progress import Progress
from rich import progress as progress_package


def _build_file_specs(seed: int, count: int, base_len: int) -> list[tuple[str, bytes]]:
    rng = __import__("random").Random(seed)
    specs: list[tuple[str, bytes]] = []
    for index in range(count):
        span = base_len + (index % 13) * 19 + (index * 7) % 17 + rng.randint(0, 6)
        text = "".join(
            chr(32 + (seed + index * 41 + ch) % 95) for ch in range(span)
        )
        specs.append((f"blob_{index:02d}.bin", text.encode("ascii")))
    return specs


def _mode_for_index(index: int) -> str:
    if index % 5 == 0:
        return "rb"
    if index % 5 == 1:
        return "rt"
    return "r"


def _buffering_for_index(index: int, mode: str) -> int:
    if mode == "rb" and index % 7 == 3:
        return 1
    if mode != "rb" and index % 9 == 4:
        return 1
    return -1


class TestProgressOpenCallOrder(unittest.TestCase):
    def test_indirect_open_via_module_entry(self) -> None:
        seed = 0x42A7
        specs = _build_file_specs(seed=seed, count=22, base_len=88)
        tmpdir = tempfile.mkdtemp(prefix="rich_qa_open_")
        paths: list[str] = []
        for name, payload in specs:
            path = os.path.join(tmpdir, name)
            with open(path, "wb") as handle:
                handle.write(payload)
            paths.append(path)

        clock = {"tick": 0.0}

        def fake_get_time() -> float:
            clock["tick"] += 0.29
            return clock["tick"]

        console = Console(file=io.StringIO(), force_terminal=False, width=120)

        def _run_track_thread_on_join(self, timeout=None):  # type: ignore[no-untyped-def]
            self.run()

        totals_checksum = 0
        bytes_read = 0

        with patch.object(threading.Thread, "start", lambda self: None), patch.object(
            threading.Thread, "join", _run_track_thread_on_join
        ):
            for index, path in enumerate(paths[:16]):
                mode = _mode_for_index(index)
                buffering = _buffering_for_index(index, mode)
                explicit_total = None
                if index % 4 == 2:
                    explicit_total = os.path.getsize(path) - (index % 3)

                with progress_package.open(
                    path,
                    mode,
                    buffering=buffering,
                    auto_refresh=False,
                    console=console,
                    transient=True,
                    get_time=fake_get_time,
                    total=explicit_total,
                    description=f"slot-{index}",
                ) as reader:
                    chunk = reader.read(13 + (index % 5))
                    bytes_read += len(chunk)
                    totals_checksum += explicit_total or os.path.getsize(path)

            with Progress(
                console=console,
                disable=False,
                auto_refresh=False,
                get_time=fake_get_time,
                transient=True,
            ) as progress:
                reuse_task = progress.add_task("reuse", total=1)
                entry_name = bytes([111, 112, 101, 110]).decode("ascii")
                bound_reader = types.MethodType(
                    inspect.getattr_static(progress.__class__, entry_name),
                    progress,
                )
                for index, path in enumerate(paths[16:]):
                    mode = _mode_for_index(index + 16)
                    buffering = _buffering_for_index(index + 16, mode)
                    alt_total = os.path.getsize(path) + (index % 4) * 3
                    handle = bound_reader(
                        path,
                        mode,
                        buffering=buffering,
                        task_id=reuse_task,
                        total=alt_total,
                    )
                    payload = handle.read(9 + index)
                    bytes_read += len(payload)
                    totals_checksum += alt_total
                    handle.close()

        self.assertEqual(len(paths), 22)
        self.assertGreater(bytes_read, 0)
        self.assertGreater(totals_checksum, 0)
        self.assertGreater(clock["tick"], 4.0)
