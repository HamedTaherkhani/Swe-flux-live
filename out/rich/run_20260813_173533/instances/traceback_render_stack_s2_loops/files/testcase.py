"""Exercise traceback rendering through Console.print."""

from __future__ import annotations

import io
import random
import unittest

from rich.console import Console
from rich.traceback import Frame, Stack, Trace, Traceback


class TestRenderStackTraceLoop(unittest.TestCase):
    def test_console_print_traceback(self) -> None:
        rng = random.Random(0x5EED)
        layer_count = 9 + sum(rng.randrange(2, 5) for _ in range(11))

        frames: list[Frame] = []
        for idx in range(layer_count):
            locals_map = {"slot": idx, "tag": f"t{idx % 7}"} if idx % 3 == 1 else None
            last_inst = None
            if idx % 4 == 2:
                base_line = 40 + (idx % 6)
                last_inst = ((base_line, 4), (base_line + 2, 12))
            frames.append(
                Frame(
                    filename=__file__,
                    lineno=30 + (idx % 9),
                    name=f"hop_{idx}",
                    line="raise marker",
                    locals=locals_map,
                    last_instruction=last_inst,
                )
            )

        trace = Trace(
            stacks=[
                Stack(
                    exc_type="RuntimeError",
                    exc_value="synthetic chain",
                    frames=frames,
                )
            ]
        )
        cap = max(6, (layer_count // 3) | 1)
        tb = Traceback(trace=trace, show_locals=True, max_frames=cap, extra_lines=2)
        out = io.StringIO()
        console = Console(file=out, width=120, color_system=None, force_terminal=False)
        console.print(tb)

        rendered = out.getvalue()
        self.assertIn("Traceback", rendered)
        self.assertIn("RuntimeError", rendered)
        self.assertGreater(len(rendered), layer_count * 4)
