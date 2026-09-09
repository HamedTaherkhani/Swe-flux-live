import io
import unittest
from unittest import mock

from click import _compat


class _ReadableTextView:
    def __init__(self, buffer, encoding, errors):
        self.buffer = buffer
        self.encoding = encoding
        self.errors = errors

    def read(self, size=-1):
        return ""


class _WritableTextView:
    def __init__(self, buffer, encoding, errors):
        self.buffer = buffer
        self.encoding = encoding
        self.errors = errors

    def write(self, value):
        if isinstance(value, bytes):
            raise TypeError("text only")
        return len(value)


class TestGeneratedCompatibilityMatrix(unittest.TestCase):
    def _exercise(self, seed, rounds, route_bias):
        state = seed
        wrappers = []
        originals = []

        for index in range(rounds):
            state = (state * 157 + index * index * 31 + route_bias * 43) % 4093
            mode = (state ^ (state >> 3) ^ index ^ route_bias) % 10
            choose_stderr = ((state + index + route_bias) % 4) == 0

            if mode == 0:
                stream = io.BytesIO(bytes((state + offset) % 251 for offset in range(7)))
                encoding = None if state % 3 else "utf-8"
                errors = None if state % 2 else "strict"
                attribute = "stdin"
                entry = _compat.get_text_stdin
            elif mode == 1:
                stream = io.BytesIO()
                encoding = None if state % 4 else "latin-1"
                errors = None if state % 3 else "ignore"
                attribute = "stderr" if choose_stderr else "stdout"
                entry = (
                    _compat.get_text_stderr
                    if choose_stderr
                    else _compat.get_text_stdout
                )
            elif mode == 2:
                stream = _ReadableTextView(io.BytesIO(b"reader"), "utf-8", "strict")
                encoding = "utf-8"
                errors = "strict"
                attribute = "stdin"
                entry = _compat.get_text_stdin
            elif mode == 3:
                stream = _WritableTextView(io.BytesIO(), "utf-8", "strict")
                encoding = "utf-8"
                errors = "strict"
                attribute = "stderr" if choose_stderr else "stdout"
                entry = (
                    _compat.get_text_stderr
                    if choose_stderr
                    else _compat.get_text_stdout
                )
            elif mode == 4:
                stream = _ReadableTextView(io.BytesIO(b"ascii"), "ascii", "strict")
                encoding = None
                errors = None if state % 2 else "replace"
                attribute = "stdin"
                entry = _compat.get_text_stdin
            elif mode == 5:
                stream = _WritableTextView(io.BytesIO(), "utf-16", "strict")
                encoding = "utf-8"
                errors = None if state % 2 else "backslashreplace"
                attribute = "stderr" if choose_stderr else "stdout"
                entry = (
                    _compat.get_text_stderr
                    if choose_stderr
                    else _compat.get_text_stdout
                )
            elif mode == 6:
                stream = io.StringIO("unbuffered reader")
                encoding = "utf-8"
                errors = "strict"
                attribute = "stdin"
                entry = _compat.get_text_stdin
            elif mode == 7:
                stream = io.StringIO()
                encoding = "utf-8"
                errors = "strict"
                attribute = "stderr" if choose_stderr else "stdout"
                entry = (
                    _compat.get_text_stderr
                    if choose_stderr
                    else _compat.get_text_stdout
                )
            elif mode == 8:
                stream = _ReadableTextView(io.BytesIO(b"latin"), "latin-1", "strict")
                encoding = None
                errors = None
                attribute = "stdin"
                entry = _compat.get_text_stdin
            else:
                stream = _WritableTextView(io.BytesIO(), "ascii", "strict")
                encoding = "ascii"
                errors = "strict"
                attribute = "stderr" if choose_stderr else "stdout"
                entry = (
                    _compat.get_text_stderr
                    if choose_stderr
                    else _compat.get_text_stdout
                )

            originals.append(stream)
            with mock.patch.object(_compat.sys, attribute, stream):
                result = entry(encoding=encoding, errors=errors)

            self.assertTrue(hasattr(result, "encoding"))
            self.assertTrue(hasattr(result, "errors"))
            wrappers.append(result)

        self.assertEqual(len(wrappers), rounds)
        self.assertEqual(len(originals), rounds)
        self.assertTrue(any(left is right for left, right in zip(wrappers, originals)))
        self.assertTrue(any(left is not right for left, right in zip(wrappers, originals)))

    def test_ascii_recovery_mix(self):
        self._exercise(137, 23, 5)

    def test_binary_reader_mix(self):
        self._exercise(281, 29, 2)

    def test_binary_writer_mix(self):
        self._exercise(419, 31, 7)

    def test_compatible_reader_mix(self):
        self._exercise(563, 27, 3)

    def test_compatible_writer_mix(self):
        self._exercise(691, 34, 11)

    def test_default_encoding_mix(self):
        self._exercise(827, 26, 13)

    def test_detached_fallback_mix(self):
        self._exercise(953, 28, 17)

    def test_error_policy_mix(self):
        self._exercise(1091, 33, 19)

    def test_latin_reader_mix(self):
        self._exercise(1229, 25, 23)

    def test_stderr_route_mix(self):
        self._exercise(1367, 30, 29)

    def test_unbuffered_mix(self):
        self._exercise(1499, 32, 31)

    def test_wrapped_writer_mix(self):
        self._exercise(1637, 35, 37)
