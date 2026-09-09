import hashlib
import random
import unittest

from scrapy import Request
from scrapy.utils.request import fingerprint


class TestRequestFingerprintProgramState(unittest.TestCase):
    def test_accumulated_header_state(self):
        rng = random.Random(8675309)
        indices = list(range(29))
        rng.shuffle(indices)

        header_names = [f"X{i:02X}" for i in indices]
        request_headers = {
            name: bytes([(i * i + rng.randrange(1, 241)) % 251])
            for name, i in zip(header_names, indices, strict=True)
            if (i * i + 5 * i + 3) % 7 not in {0, 2}
        }
        query_parts = [
            f"k{(i * 11) % 17}={(i * i * 13 + 7) % 997}" for i in indices
        ]
        request = Request(
            "https://example.invalid/items?" + "&".join(query_parts),
            method="POST",
            body=bytes((i * 19 + 5) % 256 for i in indices),
            headers=request_headers,
        )

        digest = fingerprint(request, include_headers=header_names)

        self.assertIsInstance(digest, bytes)
        self.assertEqual(len(digest), hashlib.sha1().digest_size)
        self.assertGreater(len(request.headers), len(indices) // 2)
