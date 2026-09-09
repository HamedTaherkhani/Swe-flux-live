from __future__ import annotations

import ctypes
import importlib
import sys
import types
import unittest

import click


class _ReadState:
    def __init__(self) -> None:
        self.ordinal = 0
        self.carry = sum(ord(char) ** 2 for char in click.__name__)
        self.last_error = 0

    def read(self, _handle, buffer, units, units_read, _reserved) -> int:
        self.ordinal += 1
        amount = int(units)
        mixed = (
            self.carry * 41
            + self.ordinal * self.ordinal * 23
            + amount * (self.ordinal % 11 + 5)
        ) % 65521
        quota = 1 + mixed % amount
        units_read._obj.value = quota
        self.carry = (mixed + quota * 47 + amount * 13) % 32749

        if (self.carry + self.ordinal * 7) % 13 == 0:
            buffer[0] = b"\x1a"
        else:
            buffer[0] = bytes((65 + self.carry % 26,))

        if (mixed ^ self.carry) % 17 == 0:
            self.last_error = 995
        else:
            self.last_error = (mixed + self.ordinal * 31) % 997

        return int((mixed + quota + self.ordinal) % 9 != 0)


class _NativeFunction:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


_STATE = _ReadState()
_KERNEL = types.SimpleNamespace()
_KERNEL.GetStdHandle = _NativeFunction(lambda value: value)
_KERNEL.ReadConsoleW = _NativeFunction(_STATE.read)
_KERNEL.WriteConsoleW = _NativeFunction(lambda *args: 1)
_KERNEL.GetConsoleMode = _NativeFunction(lambda *args: 1)
_KERNEL.GetLastError = _NativeFunction(lambda: _STATE.last_error)
_SHELL = types.SimpleNamespace()


def _function_factory(*_signature):
    return lambda _spec: _NativeFunction(lambda *args: 0)


def _load_console_module():
    old_platform = sys.platform
    old_windll = getattr(ctypes, "windll", None)
    old_factory = getattr(ctypes, "WINFUNCTYPE", None)
    old_msvcrt = sys.modules.get("msvcrt")
    sys.modules["msvcrt"] = types.SimpleNamespace(get_osfhandle=lambda value: value)
    ctypes.windll = types.SimpleNamespace(kernel32=_KERNEL, shell32=_SHELL)
    ctypes.WINFUNCTYPE = _function_factory
    sys.platform = "win32"

    try:
        sys.modules.pop("click._winconsole", None)
        return importlib.import_module("click._winconsole")
    finally:
        sys.platform = old_platform
        if old_msvcrt is None:
            sys.modules.pop("msvcrt", None)
        else:
            sys.modules["msvcrt"] = old_msvcrt

        if old_windll is None:
            del ctypes.windll
        else:
            ctypes.windll = old_windll

        if old_factory is None:
            del ctypes.WINFUNCTYPE
        else:
            ctypes.WINFUNCTYPE = old_factory


_WINCONSOLE = _load_console_module()


class WindowsConsoleReaderStateTest(unittest.TestCase):
    def test_generated_read_schedule(self) -> None:
        reader = _WINCONSOLE._WindowsConsoleReader(
            sum((index + 3) * ord(char) ** 2 for index, char in enumerate(click.__name__))
        )
        _WINCONSOLE.time.sleep = lambda _delay: None
        state = sum((index + 1) * ord(char) ** 3 for index, char in enumerate(click.__name__))
        successes = 0
        failures = 0
        returned_bytes = 0

        for index in range(len(click.__name__) ** 2 + 257):
            state = (state * 127 + index * index * 31 + (state >> 5)) % 104729
            size = 2 * ((state + index * 43) % 89)
            payload = bytearray(
                (state + offset * offset * 3 + index * 19) % 251
                for offset in range(size)
            )

            try:
                result = reader.readinto(payload)
            except OSError:
                failures += 1
            else:
                successes += 1
                returned_bytes += result
                self.assertEqual(result % 2, 0)
                self.assertLessEqual(result, len(payload))

        self.assertGreater(successes, failures)
        self.assertGreater(failures, 0)
        self.assertGreater(returned_bytes, successes)