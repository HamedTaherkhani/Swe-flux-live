"""Direct exercise of legacy_windows_render with programmatic segment buffers."""

from __future__ import annotations

import random
import sys
import types
import unittest
from typing import NamedTuple
from unittest.mock import MagicMock

from rich.segment import ControlType, Segment
from rich.style import Style


def _install_win32_stub() -> None:
    """Stub win32 console types so the renderer imports on non-Windows hosts."""
    if "rich._win32_console" in sys.modules:
        return

    stub = types.ModuleType("rich._win32_console")

    class WindowsCoordinates(NamedTuple):
        row: int
        col: int

    class LegacyWindowsTerm:
        pass

    stub.LegacyWindowsTerm = LegacyWindowsTerm
    stub.WindowsCoordinates = WindowsCoordinates
    sys.modules["rich._win32_console"] = stub


_install_win32_stub()

from rich._windows_renderer import legacy_windows_render  # noqa: E402


def _control_pool() -> list[ControlType]:
    return [
        ControlType.CURSOR_MOVE_TO,
        ControlType.CARRIAGE_RETURN,
        ControlType.HOME,
        ControlType.CURSOR_UP,
        ControlType.CURSOR_DOWN,
        ControlType.CURSOR_FORWARD,
        ControlType.CURSOR_BACKWARD,
        ControlType.CURSOR_MOVE_TO_COLUMN,
        ControlType.HIDE_CURSOR,
        ControlType.SHOW_CURSOR,
        ControlType.ERASE_IN_LINE,
        ControlType.SET_WINDOW_TITLE,
    ]


def _build_control_code(rng: random.Random, control_type: ControlType, tag: int):
    if control_type == ControlType.CURSOR_MOVE_TO:
        return (control_type, 1 + rng.randrange(0x2F), 1 + rng.randrange(0x13))
    if control_type == ControlType.CURSOR_MOVE_TO_COLUMN:
        return (control_type, 1 + rng.randrange(0x4F))
    if control_type == ControlType.ERASE_IN_LINE:
        return (control_type, rng.randrange(3))
    if control_type == ControlType.SET_WINDOW_TITLE:
        return (control_type, f"w{tag:x}")
    return (control_type,)


def _build_buffer(seed: int, slot: int) -> list[Segment]:
    rng = random.Random(seed ^ (slot * 0x85EBCA6B))
    pool = _control_pool()
    count = (rng.randrange(8) + 6) * (rng.randrange(5) + 3)
    segments: list[Segment] = []

    for idx in range(count):
        bucket = (idx * 5 + rng.randrange(9)) % 8
        if bucket == 0:
            segments.append(Segment(f"a{idx:x}", None))
        elif bucket == 1:
            segments.append(
                Segment(
                    f"b{idx:x}",
                    Style.parse("bold" if idx % 2 else "italic"),
                )
            )
        elif bucket == 2:
            segments.append(
                Segment(
                    "",
                    None,
                    [
                        (ControlType.ERASE_IN_LINE, 0),
                        (ControlType.ERASE_IN_LINE, 1),
                        (ControlType.ERASE_IN_LINE, 2),
                    ],
                )
            )
        elif bucket == 3:
            codes = [
                _build_control_code(rng, pool[rng.randrange(len(pool))], idx)
                for _ in range(1 + rng.randrange(3))
            ]
            segments.append(Segment("", None, codes))
        elif bucket == 4:
            segments.append(
                Segment(
                    f"c{idx:x}",
                    Style.parse("underline"),
                    [(ControlType.HOME,)],
                )
            )
        elif bucket == 5:
            segments.append(
                Segment(
                    "",
                    None,
                    [
                        (ControlType.CURSOR_MOVE_TO, 1 + rng.randrange(0x2F), 1 + rng.randrange(0x13)),
                        (ControlType.SHOW_CURSOR,),
                    ],
                )
            )
        elif bucket == 6:
            segments.append(
                Segment(
                    "",
                    None,
                    [(ControlType.CARRIAGE_RETURN,) for _ in range(1 + rng.randrange(3))],
                )
            )
        else:
            segments.append(
                Segment(
                    "",
                    None,
                    [
                        (ControlType.CURSOR_BACKWARD,),
                        (ControlType.CURSOR_FORWARD,),
                    ],
                )
            )

    return segments


class TestLegacyWindowsRenderExecutedPath(unittest.TestCase):
    def test_programmatic_multi_invocation_render(self) -> None:
        term = MagicMock()
        base_seed = 0xC0FFEE
        invocation_total = 5
        buffers = [
            _build_buffer(base_seed, slot)
            for slot in range(invocation_total)
        ]

        total_segments = 0
        for buffer in buffers:
            legacy_windows_render(buffer, term)
            total_segments += len(buffer)

        term_activity = (
            term.write_text.call_count
            + term.write_styled.call_count
            + term.move_cursor_to.call_count
            + term.move_cursor_up.call_count
            + term.move_cursor_down.call_count
            + term.move_cursor_forward.call_count
            + term.move_cursor_backward.call_count
            + term.move_cursor_to_column.call_count
            + term.hide_cursor.call_count
            + term.show_cursor.call_count
            + term.erase_end_of_line.call_count
            + term.erase_start_of_line.call_count
            + term.erase_line.call_count
            + term.set_title.call_count
        )
        self.assertGreater(term_activity, total_segments)
        self.assertGreater(total_segments, invocation_total * invocation_total)
        self.assertEqual(len(buffers), invocation_total)
