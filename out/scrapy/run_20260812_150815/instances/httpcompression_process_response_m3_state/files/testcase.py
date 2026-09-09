import gzip
import random
import unittest
import zlib

from scrapy import Request
from scrapy.downloadermiddlewares.httpcompression import HttpCompressionMiddleware
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Response


class _CountingStats:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def inc_value(self, key: str, count: int = 1, **kwargs) -> None:
        self.values[key] = self.values.get(key, 0) + count


class HttpCompressionProcessResponseStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.middleware = object.__new__(HttpCompressionMiddleware)
        self.middleware.stats = _CountingStats()
        self.middleware._max_size = 1 << 20
        self.middleware._warn_size = 1 << 19

    @staticmethod
    def _payload(seed: int, size: int, binary: bool = False) -> bytes:
        generator = random.Random((seed * 65537) ^ (size * 8191))
        if binary:
            return bytes(generator.randrange(1, 256) for _ in range(size))
        alphabet = b"abcdefghijkmnpqrstuvwxyz23456789"
        return bytes(alphabet[generator.randrange(len(alphabet))] for _ in range(size))

    @staticmethod
    def _encoded(raw: bytes, encodings: list[bytes]) -> bytes:
        body = raw
        for encoding in encodings:
            normalized = encoding.strip().lower()
            if normalized in {b"gzip", b"x-gzip"}:
                body = gzip.compress(body, mtime=0)
            elif normalized == b"deflate":
                body = zlib.compress(body)
        return body

    def _run_success_series(
        self,
        *,
        seed: int,
        count: int,
        encoding_factory,
        content_type: bytes,
        binary: bool = False,
        warning_mode: bool = False,
        without_stats: bool = False,
    ) -> None:
        if without_stats:
            self.middleware.stats = None
        checksum = 0
        for index in range(count):
            raw = self._payload(seed + index * 17, 19 + (index * 13) % 47, binary)
            encodings = encoding_factory(index)
            body = self._encoded(raw, encodings)
            headers = {b"Content-Type": content_type}
            if encodings:
                headers[b"Content-Encoding"] = b", ".join(encodings)
            meta = {}
            if warning_mode:
                meta["download_warnsize"] = 3 + (index % 5)
            request = Request(
                f"https://example.invalid/{seed:x}/{index:x}",
                meta=meta,
            )
            response = Response(
                request.url,
                status=200 + index % 7,
                headers=headers,
                body=body,
                request=request,
            )
            result = self.middleware.process_response(request, response)
            self.assertIsInstance(result, Response)
            self.assertEqual(result.url, request.url)
            if not encodings or encodings[-1].strip().lower() in {
                b"gzip",
                b"x-gzip",
                b"deflate",
            }:
                self.assertEqual(result.body, raw)
            else:
                self.assertEqual(result.body, body)
            checksum ^= len(result.body) * (index + 3) + result.status
        self.assertGreater(count, 14)
        self.assertNotEqual(checksum, 0)

    def test_01_gzip_text_series(self) -> None:
        self._run_success_series(
            seed=101,
            count=17,
            encoding_factory=lambda index: [b"gzip"],
            content_type=b"text/plain",
        )

    def test_02_deflate_text_series(self) -> None:
        self._run_success_series(
            seed=211,
            count=18,
            encoding_factory=lambda index: [b"deflate"],
            content_type=b"text/csv",
        )

    def test_03_xgzip_text_series(self) -> None:
        self._run_success_series(
            seed=307,
            count=19,
            encoding_factory=lambda index: [b"x-gzip"],
            content_type=b"application/json",
        )

    def test_04_stacked_known_encodings(self) -> None:
        self._run_success_series(
            seed=401,
            count=20,
            encoding_factory=lambda index: (
                [b"gzip", b"deflate"] if index % 2 else [b"deflate", b"gzip"]
            ),
            content_type=b"text/html",
        )

    def test_05_decode_until_unknown_encoding(self) -> None:
        self._run_success_series(
            seed=503,
            count=17,
            encoding_factory=lambda index: [
                f"vendor-{(index * 31337 + 97):x}".encode(),
                b"gzip",
            ],
            content_type=b"text/plain",
        )

    def test_06_unknown_encoding_blocks_decode(self) -> None:
        self._run_success_series(
            seed=601,
            count=18,
            encoding_factory=lambda index: [
                b"gzip",
                f"opaque-{(index * 104729 + 193):x}".encode(),
            ],
            content_type=b"application/octet-stream",
            binary=True,
        )

    def test_07_gzip_binary_responses(self) -> None:
        self._run_success_series(
            seed=701,
            count=21,
            encoding_factory=lambda index: [b"gzip"],
            content_type=b"application/octet-stream",
            binary=True,
        )

    def test_08_warning_threshold_crossings(self) -> None:
        self._run_success_series(
            seed=809,
            count=16,
            encoding_factory=lambda index: [b"deflate"],
            content_type=b"text/plain",
            warning_mode=True,
        )

    def test_09_without_stats_collector(self) -> None:
        self._run_success_series(
            seed=907,
            count=17,
            encoding_factory=lambda index: [b"gzip" if index % 3 else b"deflate"],
            content_type=b"text/xml",
            without_stats=True,
        )

    def test_10_unencoded_responses(self) -> None:
        self._run_success_series(
            seed=1009,
            count=22,
            encoding_factory=lambda index: [],
            content_type=b"text/plain",
        )

    def test_11_head_responses_bypass_decoding(self) -> None:
        checksum = 0
        for index in range(15):
            raw = self._payload(1103 + index * 23, 31 + index)
            body = self._encoded(raw, [b"gzip"])
            request = Request(
                f"https://example.invalid/head/{index:x}",
                method="HEAD",
            )
            response = Response(
                request.url,
                headers={
                    b"Content-Type": b"text/plain",
                    b"Content-Encoding": b"gzip",
                },
                body=body,
                request=request,
            )
            result = self.middleware.process_response(request, response)
            self.assertIs(result, response)
            checksum ^= len(result.body) * (index + 5)
        self.assertNotEqual(checksum, 0)

    def test_12_decompression_size_failures(self) -> None:
        caught = 0
        for index in range(15):
            raw = self._payload(1201 + index * 29, 96 + index * 7)
            body = self._encoded(raw, [b"gzip"])
            request = Request(
                f"https://example.invalid/limit/{index:x}",
                meta={"download_maxsize": 11 + index % 4},
            )
            response = Response(
                request.url,
                headers={
                    b"Content-Type": b"text/plain",
                    b"Content-Encoding": b"gzip",
                },
                body=body,
                request=request,
            )
            with self.assertRaises(IgnoreRequest):
                self.middleware.process_response(request, response)
            caught += bool(body)
        self.assertGreater(caught, 14)
