from __future__ import annotations

import random
import unittest
from socket import gaierror

from scrapy import Request
from scrapy.core.downloader.handlers._httpx import (
    DOWNLOAD_FAILED_EXCEPTIONS,
    HttpxDownloadHandler,
    httpx,
)
from scrapy.http import Headers


class _FailingStream:
    def __init__(self, exception: Exception, chained_dns_failure: bool) -> None:
        self.exception = exception
        self.chained_dns_failure = chained_dns_failure

    async def __aenter__(self) -> None:
        if not self.chained_dns_failure:
            raise self.exception
        try:
            host_size = sum((value * 7 + 3) % 19 for value in range(23))
            raise gaierror(host_size, f"generated-host-{host_size:x}")
        except gaierror as cause:
            raise self.exception from cause

    async def __aexit__(self, *args: object) -> None:
        return None


class _Client:
    def __init__(self, exception: Exception, chained_dns_failure: bool) -> None:
        self.exception = exception
        self.chained_dns_failure = chained_dns_failure

    def stream(self, *args: object, **kwargs: object) -> _FailingStream:
        if len(args) < 2 or not kwargs.get("headers"):
            raise AssertionError("request arguments were not assembled")
        return _FailingStream(self.exception, self.chained_dns_failure)


class TestHttpxMakeRequestExceptions(unittest.IsolatedAsyncioTestCase):
    async def test_generated_failure_matrix(self) -> None:
        handler = object.__new__(HttpxDownloadHandler)
        handler._extract_proxy_url_with_creds = lambda request: None
        handler._request_headers = lambda request: Headers(
            {
                b"X-Probe": str(
                    sum((byte + index) % 31 for index, byte in enumerate(request.url.encode()))
                )
            }
        )

        timeout_kinds = sorted(
            httpx.TimeoutException.__subclasses__(),
            key=lambda exception_class: exception_class.__name__,
        )
        failure_kinds = [
            *timeout_kinds,
            httpx.UnsupportedProtocol,
            httpx.ConnectError,
            httpx.ProxyError,
            *DOWNLOAD_FAILED_EXCEPTIONS[:2],
        ]
        plan = [
            (exception_class, round_index)
            for round_index in range(3)
            for exception_class in failure_kinds
        ]
        random.Random(sum(value * value + 11 for value in range(29))).shuffle(plan)

        observed: list[tuple[Exception, Exception]] = []
        for index, (exception_class, round_index) in enumerate(plan):
            token = sum(
                (value * (index + 5) + round_index * 13) % 97
                for value in range(17 + index % 11)
            )
            source_exception = exception_class(
                f"transport-{token:x}-{(token * token + index * 41):x}"
            )
            chained_dns_failure = (
                exception_class is httpx.ConnectError and (token + index) % 2 == 0
            )
            client = _Client(source_exception, chained_dns_failure)
            handler._get_client = lambda proxy, selected=client: selected
            request = Request(
                "https://example.invalid/"
                + "".join(
                    chr(97 + (token + offset * 7 + index) % 26)
                    for offset in range(9 + index % 7)
                ),
                method=("POST" if (token ^ index) & 1 else "GET"),
                body=bytes((token + offset * 17) % 256 for offset in range(index % 13)),
            )
            timeout = (sum(divmod(token + index, 17)) + 1) / 7

            try:
                async with handler._make_request(request, timeout):
                    self.fail("the generated stream unexpectedly entered")
            except Exception as propagated:
                observed.append((source_exception, propagated))

        self.assertEqual(len(observed), len(plan))
        self.assertTrue(all(source is not propagated for source, propagated in observed))
