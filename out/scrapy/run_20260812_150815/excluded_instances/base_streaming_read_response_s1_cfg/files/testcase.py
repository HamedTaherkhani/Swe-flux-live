from __future__ import annotations

import random
import unittest
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace

from scrapy import Request
from scrapy.core.downloader.handlers._base_streaming import (
    BaseStreamingDownloadHandler,
)
from scrapy.exceptions import DownloadCancelledError
from scrapy.http import Headers


class SyntheticDataLoss(RuntimeError):
    pass


@dataclass
class SyntheticResponse:
    url: str
    status: int
    headers: Headers
    chunks: list[bytes]
    lose_data: bool = False


class QuietSignals:
    def send_catch_log(self, **kwargs):
        return []


class SyntheticHandler(BaseStreamingDownloadHandler[SyntheticResponse]):
    requires_asyncio = False

    @staticmethod
    def _check_deps_installed() -> None:
        return None

    @asynccontextmanager
    async def _make_request(self, request, timeout):
        yield self.responses.pop(0)

    @staticmethod
    def _extract_headers(response):
        return response.headers

    @staticmethod
    def _build_base_response_args(response, request, headers):
        return {
            "status": response.status,
            "url": response.url,
            "headers": headers,
            "protocol": "HTTP/1.1",
        }

    @staticmethod
    async def _iter_body_chunks(response):
        for chunk in response.chunks:
            yield chunk
        if response.lose_data:
            raise SyntheticDataLoss("stream ended before its generated payload completed")

    @staticmethod
    def _is_dataloss_exception(exc):
        return isinstance(exc, SyntheticDataLoss)


class StreamingPathTest(unittest.IsolatedAsyncioTestCase):
    async def test_indirect_download_sequence(self):
        rng = random.Random(907_301)
        rich_chunks = [
            bytes(rng.randrange(1, 256) for _ in range(5 + (index * 7) % 19))
            for index in range(27)
        ]
        short_chunks = [bytes([rng.randrange(1, 256)]) * (index + 2) for index in range(4)]

        responses = [
            SyntheticResponse(
                "https://example.invalid/brief",
                299,
                Headers(),
                short_chunks,
            ),
            SyntheticResponse(
                "https://example.invalid/rich",
                299,
                Headers(),
                rich_chunks,
                lose_data=True,
            ),
            SyntheticResponse(
                "https://example.invalid/rejected",
                299,
                Headers({"Content-Length": "4096"}),
                rich_chunks,
            ),
        ]

        handler = object.__new__(SyntheticHandler)
        handler.responses = responses
        handler.crawler = SimpleNamespace(signals=QuietSignals(), spider=None)
        handler._default_maxsize = 0
        handler._default_warnsize = 0
        handler._fail_on_dataloss = True
        handler._tls_verbose_logging = False
        handler._fail_on_dataloss_warned = False

        first = await handler.download_request(
            Request("https://example.invalid/brief", meta={"download_warnsize": 17})
        )
        second = await handler.download_request(
            Request(
                "https://example.invalid/rich",
                meta={
                    "download_warnsize": sum(map(len, rich_chunks)) // 3,
                    "download_fail_on_dataloss": False,
                },
            )
        )
        with self.assertRaises(DownloadCancelledError):
            await handler.download_request(
                Request(
                    "https://example.invalid/rejected",
                    meta={"download_maxsize": len(second.body) // 2},
                )
            )

        self.assertEqual(first.body, b"".join(short_chunks))
        self.assertEqual(second.body, b"".join(rich_chunks))
        self.assertEqual(len(second.flags), int(second.flags[0] == "dataloss"))
