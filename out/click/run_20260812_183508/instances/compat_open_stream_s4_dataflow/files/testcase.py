import errno
import os
import tempfile
import unittest
from unittest import mock

from click import _compat


class TestOpenStreamDataFlow(unittest.TestCase):
    def test_generated_stream_matrix_and_atomic_retries(self):
        state = sum(ord(ch) * (index + 1) for index, ch in enumerate(__name__))

        def generated_words(count):
            nonlocal state
            words = []
            for index in range(count):
                state = (state * 1664525 + 1013904223 + index) & 0xFFFFFFFF
                words.append(format(state, "x"))
            return words

        with tempfile.TemporaryDirectory() as directory:
            pieces = generated_words(6)
            existing_path = os.path.join(directory, "-".join(pieces[:3]))
            absent_path = os.path.join(directory, "-".join(pieces[3:]))
            payload = bytes((ord(ch) + index) & 0xFF for index, ch in enumerate("stream"))
            with open(existing_path, "wb") as seed_file:
                seed_file.write(payload[::-1])

            dash = "".join(chr(code) for code in (45,))
            write_binary = "".join(("w", "b"))
            read_text = "".join(("r",))

            stdout_stream, close_stdout = _compat.open_stream(dash, write_binary)
            stdin_stream, close_stdin = _compat.open_stream(dash, read_text)
            plain_stream, close_plain = _compat.open_stream(existing_path, read_text)
            plain_stream.close()

            self.assertIsNotNone(stdout_stream)
            self.assertIsNotNone(stdin_stream)
            self.assertFalse(close_stdout or close_stdin)
            self.assertTrue(close_plain)

            invalid_modes = [
                "".join(chr(code) for code in codes)
                for codes in ((97,), (120,), (114,))
            ]
            for invalid_mode in invalid_modes:
                with self.assertRaises(ValueError):
                    _compat.open_stream(existing_path, invalid_mode, atomic=True)

            retry_budget = len(generated_words(9)) + len(pieces) + len(invalid_modes)
            random_values = [
                int(word[-8:], 16) for word in generated_words(retry_budget + 1)
            ]
            real_open = os.open
            attempts = 0

            def collision_then_open(path, flags, permissions):
                nonlocal attempts
                attempts += 1
                if attempts <= retry_budget:
                    raise OSError(errno.EEXIST, "generated collision", path)
                return real_open(path, flags, permissions)

            with mock.patch("random.randrange", side_effect=random_values), mock.patch(
                "os.open", side_effect=collision_then_open
            ):
                atomic_binary, close_atomic_binary = _compat.open_stream(
                    existing_path, write_binary, atomic=True
                )
                atomic_binary.write(payload)
                atomic_binary.close()

            second_values = [int(word[-8:], 16) for word in generated_words(4)]
            with mock.patch("random.randrange", side_effect=second_values):
                atomic_text, close_atomic_text = _compat.open_stream(
                    absent_path,
                    "".join(("w",)),
                    encoding="utf-8",
                    errors="replace",
                    atomic=True,
                )
                atomic_text.write("".join(reversed(pieces[0])))
                atomic_text.close()

            self.assertTrue(close_atomic_binary and close_atomic_text)
            self.assertEqual(attempts, retry_budget + 1)
            self.assertEqual(os.path.getsize(existing_path), len(payload))
            self.assertGreater(os.path.getsize(absent_path), 0)
