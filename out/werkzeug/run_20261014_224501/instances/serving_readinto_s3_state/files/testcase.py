import io
import random
import unittest

from werkzeug.serving import DechunkedInput


def _build_stream(rng):
    """Build a chunked body from seeded random chunks; return (wire, payload)."""
    alphabet = b"abcdefghijklmnopqrstuvwxyz0123456789"
    wire = bytearray()
    payload = bytearray()
    for idx in range(48):
        size = rng.randint(1, 29) + (idx % 5) * 3
        header = format(size, "x")
        if rng.random() < 0.4:
            header = header.upper()
        header = "0" * rng.randint(0, 2) + header
        if rng.random() < 0.3:
            header = " " + header + "\t"
        data = bytes(rng.choice(alphabet) for _ in range(size))
        wire += header.encode("latin1") + b"\r\n" + data + (b"\r\n" if idx % 3 else b"\n")
        payload += data
    wire += b"0\r\n\r\n"
    return bytes(wire), bytes(payload)


class TestDechunkedReadinto(unittest.TestCase):
    def test_readinto_varied_buffers(self):
        rng = random.Random(3329)
        wire, payload = _build_stream(rng)
        stream = DechunkedInput(io.BytesIO(wire))

        sizes = [rng.randint(5, 60) for _ in range(3)]
        sizes.insert(2, sum(sizes) * 4 + rng.randint(0, 9))
        collected = bytearray()
        counts = []
        while True:
            size = sizes[len(counts) % len(sizes)]
            buf = bytearray(size)
            got = stream.readinto(buf)
            counts.append(got)
            if got == 0:
                break
            collected += buf[:got]

        self.assertEqual(bytes(collected), payload)
        self.assertEqual(sum(counts), len(payload))
        self.assertEqual(counts[-1], 0)
        self.assertGreater(len(counts), 6)
