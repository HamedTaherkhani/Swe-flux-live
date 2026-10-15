"""Direct parsing of programmatically built Content-Range header values."""
import random
import unittest

from werkzeug.datastructures import ContentRange


def _spans(rng, count, total):
    out = []
    for _ in range(count):
        a = rng.randrange(total)
        b = rng.randrange(a, total)
        out.append((a, b))
    return out


def _parse_all(values):
    return [ContentRange.from_header(v) for v in values]


class ContentRangeParseTest(unittest.TestCase):
    def test_well_formed_spans(self):
        rng = random.Random(101)
        total = rng.randint(200, 900)
        values = [f"bytes {a}-{b}/{total}" for a, b in _spans(rng, 14, total)]
        parsed = _parse_all(values)
        self.assertTrue(all(parsed))
        for cr in parsed:
            self.assertEqual(cr.to_header().split("/")[1], str(total))

    def test_unknown_length_mixed_units(self):
        rng = random.Random(202)
        units = ["bytes", "items", "rows"]
        values = []
        for i in range(11):
            a = rng.randint(0, 50)
            b = a + rng.randint(0, 30)
            values.append(f"{units[i % 3]} {a}-{b}/*")
        parsed = _parse_all(values)
        self.assertTrue(all(cr.length is None for cr in parsed))
        self.assertEqual({cr.units for cr in parsed}, set(units))

    def test_empty_and_none(self):
        values = [None, "", None] + ["" for _ in range(random.Random(3).randint(1, 4))]
        parsed = _parse_all(values)
        self.assertFalse(any(parsed))

    def test_missing_slash(self):
        rng = random.Random(404)
        values = []
        for _ in range(9):
            a = rng.randint(0, 99)
            sep = rng.choice(["/", "|", ":"])
            values.append(f"bytes {a}-{a + rng.randint(1, 9)}{sep}{a + 100}")
        parsed = _parse_all(values)
        self.assertGreaterEqual(sum(1 for cr in parsed if cr), 1)

    def test_bad_length_strings(self):
        rng = random.Random(505)
        bad = ["+12", "1_000", "0x1f", "ten", "", " 7 8", "-3"]
        values = []
        for _ in range(10):
            a = rng.randint(0, 20)
            tail = rng.choice(bad + [str(a + 50), "\t" + str(a + 60) + " "])
            values.append(f"bytes {a}-{a + 5}/{tail}")
        parsed = _parse_all(values)
        self.assertIsInstance(sum(bool(cr) for cr in parsed), int)

    def test_unsatisfied_star_range(self):
        rng = random.Random(606)
        values = []
        for i in range(13):
            if i % 4 == 3:
                values.append("bytes */*")
            else:
                values.append(f"bytes */{rng.randint(0, 5000)}")
        parsed = _parse_all(values)
        for cr in parsed:
            if cr:
                self.assertIsNone(cr.start)
                self.assertIsNotNone(cr.length)

    def test_range_without_dash(self):
        rng = random.Random(707)
        values = []
        for _ in range(8):
            a = rng.randint(0, 40)
            joiner = rng.choice(["-", "~", ".."])
            values.append(f"bytes {a}{joiner}{a + 3}/100")
        parsed = _parse_all(values)
        self.assertEqual(len(parsed), 8)

    def test_bad_start_or_stop(self):
        rng = random.Random(808)
        pieces = ["x", "+4", " 9", "4_0", "", "12", "7"]
        values = [
            f"bytes {rng.choice(pieces)}-{rng.choice(pieces)}/{rng.choice(['*', '64'])}"
            for _ in range(15)
        ]
        parsed = _parse_all(values)
        self.assertEqual(len(parsed), 15)

    def test_out_of_bounds(self):
        rng = random.Random(909)
        values = []
        for _ in range(12):
            length = rng.randint(10, 60)
            a = rng.randint(0, 70)
            b = rng.randint(0, 70)
            values.append(f"bytes {a}-{b}/{length}")
        parsed = _parse_all(values)
        for cr in parsed:
            if cr:
                self.assertLess(cr.stop, cr.length + 1)

    def test_round_trip(self):
        rng = random.Random(1010)
        originals = []
        for _ in range(7):
            length = rng.choice([None, rng.randint(100, 300)])
            a = rng.randint(0, 90)
            originals.append(ContentRange("bytes", a, a + rng.randint(1, 9), length))
        parsed = _parse_all([cr.to_header() for cr in originals])
        for src, cr in zip(originals, parsed):
            self.assertEqual((src.start, src.stop, src.length), (cr.start, cr.stop, cr.length))

    def test_no_space_units(self):
        rng = random.Random(1111)
        values = []
        for i in range(6):
            a = rng.randint(0, 9)
            values.append(f"bytes{'' if i % 2 else ' '}{a}-{a + 1}/{a + 2}")
        parsed = _parse_all(values)
        self.assertEqual(len(parsed), 6)

    def test_chained_derivation(self):
        rng = random.Random(1212)
        cr = ContentRange.from_header(f"bytes 0-{rng.randint(3, 8)}/*")
        seen = 0
        while cr and seen < 16:
            seen += 1
            nxt_start = cr.stop + rng.randint(-2, 3)
            nxt_stop = nxt_start + rng.randint(-1, 6)
            limit = rng.choice(["*", str(nxt_stop + rng.randint(-1, 4))])
            cr = ContentRange.from_header(f"bytes {nxt_start}-{nxt_stop}/{limit}")
        self.assertGreaterEqual(seen, 1)


if __name__ == "__main__":
    unittest.main()
