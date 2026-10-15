import datetime as dt
import random
import unittest
import warnings

from werkzeug.http import dump_cookie


def _build_specs(seed, count):
    rng = random.Random(seed)
    alphabet = "abcXYZ019-_.!" + ' ;,"\\' + "é€"
    specs = []
    for i in range(count):
        n = rng.randint(1, 12)
        value = "".join(rng.choice(alphabet) for _ in range(n))
        if rng.random() < 0.4:
            value = value.encode("ascii", "ignore").decode().replace(" ", "")
            value = "".join(c for c in value if c not in ';,"\\')
        kwargs = {"key": f"k{i}{rng.choice(['', 'id', 'sess'])}", "value": value}
        r = rng.random()
        if r < 0.3:
            kwargs["max_age"] = dt.timedelta(minutes=rng.randint(1, 90))
        elif r < 0.55:
            kwargs["max_age"] = rng.randint(0, 5000)
        r = rng.random()
        if r < 0.25:
            kwargs["expires"] = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(
                days=rng.randint(0, 900)
            )
        elif r < 0.4:
            kwargs["expires"] = rng.randint(10**9, 2 * 10**9)
        elif r < 0.5:
            kwargs["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        r = rng.random()
        if r < 0.2:
            kwargs["path"] = None
        elif r < 0.6:
            kwargs["path"] = "/" + "/".join(rng.choice(["a b", "x", "%7e", "q;r"]) for _ in range(rng.randint(1, 3)))
        r = rng.random()
        if r < 0.3:
            kwargs["domain"] = rng.choice([".example.org", "localhost:8080", "bücher.de", "Sub.Host.net"])
        elif r < 0.4:
            kwargs["domain"] = ""
        kwargs["secure"] = rng.random() < 0.3
        kwargs["httponly"] = rng.random() < 0.5
        kwargs["sync_expires"] = rng.random() < 0.7
        kwargs["max_size"] = rng.choice([4093, 0, 40, 60])
        r = rng.random()
        if r < 0.5:
            kwargs["samesite"] = rng.choice(["strict", "LAX", "none", "None", "loose"])
        kwargs["partitioned"] = rng.random() < 0.25
        specs.append(kwargs)
    return specs


class DumpCookieDataFlowTest(unittest.TestCase):
    def test_dump_cookie_batch(self):
        specs = _build_specs(20240607, 36)
        produced = 0
        rejected = 0
        oversized = 0
        for kwargs in specs:
            if kwargs.get("samesite", "strict").title() not in {"Strict", "Lax", "None"}:
                with self.assertRaises(ValueError):
                    dump_cookie(**kwargs)
                rejected += 1
                continue
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                header = dump_cookie(**kwargs)
            oversized += len(caught)
            produced += 1
            self.assertTrue(header.startswith(kwargs["key"] + "="))
            if kwargs["partitioned"]:
                self.assertIn("; Secure", header)
        self.assertEqual(produced + rejected, len(specs))
        self.assertGreater(rejected, 0)
        self.assertGreater(oversized, 0)
