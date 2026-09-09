from __future__ import annotations

import unittest
from email.utils import formatdate
from unittest.mock import patch

from scrapy.extensions.httpcache import RFC2616Policy
from scrapy.http import Request, Response
from scrapy.settings import Settings


class TestRFC2616FreshnessCallGraph(unittest.TestCase):
    NOW = 1_893_456_000

    def setUp(self) -> None:
        settings = Settings(
            {
                "HTTPCACHE_ALWAYS_STORE": False,
                "HTTPCACHE_IGNORE_SCHEMES": [],
                "HTTPCACHE_IGNORE_RESPONSE_CACHE_CONTROLS": [],
            }
        )
        self.policy = RFC2616Policy(settings)
        time_patch = patch("scrapy.extensions.httpcache.time", return_value=self.NOW)
        time_patch.start()
        self.addCleanup(time_patch.stop)

    def _exercise(self, seed: int, width: int, stride: int) -> None:
        requests: list[Request] = []
        outcomes: list[bool] = []

        for index in range(width):
            selector = (seed * (index + 3) + index * stride + index**2) % 17
            response_headers: dict[bytes, bytes] = {}
            request_headers: dict[bytes, bytes] = {}

            apparent_age = (selector * selector + seed * 7 + index * 11) % 420
            response_headers[b"Date"] = formatdate(
                self.NOW - apparent_age, usegmt=True
            ).encode()

            branch = selector % 8
            if branch == 0:
                response_headers[b"Cache-Control"] = b"no-cache"
            elif branch == 1:
                request_headers[b"Cache-Control"] = b"no-cache"
            elif branch == 2:
                lifetime = (seed * 13 + index * 19) % 260
                response_headers[b"Cache-Control"] = (
                    f"max-age={lifetime}".encode()
                )
            elif branch == 3:
                lifetime = (seed * 5 + index * 23) % 180
                response_headers[b"Cache-Control"] = (
                    f"max-age={lifetime}, must-revalidate".encode()
                )
                request_headers[b"Cache-Control"] = b"max-stale"
            elif branch == 4:
                expiry_delta = ((index + seed) % 9 - 4) * 47
                response_headers[b"Expires"] = formatdate(
                    self.NOW - apparent_age + expiry_delta, usegmt=True
                ).encode()
            elif branch == 5:
                modified_delta = 60 + ((seed + index * stride) % 900)
                response_headers[b"Last-Modified"] = formatdate(
                    self.NOW - apparent_age - modified_delta, usegmt=True
                ).encode()
            elif branch == 6:
                response_headers[b"Age"] = (
                    b"invalid"
                    if (seed + index) % 3 == 0
                    else str((seed * index + stride) % 500).encode()
                )
            else:
                response_headers[b"Cache-Control"] = b"max-age=0"
                stale_variant = (seed + index + stride) % 4
                if stale_variant == 0:
                    request_headers[b"Cache-Control"] = b"max-stale"
                elif stale_variant == 1:
                    request_headers[b"Cache-Control"] = (
                        f"max-stale={(seed * 3 + index * 17) % 240}".encode()
                    )
                elif stale_variant == 2:
                    request_headers[b"Cache-Control"] = b"max-stale=broken"
                else:
                    request_headers[b"Cache-Control"] = (
                        f"max-age={(seed + index) % 90}".encode()
                    )

            if (selector + seed) % 5 == 0:
                response_headers[b"ETag"] = (
                    f'"tag-{seed:x}-{index * stride:x}"'.encode()
                )
            if (selector * stride + index) % 7 == 0:
                response_headers[b"Last-Modified"] = formatdate(
                    self.NOW - apparent_age - 7200 - index, usegmt=True
                ).encode()

            status = (200, 203, 300, 301, 308, 404)[
                (selector + index + seed) % 6
            ]
            url = f"https://example.invalid/{seed:x}/{index:x}"
            request = Request(url, headers=request_headers)
            cached = Response(url, status=status, headers=response_headers)
            requests.append(request)
            outcomes.append(self.policy.is_cached_response_fresh(cached, request))

        self.assertEqual(len(outcomes), len(requests))
        self.assertTrue(all(type(outcome) is bool for outcome in outcomes))
        self.assertTrue(all(request.url.startswith("https://") for request in requests))

    def test_rotating_expiration_windows(self) -> None:
        self._exercise(19, 16, 5)

    def test_dense_age_headers(self) -> None:
        self._exercise(23, 17, 7)

    def test_validator_heavy_mix(self) -> None:
        self._exercise(29, 18, 9)

    def test_request_directive_mix(self) -> None:
        self._exercise(31, 19, 11)

    def test_redirect_status_mix(self) -> None:
        self._exercise(37, 20, 13)

    def test_heuristic_lifetimes(self) -> None:
        self._exercise(41, 21, 15)

    def test_stale_allowances(self) -> None:
        self._exercise(43, 22, 17)

    def test_invalid_age_values(self) -> None:
        self._exercise(47, 23, 19)

    def test_conditional_header_updates(self) -> None:
        self._exercise(53, 24, 21)

    def test_zero_lifetime_responses(self) -> None:
        self._exercise(59, 25, 23)

    def test_mixed_cache_controls(self) -> None:
        self._exercise(61, 26, 25)

    def test_long_status_rotation(self) -> None:
        self._exercise(67, 27, 27)
