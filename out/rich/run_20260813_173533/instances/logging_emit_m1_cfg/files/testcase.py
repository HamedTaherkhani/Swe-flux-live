"""Direct exercise of RichHandler.emit across varied control-flow paths."""

from __future__ import annotations

import io
import logging
import random
import sys
import unittest
from typing import Callable
from unittest.mock import MagicMock

from rich._null_file import NullFile
from rich.console import Console
from rich.logging import RichHandler


def _console(width: int = 100) -> Console:
    return Console(
        file=io.StringIO(),
        force_terminal=True,
        width=width,
        color_system=None,
        _environ={},
    )


def _handler(**kwargs) -> RichHandler:
    return RichHandler(console=_console(), enable_link_path=False, **kwargs)


def _record(
    rng: random.Random,
    tag: int,
    *,
    level: int = logging.INFO,
    exc_info=None,
    **extra,
) -> logging.LogRecord:
    bucket = (tag * 7 + rng.randrange(11)) % 5
    verbs = ("GET", "POST", "PATCH", "PUT", "DELETE")
    verb = verbs[bucket]
    path = f"/api/{tag % 13}/item/{rng.randrange(9000)}"
    msg = f"{verb} {path} status={200 + (tag % 3)}"
    record = logging.LogRecord(
        name="rich_qa.logging_emit",
        level=level,
        pathname=__file__,
        lineno=10 + (tag % 40),
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _fresh_exc_info(rng: random.Random, tag: int):
    marker = tag * 17 + rng.randrange(1000)

    def _raise() -> None:
        raise RuntimeError(f"trace-{marker}")

    try:
        _raise()
    except RuntimeError:
        return sys.exc_info()


def _emit_many(
    handler: RichHandler,
    rng: random.Random,
    count: int,
    *,
    level_fn: Callable[[int], int] | None = None,
    exc_fn: Callable[[int], object] | None = None,
) -> int:
    emitted = 0
    for idx in range(count):
        level = level_fn(idx) if level_fn else logging.INFO
        exc_info = exc_fn(idx) if exc_fn else None
        handler.emit(_record(rng, idx, level=level, exc_info=exc_info))
        emitted += 1
    return emitted


class TestRichHandlerEmitFlow(unittest.TestCase):
    def test_plain_emit_programmatic_batch(self) -> None:
        rng = random.Random(0xE01)
        handler = _handler()
        total = _emit_many(handler, rng, 22)
        self.assertEqual(total, 22)
        self.assertGreater(len(handler.console.file.getvalue()), 0)

    def test_level_sweep_emits(self) -> None:
        rng = random.Random(0xE02)
        handler = _handler()
        levels = (
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        )

        def level_fn(idx: int) -> int:
            return levels[(idx + rng.randrange(3)) % len(levels)]

        total = _emit_many(handler, rng, 14, level_fn=level_fn)
        self.assertEqual(total, 14)
        self.assertIn("WARNING", handler.console.file.getvalue())

    def test_markup_extra_records(self) -> None:
        rng = random.Random(0xE03)
        handler = _handler(markup=False)
        for idx in range(11):
            record = _record(rng, idx + 40, exc_info=None, markup=True)
            record.msg = f"[bold]evt-{idx}[/bold] token={rng.randrange(500)}"
            handler.emit(record)
        output = handler.console.file.getvalue()
        self.assertGreater(len(output), 20)
        self.assertNotIn("[bold]", output)

    def test_rich_traceback_single_emit(self) -> None:
        rng = random.Random(0xE04)
        handler = _handler(rich_tracebacks=True)
        handler.emit(_record(rng, 1, level=logging.ERROR, exc_info=_fresh_exc_info(rng, 1)))
        rendered = handler.console.file.getvalue()
        self.assertIn("RuntimeError", rendered)

    def test_traceback_with_message_only_formatter(self) -> None:
        rng = random.Random(0xE05)
        handler = _handler(rich_tracebacks=True)
        handler.setFormatter(logging.Formatter("%(message)s"))
        for idx in range(6):
            handler.emit(
                _record(rng, idx + 50, level=logging.ERROR, exc_info=_fresh_exc_info(rng, idx))
            )
        rendered = handler.console.file.getvalue()
        self.assertIn("trace-", rendered)
        self.assertGreater(rendered.count("RuntimeError"), 0)

    def test_traceback_programmatic_batch(self) -> None:
        rng = random.Random(0xE06)
        handler = _handler(
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            tracebacks_extra_lines=2,
        )
        emitted = 0
        for idx in range(9):
            if idx % 3 == 0:
                handler.emit(_record(rng, idx + 70, level=logging.WARNING))
            else:
                handler.emit(
                    _record(
                        rng,
                        idx + 70,
                        level=logging.ERROR,
                        exc_info=_fresh_exc_info(rng, idx + 70),
                    )
                )
            emitted += 1
        self.assertEqual(emitted, 9)
        self.assertGreater(len(handler.console.file.getvalue()), 40)

    def test_null_file_console_path(self) -> None:
        rng = random.Random(0xE07)
        console = Console(file=NullFile(), _environ={})
        handler = RichHandler(console=console, enable_link_path=False)
        captured: list[logging.LogRecord] = []
        handler.handleError = captured.append  # type: ignore[method-assign]
        for idx in range(5):
            handler.emit(_record(rng, idx + 90))
        self.assertEqual(len(captured), 5)

    def test_print_failure_exception_path(self) -> None:
        rng = random.Random(0xE08)
        handler = _handler()
        handler.console.print = MagicMock(side_effect=OSError("sink-closed"))  # type: ignore[method-assign]
        captured: list[logging.LogRecord] = []
        handler.handleError = captured.append  # type: ignore[method-assign]
        for idx in range(4):
            handler.emit(_record(rng, idx + 110))
        self.assertEqual(len(captured), 4)
        self.assertGreater(handler.console.print.call_count, 0)

    def test_exc_info_empty_tuple_skips_traceback(self) -> None:
        rng = random.Random(0xE09)
        handler = _handler(rich_tracebacks=True)
        empty = (None, None, None)
        for idx in range(7):
            handler.emit(_record(rng, idx + 130, exc_info=empty))
        rendered = handler.console.file.getvalue()
        self.assertEqual(rendered.count("status="), 7)
        self.assertNotIn("trace-", rendered)

    def test_plain_emit_with_time_formatter(self) -> None:
        rng = random.Random(0xE0A)
        handler = _handler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M"))
        total = _emit_many(handler, rng, 10)
        rendered = handler.console.file.getvalue()
        self.assertEqual(total, 10)
        self.assertGreater(len(rendered), 10)

    def test_mixed_plain_and_traceback_sequence(self) -> None:
        rng = random.Random(0xE0B)
        handler = _handler(rich_tracebacks=True)
        steps = 16
        for idx in range(steps):
            use_tb = (idx * 5 + rng.randrange(7)) % 4 == 0
            if use_tb:
                handler.emit(
                    _record(rng, idx + 150, exc_info=_fresh_exc_info(rng, idx + 150))
                )
            else:
                handler.emit(_record(rng, idx + 150))
        rendered = handler.console.file.getvalue()
        self.assertGreater(rendered.count("trace-"), 0)
        self.assertGreater(len(rendered), steps)

    def test_seeded_dense_emit_walk(self) -> None:
        rng = random.Random(0xE0C)
        handler = _handler(markup=True)
        acc = 0
        for idx in range(24):
            acc = (acc * 3 + rng.randrange(17)) % 997
            record = _record(rng, idx + 200)
            record.msg = f"walk-{acc} hop={idx}"
            handler.emit(record)
        self.assertGreater(acc, 0)
        self.assertGreater(len(handler.console.file.getvalue()), 24)
