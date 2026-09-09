from __future__ import annotations

import importlib
import io
import sys
import types
import unittest

import click
import ctypes


class _ConsoleState:
    def __init__(self) -> None:
        self.ordinal = 0
        self.seed = 1
        self.failure_stride = 0
        self.last_error = 0

    def configure(self, seed: int, failure_stride: int) -> None:
        self.ordinal = 0
        self.seed = seed
        self.failure_stride = failure_stride
        self.last_error = 0

    def write(self, _handle, _buffer, units, written, _reserved) -> int:
        self.ordinal += 1
        amount = int(units)

        if self.failure_stride and (
            self.ordinal + self.seed * self.seed
        ) % self.failure_stride == 0:
            written._obj.value = 0
            self.last_error = (self.seed * 7 + self.ordinal * 3) % (9 * 9) + 1
            return 0

        divisor = 1 + (self.ordinal * self.seed + amount) % 4
        written._obj.value = min(amount, max(1, amount // divisor))
        self.last_error = 0
        return 1


class _NativeFunction:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


_STATE = _ConsoleState()
_KERNEL = types.SimpleNamespace()
_KERNEL.GetStdHandle = _NativeFunction(lambda value: value)
_KERNEL.ReadConsoleW = _NativeFunction(lambda *args: 1)
_KERNEL.WriteConsoleW = _NativeFunction(_STATE.write)
_KERNEL.GetConsoleMode = _NativeFunction(lambda *args: 1)
_KERNEL.GetLastError = _NativeFunction(lambda: _STATE.last_error)
_SHELL = types.SimpleNamespace()


def _function_factory(*_signature):
    return lambda _spec: _NativeFunction(lambda *args: 0)


def _load_console_module():
    old_platform = sys.platform
    old_windll = getattr(ctypes, "windll", None)
    old_factory = getattr(ctypes, "WINFUNCTYPE", None)
    fake_msvcrt = types.SimpleNamespace(get_osfhandle=lambda value: value)
    sys.modules["msvcrt"] = fake_msvcrt
    ctypes.windll = types.SimpleNamespace(kernel32=_KERNEL, shell32=_SHELL)
    ctypes.WINFUNCTYPE = _function_factory
    sys.platform = "win32"

    try:
        sys.modules.pop("click._winconsole", None)
        return importlib.import_module("click._winconsole")
    finally:
        sys.platform = old_platform

        if old_windll is None:
            del ctypes.windll
        else:
            ctypes.windll = old_windll

        if old_factory is None:
            del ctypes.WINFUNCTYPE
        else:
            ctypes.WINFUNCTYPE = old_factory


_WINCONSOLE = _load_console_module()


class WindowsConsoleWriterCallGraphTest(unittest.TestCase):
    def _exercise(self, seed: int, chunks: int, failure_stride: int) -> None:
        _STATE.configure(seed, failure_stride)
        stream = _WINCONSOLE._get_text_stdout(io.BytesIO())
        successes = 0
        failures = 0

        for index in range(chunks):
            width = 3 + (index * seed + seed * seed) % (7 * 5)
            text = "".join(
                chr(0x41 + (seed * 5 + index * 3 + offset * offset) % (5 * 5))
                for offset in range(width)
            )

            try:
                result = stream.write(f"{text}:{index * seed:x}\n")
            except OSError:
                failures += 1
            else:
                successes += 1
                self.assertGreater(result, 0)

        for _ in range(3 * 3):
            try:
                stream.flush()
            except OSError:
                failures += 1
            else:
                break
        else:
            self.fail("console buffer did not drain")

        stream.close()
        self.assertGreater(successes + failures, 0)
        self.assertLessEqual(successes, chunks)

    def test_dense_short_fragments(self) -> None:
        self._exercise(1, 3 * 5 + 2, 4)

    def test_sparse_wide_fragments(self) -> None:
        self._exercise(2, 4 * 5 + 1, 5)

    def test_prime_stride_fragments(self) -> None:
        self._exercise(3, 5 * 5 - 2, 7)

    def test_success_only_fragments(self) -> None:
        self._exercise(4, 2 * 7 + 3, 0)

    def test_frequent_retries(self) -> None:
        self._exercise(5, 3 * 7, 3)

    def test_alternating_lengths(self) -> None:
        self._exercise(6, 4 * 4 + 3, 6)

    def test_long_generated_payloads(self) -> None:
        self._exercise(7, 5 * 4 + 2, 8)

    def test_offset_failure_cycle(self) -> None:
        self._exercise(8, 3 * 6, 5)

    def test_square_seed_cycle(self) -> None:
        self._exercise(9, 4 * 5 + 3, 7)

    def test_wrapped_seed_cycle(self) -> None:
        self._exercise(5 + 5, 3 * 7 + 3, 4)

    def test_high_stride_cycle(self) -> None:
        self._exercise(6 + 5, 5 * 5 - 1, 9)

    def test_shifted_dense_cycle(self) -> None:
        self._exercise(7 + 5, 4 * 6 + 1, 6)
