import random
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from werkzeug.http import http_date
from werkzeug.sansio.http import _is_resource_modified

SEED = 20241015
BASE = datetime(2023, 3, 14, 9, 26, 53, tzinfo=timezone.utc)


def _token(rng):
    return "".join(rng.choice("abcdef0123456789") for _ in range(rng.randint(3, 9)))


def build_requests(seed, count):
    rng = random.Random(seed)
    requests = []
    for _ in range(count):
        offset = timedelta(hours=rng.randint(-72, 72), microseconds=rng.randint(0, 999))
        kwargs = {
            "http_if_modified_since": http_date(BASE + timedelta(hours=rng.randint(-48, 48))),
            "last_modified": BASE + offset,
        }
        lm_roll = rng.random()
        if lm_roll < 0.25:
            kwargs["last_modified"] = http_date(kwargs["last_modified"])
        elif lm_roll < 0.31:
            kwargs["last_modified"] = kwargs["last_modified"].date()

        etag_roll = rng.random()
        if etag_roll < 0.35:
            kwargs["etag"] = _token(rng)
        elif etag_roll < 0.5:
            kwargs["etag"] = ""
        elif etag_roll < 0.56:
            kwargs["etag"] = f'"{_token(rng)}"'
        elif etag_roll < 0.62:
            kwargs["etag"] = f'W/{_token(rng)}'

        data_roll = rng.random()
        if data_roll < 0.04:
            kwargs["data"] = _token(rng).encode()
        elif data_roll < 0.07:
            kwargs["data"] = _token(rng)
        elif data_roll < 0.10:
            kwargs["data"] = bytearray(_token(rng), "ascii")

        if rng.random() < 0.08:
            kwargs["ignore_if_range"] = False
            kwargs["http_range"] = f"bytes=0-{rng.randint(10, 999)}"
            kwargs["http_if_range"] = http_date(BASE)
        elif rng.random() < 0.5:
            kwargs["http_range"] = "bytes=0-499"
            kwargs["http_if_range"] = f'"{_token(rng)}"'

        if rng.random() < 0.4:
            kwargs["http_if_none_match"] = f'"{_token(rng)}", W/"{_token(rng)}"'
        requests.append(kwargs)
    return requests


class IsResourceModifiedBatchTest(unittest.TestCase):
    def test_conditional_batch(self):
        requests = build_requests(SEED, 48)
        returned = []
        failed = []
        for index, kwargs in enumerate(requests):
            try:
                result = _is_resource_modified(**kwargs)
            except Exception as exc:  # outcome bookkeeping only
                failed.append((index, exc))
            else:
                self.assertIsInstance(result, bool)
                returned.append((index, result))

        self.assertEqual(len(returned) + len(failed), len(requests))
        self.assertGreater(len(returned), 10)
        self.assertGreater(len(failed), 0)
        self.assertIn(True, [r for _, r in returned])
        self.assertIn(False, [r for _, r in returned])


if __name__ == "__main__":
    unittest.main()
