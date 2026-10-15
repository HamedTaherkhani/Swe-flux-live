"""Range request handling driven through Request/Response wrappers."""
import random
import unittest

from werkzeug.datastructures import ETag
from werkzeug.exceptions import RequestedRangeNotSatisfiable
from werkzeug.test import create_environ
from werkzeug.wrappers import Request
from werkzeug.wrappers import Response


def _request(range_header=None, method="GET", **extra):
    headers = {}
    if range_header is not None:
        headers["Range"] = range_header
    headers.update(extra)
    return Request(create_environ("/f", method=method, headers=headers))


def _response(size, seed):
    rng = random.Random(seed)
    data = bytes(rng.randrange(256) for _ in range(size))
    resp = Response(data)
    resp.etag = ETag(f"tag{seed}")
    return resp


def _chain(rng, count, start, step_lo, step_hi):
    parts = []
    pos = start
    for _ in range(count):
        width = rng.randint(step_lo, step_hi)
        parts.append(f"{pos}-{pos + width}")
        pos += width + rng.randint(1, 3)
    return parts


class RangeRequestFlowTest(unittest.TestCase):
    def test_missing_header(self):
        resp = _response(40, 1)
        resp.apply_range(_request())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.accept_ranges, "bytes")
        resp = _response(40, 12)
        resp.status_code = 404
        resp.apply_range(_request("bytes=0-3"))
        self.assertEqual(resp.status_code, 404)
        req = _request(" BYTES\t= 5-9 , 12-")
        self.assertEqual(len(req.range.ranges), 2)

    def test_long_ascending_chain(self):
        rng = random.Random(11)
        header = "bytes=" + ",".join(_chain(rng, 17, 3, 1, 5))
        resp = _response(400, 2)
        resp.apply_range(_request(header))
        self.assertEqual(resp.status_code, 206)
        self.assertGreater(resp.content_length, 1)

    def test_chain_with_spaces_and_open_end(self):
        rng = random.Random(23)
        parts = _chain(rng, 9, 0, 2, 7)
        spaced = [(" " * (i % 3)) + p.replace("-", " - " if i % 2 else "-") for i, p in enumerate(parts)]
        last_end = int(parts[-1].split("-")[1])
        spaced.append(f"\t{last_end + 4}-")
        header = "Bytes =" + ",".join(spaced)
        resp = _response(300, 3)
        resp.apply_range(_request(header))
        self.assertEqual(resp.status_code, 206)

    def test_overlap_rejected(self):
        rng = random.Random(5)
        parts = _chain(rng, 12, 10, 3, 6)
        parts[8], parts[9] = parts[9], parts[8]
        resp = _response(200, 4)
        resp.apply_range(_request("bytes=" + ",".join(parts)))
        self.assertEqual(resp.status_code, 200)

    def test_non_bytes_units(self):
        rng = random.Random(7)
        header = "items=" + ",".join(_chain(rng, 6, 1, 1, 2))
        req = _request(header)
        resp = _response(50, 5)
        resp.apply_range(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(req.range.units[:2], "it")

    def test_suffix_after_ranges(self):
        rng = random.Random(31)
        parts = _chain(rng, 5, 2, 1, 3) + [f"-{rng.randint(4, 9)}"]
        resp = _response(120, 6)
        resp.apply_range(_request("bytes=" + ",".join(parts)))
        self.assertEqual(resp.status_code, 206)

    def test_range_after_suffix_rejected(self):
        rng = random.Random(41)
        parts = _chain(rng, 4, 0, 2, 4)
        parts.insert(2, "-15")
        req = _request("bytes=" + ",".join(parts))
        self.assertIsNone(req.range)
        self.assertIsNone(req.range)

    def test_zero_suffix_and_bad_suffix(self):
        req = _request("bytes=0-4,-0")
        self.assertIsNone(req.range)
        req = _request("bytes=-+3")
        self.assertIsNone(req.range)
        req = _request("bytes=-12")
        self.assertEqual(req.range.ranges[0][1], None)

    def test_item_without_dash(self):
        rng = random.Random(53)
        parts = _chain(rng, 7, 0, 1, 4)
        parts[5] = parts[5].replace("-", ":")
        resp = _response(90, 7)
        resp.apply_range(_request("bytes=" + ",".join(parts)))
        self.assertEqual(resp.status_code, 200)

    def test_bad_begin_and_reversed(self):
        rng = random.Random(61)
        good = _chain(rng, 3, 0, 1, 3)
        req = _request("bytes=" + ",".join(good + ["x5-9"]))
        self.assertIsNone(req.range)
        req = _request("bytes=" + ",".join(good + ["90-80"]))
        self.assertIsNone(req.range)

    def test_unsatisfiable(self):
        rng = random.Random(71)
        header = "bytes=" + ",".join(_chain(rng, 8, 500, 2, 9))
        resp = _response(64, 8)
        with self.assertRaises(RequestedRangeNotSatisfiable):
            resp.apply_range(_request(header))

    def test_if_range_mismatch_and_post(self):
        rng = random.Random(83)
        header = "bytes=" + ",".join(_chain(rng, 10, 1, 1, 6))
        resp = _response(150, 9)
        resp.apply_range(_request(header, **{"If-Range": '"other"'}))
        self.assertEqual(resp.status_code, 200)
        resp = _response(150, 10)
        resp.apply_range(_request(header, method="POST"))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(_request("bytes").range)
        self.assertIsNone(_request("").range)


if __name__ == "__main__":
    unittest.main()
