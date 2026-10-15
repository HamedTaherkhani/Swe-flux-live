"""Drive ``_LimitedStream.readinto`` directly over many stream flavours."""

import io
import os
import random
import tempfile
import unittest
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from werkzeug.wsgi import LimitedStream


def _payload(rng, n, high_ratio=0.0):
    out = bytearray()
    for _ in range(n):
        if rng.random() < high_ratio:
            out.append(rng.randrange(128, 256))
        else:
            out.append(rng.randrange(32, 127))
    return bytes(out)


class AsciiOnlyReader:
    """WSGI-style input exposing only ``read``; rejects non-ASCII chunks."""

    def __init__(self, data):
        self._data = data
        self._pos = 0

    def read(self, n):
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk.decode("ascii").encode("ascii")


class GuardedReader:
    """``read``-only input that tolerates a lookup miss internally."""

    def __init__(self, data, table):
        self._data = data
        self._pos = 0
        self._table = table

    def read(self, n):
        try:
            n = self._table[n]
        except KeyError:
            pass
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


def _drive(test, stream, sizes):
    """Call readinto once per size, recording outcomes generically."""
    outcomes = []
    for size in sizes:
        buf = bytearray(size)
        try:
            got = stream.readinto(buf)
        except Exception as e:  # noqa: BLE001
            outcomes.append(("err", e))
        else:
            test.assertLessEqual(got, size)
            outcomes.append(("ok", got))
    return outcomes


def _errors(outcomes):
    return sum(1 for kind, _ in outcomes if kind == "err")


class LimitedStreamReadintoTest(unittest.TestCase):
    def test_clean_drain(self):
        rng = random.Random(101)
        data = _payload(rng, 317)
        ls = LimitedStream(io.BytesIO(data), len(data))
        collected = bytearray()
        while not ls.is_exhausted:
            buf = bytearray(rng.randint(1, 41))
            got = ls.readinto(buf)
            collected += buf[:got]
        self.assertEqual(bytes(collected), data)

    def test_max_overrun(self):
        rng = random.Random(202)
        data = _payload(rng, 400)
        limit = 9 * 13
        ls = LimitedStream(io.BytesIO(data), limit, is_max=True)
        sizes = [rng.randint(3, 19) for _ in range(23)]
        out = _drive(self, ls, sizes)
        self.assertEqual(sum(v for k, v in out if k == "ok"), limit)
        self.assertGreater(_errors(out), 0)

    def test_short_body_disconnect(self):
        rng = random.Random(303)
        data = _payload(rng, rng.randint(60, 90))
        ls = LimitedStream(io.BytesIO(data), len(data) + 50)
        sizes = [rng.randint(4, 12) for _ in range(17)]
        out = _drive(self, ls, sizes)
        self.assertGreater(_errors(out), 0)
        self.assertEqual(sum(v for k, v in out if k == "ok"), len(data))

    def test_short_body_max_quiet(self):
        rng = random.Random(404)
        data = _payload(rng, rng.randint(40, 70))
        ls = LimitedStream(io.BytesIO(data), len(data) * 2, is_max=True)
        sizes = [rng.randint(5, 15) for _ in range(16)]
        out = _drive(self, ls, sizes)
        self.assertEqual(_errors(out), 0)

    def test_closed_inputs(self):
        rng = random.Random(505)
        failures = 0
        for i in range(18):
            src = io.BytesIO(_payload(rng, 30))
            if rng.random() < 0.45:
                src.close()
            ls = LimitedStream(src, rng.choice([10, 20, 30]))
            out = _drive(self, ls, [rng.randint(5, 25) for _ in range(2)])
            failures += _errors(out)
        self.assertGreater(failures, 0)

    def test_ascii_reader(self):
        rng = random.Random(606)
        data = _payload(rng, 220, high_ratio=0.03)
        ls = LimitedStream(AsciiOnlyReader(data), 240)
        sizes = [rng.randint(6, 24) for _ in range(22)]
        out = _drive(self, ls, sizes)
        self.assertGreater(_errors(out), 0)

    def test_write_only_file(self):
        rng = random.Random(707)
        failures = 0
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sink.bin")
            with open(path, "wb") as fh:
                for _ in range(11):
                    limit = rng.choice([0, 0, 8, 16])
                    ls = LimitedStream(fh, limit, is_max=rng.random() < 0.5)
                    out = _drive(self, ls, [rng.randint(4, 20)])
                    failures += _errors(out)
        self.assertGreater(failures, 0)

    def test_bad_descriptor(self):
        rng = random.Random(808)
        failures = 0
        for _ in range(7):
            r, w = os.pipe()
            os.close(w)
            raw = io.FileIO(r, "rb", closefd=False)
            os.close(r)
            ls = LimitedStream(raw, rng.randint(5, 50), is_max=rng.random() < 0.5)
            out = _drive(self, ls, [rng.randint(1, 60)])
            failures += _errors(out)
            raw.close()
        self.assertGreater(failures, 0)

    def test_pipe_partial(self):
        rng = random.Random(909)
        data = _payload(rng, 75)
        r, w = os.pipe()
        os.write(w, data)
        os.close(w)
        with io.FileIO(r, "rb") as raw:
            ls = LimitedStream(raw, 100)
            sizes = [rng.randint(8, 30) for _ in range(12)]
            out = _drive(self, ls, sizes)
        self.assertGreater(_errors(out), 0)

    def test_temp_buffer_path(self):
        rng = random.Random(1010)
        data = _payload(rng, 500)
        ls = LimitedStream(io.BytesIO(data), 133)
        sizes = [rng.randint(20, 70) for _ in range(14)]
        out = _drive(self, ls, sizes)
        self.assertEqual(_errors(out), 0)
        self.assertTrue(ls.is_exhausted)

    def test_guarded_reader(self):
        rng = random.Random(1111)
        data = _payload(rng, 150)
        table = {k: k // 2 for k in range(0, 40, 3)}
        ls = LimitedStream(GuardedReader(data, table), 180, is_max=rng.random() < 0.5)
        sizes = [rng.randint(2, 30) for _ in range(19)]
        out = _drive(self, ls, sizes)
        self.assertGreaterEqual(len(out), 19)

    def test_mixed_rotation(self):
        rng = random.Random(1212)
        failures = 0
        for i in range(26):
            kind = rng.randrange(4)
            is_max = rng.random() < 0.5
            if kind == 0:
                src = io.BytesIO(_payload(rng, rng.randint(0, 12)))
            elif kind == 1:
                src = io.BytesIO(b"x")
                src.close()
            elif kind == 2:
                src = AsciiOnlyReader(_payload(rng, 16, high_ratio=0.2))
            else:
                src = GuardedReader(_payload(rng, rng.randint(0, 8)), {})
            ls = LimitedStream(src, rng.randint(0, 12), is_max=is_max)
            out = _drive(self, ls, [rng.randint(1, 10) for _ in range(3)])
            failures += _errors(out)
        self.assertGreater(failures, 0)


if __name__ == "__main__":
    unittest.main()
