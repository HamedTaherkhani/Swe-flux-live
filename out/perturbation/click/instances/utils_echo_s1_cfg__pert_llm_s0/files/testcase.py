from __future__ import annotations

import io
import random
import unittest

from click.utils import echo


class TextCapture(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()

    def isatty(self) -> bool:
        return False


class BinaryCapture(io.BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


class Renderable:
    def __init__(self, pieces: list[str]) -> None:
        self.pieces = pieces

    def __str__(self) -> str:
        return "\x1b[35m" + "".join(reversed(self.pieces)) + "\x1b[0m"


class EchoGeneratedControlFlow(unittest.TestCase):
    def test_seeded_message_and_stream_matrix(self) -> None:
        rng = random.Random(15673)
        tokens = [rng.getrandbits(16) for _ in range(200)]
        selectors = [
            (token ^ (index * index + 7 * index + 11)) % 6
            for index, token in enumerate(tokens)
        ]
        palette = [None, False, True, None, False, True]
        sinks: list[TextCapture | BinaryCapture] = []

        for index, (token, selector) in enumerate(zip(tokens, selectors)):
            nl = bool((token >> 2) & 1)
            color = palette[(token >> 2) % len(palette)]
            fragments = [
                chr(97 + ((token >> shift) + index) % 26)
                for shift in range(0, 30, 2)
            ]

            if selector == 0:
                message = bytes((ord(part) + index * 2) % 256 for part in fragments)
                sink: TextCapture | BinaryCapture = BinaryCapture()
            elif selector == 1:
                message = None
                nl = False
                sink = TextCapture()
            elif selector == 2:
                message = "\x1b[31m" + "".join(fragments) + "\x1b[0m"
                sink = TextCapture()
            elif selector == 3:
                message = bytearray(
                    (ord(part) ^ (token & 0xFF)) for part in fragments
                )
                sink = BinaryCapture()
            elif selector == 4:
                message = Renderable(fragments)
                sink = TextCapture()
            else:
                message = "".join(fragments) * (1 + token % 5)
                sink = TextCapture()

            echo(message=message, file=sink, nl=nl, color=color)
            sinks.append(sink)

        self.assertEqual(len(sinks), len(tokens))
        self.assertTrue(all(sink.flush_count >= 1 for sink in sinks))
        self.assertGreater(
            sum(len(sink.getvalue()) for sink in sinks),
            len(selectors),
        )