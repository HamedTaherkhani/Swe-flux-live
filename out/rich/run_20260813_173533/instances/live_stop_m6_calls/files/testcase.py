"""Exercise Live teardown through context-manager entry points."""

from __future__ import annotations

import io
import random
import unittest
from typing import Callable, Optional

from rich.console import Console
from rich.live import Live
from rich.text import Text


def _capture_console(
    *,
    width: int = 80,
    height: int = 24,
    force_terminal: Optional[bool] = True,
) -> Console:
    return Console(
        width=width,
        height=height,
        force_terminal=force_terminal,
        legacy_windows=False,
        color_system=None,
        _environ={},
    )


def _step_count(seed: int, slot: int) -> int:
    rng = random.Random(seed ^ (slot * 0x9E3779B1))
    return 15 + rng.randrange(18)


def _build_lines(rng: random.Random, count: int, prefix: str) -> str:
    lines: list[str] = []
    for idx in range(count):
        token = (idx * 19 + rng.randrange(113)) % 991
        lines.append(f"{prefix}{idx:02d}:{token}")
    return "\n".join(lines)


def _run_context_updates(
    console: Console,
    *,
    steps: int,
    seed: int,
    transient: bool = False,
    auto_refresh: bool = False,
    screen: bool = False,
    vertical_overflow: str = "ellipsis",
    redirect_stdout: bool = True,
    redirect_stderr: bool = True,
    get_renderable: Optional[Callable[[], str]] = None,
    initial: str = "",
) -> str:
    rng = random.Random(seed)
    console.begin_capture()
    with Live(
        initial,
        console=console,
        auto_refresh=auto_refresh,
        transient=transient,
        screen=screen,
        vertical_overflow=vertical_overflow,
        redirect_stdout=redirect_stdout,
        redirect_stderr=redirect_stderr,
        get_renderable=get_renderable,
    ) as session:
        payload = initial
        for step in range(steps):
            chunk = _build_lines(rng, 1 + (step % 4), f"s{step}_")
            payload = f"{payload}{chunk}\n" if payload else f"{chunk}\n"
            session.update(payload, refresh=True)
            if redirect_stdout and step % 3 == 0:
                console.print(f"log-{step}")
    return console.end_capture()


class TestLiveStopInvocationCounts(unittest.TestCase):
    def _assert_nonempty_capture(self, captured: str, min_len: int) -> None:
        self.assertGreater(len(captured), min_len)
        self.assertTrue(captured.strip() or "\x1b" in captured)

    def test_minimal_blank_context(self) -> None:
        console = _capture_console(width=40, height=8)
        console.begin_capture()
        with Live("", console=console, auto_refresh=False):
            pass
        captured = console.end_capture()
        self.assertIn("\x1b", captured)

    def test_seeded_growth_persistent(self) -> None:
        console = _capture_console(height=12)
        captured = _run_context_updates(
            console,
            steps=_step_count(0xA01, 1),
            seed=0xA01,
            transient=False,
        )
        self._assert_nonempty_capture(captured, 40)

    def test_seeded_growth_transient(self) -> None:
        console = _capture_console(height=10)
        captured = _run_context_updates(
            console,
            steps=_step_count(0xB02, 2),
            seed=0xB02,
            transient=True,
        )
        self._assert_nonempty_capture(captured, 30)

    def test_file_console_non_terminal(self) -> None:
        console = _capture_console(force_terminal=False, height=6)
        captured = _run_context_updates(
            console,
            steps=_step_count(0xC03, 3),
            seed=0xC03,
            transient=False,
        )
        self.assertGreater(captured.count("\n"), 8)

    def test_screen_mode_with_manual_refresh(self) -> None:
        console = _capture_console(width=24, height=6)
        console.begin_capture()
        with Live(
            Text("panel"),
            console=console,
            screen=True,
            auto_refresh=False,
        ) as session:
            for idx in range(_step_count(0xD04, 4)):
                session.update(Text(f"panel-{idx}"), refresh=True)
        captured = console.end_capture()
        self.assertIn("panel", captured)

    def test_auto_refresh_background_thread(self) -> None:
        console = _capture_console(height=8)
        console.begin_capture()
        with Live(
            "",
            console=console,
            auto_refresh=True,
            refresh_per_second=8.0,
            transient=True,
        ) as session:
            rng = random.Random(0xE05)
            for idx in range(_step_count(0xE05, 5)):
                session.update(_build_lines(rng, 2, f"auto{idx}_"))
        captured = console.end_capture()
        self._assert_nonempty_capture(captured, 20)

    def test_nested_inner_non_transient(self) -> None:
        console = _capture_console(height=10)
        console.begin_capture()
        with Live("", console=console, auto_refresh=False, transient=False) as outer:
            with Live(
                Text("inner"),
                console=console,
                auto_refresh=False,
                transient=False,
            ) as inner:
                rng = random.Random(0xF06)
                for idx in range(_step_count(0xF06, 6)):
                    inner.update(Text(f"inner-{idx}-{rng.randrange(999)}"), refresh=True)
            outer.update(Text("outer-tail"), refresh=True)
        captured = console.end_capture()
        self.assertIn("inner", captured)

    def test_nested_transient_stack(self) -> None:
        console = _capture_console(height=9)
        console.begin_capture()
        with Live("", console=console, auto_refresh=False, transient=True) as outer:
            with Live(
                "",
                console=console,
                auto_refresh=False,
                transient=True,
            ) as inner:
                rng = random.Random(0x107)
                steps = _step_count(0x107, 7)
                for idx in range(steps):
                    inner.update(_build_lines(rng, 1, f"n{idx}_"), refresh=True)
        captured = console.end_capture()
        self._assert_nonempty_capture(captured, 25)

    def test_redirect_io_disabled(self) -> None:
        console = _capture_console()
        captured = _run_context_updates(
            console,
            steps=_step_count(0x208, 8),
            seed=0x208,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self.assertGreater(len(captured), 35)

    def test_dynamic_get_renderable(self) -> None:
        console = _capture_console(height=11)
        rng = random.Random(0x309)
        state = {"value": "seed"}

        def supplier() -> str:
            state["value"] = _build_lines(rng, 2, "dyn_")
            return state["value"]

        captured = _run_context_updates(
            console,
            steps=_step_count(0x309, 9),
            seed=0x309,
            initial="",
            get_renderable=supplier,
        )
        self.assertIn("dyn_", captured)

    def test_vertical_overflow_crop(self) -> None:
        console = _capture_console(height=5)
        captured = _run_context_updates(
            console,
            steps=_step_count(0x40A, 10),
            seed=0x40A,
            vertical_overflow="crop",
        )
        self._assert_nonempty_capture(captured, 30)

    def test_sequential_sessions(self) -> None:
        console = _capture_console(width=60, height=8)
        combined = io.StringIO()
        for slot in range(4):
            seed = 0x50B + slot * 997
            chunk = _run_context_updates(
                console,
                steps=_step_count(seed, slot + 11),
                seed=seed,
                transient=slot % 2 == 0,
            )
            combined.write(chunk)
        merged = combined.getvalue()
        self.assertGreater(len(merged), 80)

    def test_string_update_coercion(self) -> None:
        console = _capture_console(height=7)
        console.begin_capture()
        with Live("", console=console, auto_refresh=False) as session:
            rng = random.Random(0x60C)
            for idx in range(_step_count(0x60C, 12)):
                session.update(_build_lines(rng, 3, f"str{idx}_"), refresh=True)
        captured = console.end_capture()
        self.assertGreater(captured.count("str"), 5)
