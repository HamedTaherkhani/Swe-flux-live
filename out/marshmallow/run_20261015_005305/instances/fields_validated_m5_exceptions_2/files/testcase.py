import random
import unittest
import uuid

from marshmallow import fields


class NoisyText(str):
    """A str whose ``replace`` misbehaves for some instances."""

    def replace(self, old, new, *args):
        table = {}
        try:
            return table[old]
        except LookupError:
            pass
        if self.count("q") % 2:
            return {}[old]
        return str.replace(self, old, new, *args)


HEX = "0123456789abcdef"


def _hex(rng, n):
    return "".join(rng.choice(HEX) for _ in range(n))


def _dashed(h):
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _junk(rng, n):
    alphabet = HEX + "gqz-{}"
    return "".join(rng.choice(alphabet) for _ in range(n))


def _drive(values):
    field = fields.UUID()
    ok, bad = [], 0
    for v in values:
        try:
            ok.append(field._validated(v))
        except Exception:  # noqa: BLE001
            bad += 1
    return ok, bad


class TestUUIDValidated(unittest.TestCase):
    def test_canonical_strings(self):
        rng = random.Random(11)
        vals = [_dashed(_hex(rng, 32)) for _ in range(18)]
        ok, bad = _drive(vals)
        self.assertEqual(bad, 0)
        self.assertTrue(all(isinstance(u, uuid.UUID) for u in ok))

    def test_mixed_wrappers(self):
        rng = random.Random(12)
        vals = []
        for i in range(20):
            h = _hex(rng, 32)
            k = rng.randrange(5)
            if k == 0:
                vals.append("{" + h + "}")
            elif k == 1:
                vals.append("urn:uuid:" + _dashed(h))
            elif k == 2:
                vals.append(h[: 28 + rng.randrange(8)])
            elif k == 3:
                vals.append(uuid.UUID(h))
            else:
                vals.append(h.upper())
        ok, bad = _drive(vals)
        self.assertEqual(len(ok) + bad, len(vals))

    def test_random_lengths(self):
        rng = random.Random(13)
        vals = [_hex(rng, rng.randint(26, 36)) for _ in range(22)]
        ok, bad = _drive(vals)
        self.assertEqual(len(ok) + bad, len(vals))

    def test_junk_alphabet(self):
        rng = random.Random(14)
        vals = [_junk(rng, 32) for _ in range(16)]
        ok, bad = _drive(vals)
        self.assertEqual(len(ok) + bad, len(vals))

    def test_raw_bytes(self):
        rng = random.Random(15)
        vals = [bytes(rng.randrange(256) for _ in range(rng.choice([15, 16, 16, 17, 32])))
                for _ in range(17)]
        ok, bad = _drive(vals)
        self.assertEqual(len(ok) + bad, len(vals))

    def test_numbers(self):
        rng = random.Random(16)
        vals = []
        for _ in range(15):
            r = rng.random()
            if r < 0.4:
                vals.append(rng.getrandbits(100))
            elif r < 0.7:
                vals.append(rng.random() * 1000)
            elif r < 0.85:
                vals.append(uuid.UUID(int=rng.getrandbits(128)))
            else:
                vals.append(None)
        ok, bad = _drive(vals)
        self.assertGreater(bad, 0)

    def test_containers(self):
        rng = random.Random(17)
        vals = []
        for i in range(14):
            h = _hex(rng, 32)
            m = i % 4
            if m == 0:
                vals.append([h])
            elif m == 1:
                vals.append(bytearray(h[:16], "ascii"))
            elif m == 2:
                vals.append({"hex": h})
            else:
                vals.append(h)
        ok, bad = _drive(vals)
        self.assertEqual(len(ok) + bad, len(vals))

    def test_noisy_text(self):
        rng = random.Random(18)
        vals = [NoisyText(_junk(rng, rng.choice([31, 32, 32, 33]))) for _ in range(19)]
        ok, bad = _drive(vals)
        self.assertEqual(len(ok) + bad, len(vals))

    def test_none_and_empty(self):
        rng = random.Random(19)
        pool = [None, "", b"", "-" * 32, "{}", "urn:uuid:"]
        vals = [pool[rng.randrange(len(pool))] for _ in range(15)]
        ok, bad = _drive(vals)
        self.assertEqual(ok, [])

    def test_bytes_from_uuids(self):
        rng = random.Random(20)
        vals = []
        for _ in range(16):
            u = uuid.UUID(int=rng.getrandbits(128))
            vals.append(u.bytes if rng.random() < 0.6 else u.bytes_le[: rng.randint(10, 16)])
        ok, bad = _drive(vals)
        self.assertEqual(len(ok) + bad, len(vals))

    def test_chained_roundtrip(self):
        rng = random.Random(21)
        seed = uuid.UUID(int=rng.getrandbits(128))
        vals = []
        cur = str(seed)
        for _ in range(18):
            cut = rng.randrange(len(cur) + 1)
            cur = cur[:cut] + rng.choice(["", "-", "q", "0", "x"]) + cur[cut:]
            vals.append(NoisyText(cur) if rng.random() < 0.3 else cur)
        ok, bad = _drive(vals)
        self.assertEqual(len(ok) + bad, len(vals))

    def test_identity_passthrough(self):
        rng = random.Random(22)
        objs = [uuid.UUID(int=rng.getrandbits(128), version=4) for _ in range(15)]
        ok, bad = _drive(objs)
        self.assertEqual(bad, 0)
        self.assertTrue(all(a is b for a, b in zip(ok, objs)))
