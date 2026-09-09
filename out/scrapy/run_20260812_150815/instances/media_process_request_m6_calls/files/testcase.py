from __future__ import annotations

import asyncio
import random
import unittest
from types import SimpleNamespace
from typing import Any

from twisted.python.failure import Failure

from scrapy.http import Request, Response
from scrapy.pipelines.media import (
    FileException,
    FileInfo,
    FileInfoOrError,
    MediaPipeline,
    _MediaRequestFiltered,
)
from scrapy.utils.spider import DefaultSpider
from scrapy.utils.test import get_crawler


class ScenarioEngine:
    async def download_async(self, request: Request) -> Response:
        if request.meta["mode"] == "transport":
            raise OSError(f"transport-{request.meta['token']}")
        return Response(request.url, body=request.meta["payload"], request=request)


class ScenarioPipeline(MediaPipeline):
    LOG_FAILED_RESULTS = False

    def get_media_requests(
        self, item: dict[str, Any], info: MediaPipeline.SpiderInfo
    ) -> list[Request]:
        return item["requests"]

    def media_to_download(
        self,
        request: Request,
        info: MediaPipeline.SpiderInfo,
        *,
        item: Any = None,
    ) -> FileInfo | None:
        mode = request.meta["mode"]
        if mode == "shortcut":
            return {
                "url": request.url,
                "path": f"shortcut/{request.meta['token']:x}",
                "checksum": None,
                "status": "cached",
            }
        if mode == "filtered":
            raise _MediaRequestFiltered(f"filtered-{request.meta['token']}")
        return None

    def media_downloaded(
        self,
        response: Response,
        request: Request,
        info: MediaPipeline.SpiderInfo,
        *,
        item: Any = None,
    ) -> FileInfo:
        if request.meta["mode"] == "decode":
            raise FileException(f"decode-{request.meta['token']}")
        return {
            "url": response.url,
            "path": f"download/{request.meta['token']:x}",
            "checksum": str(sum(response.body) % 997),
            "status": "downloaded",
        }

    def media_failed(
        self,
        failure: Failure,
        request: Request,
        info: MediaPipeline.SpiderInfo,
    ) -> Failure:
        failure.raiseException()

    def item_completed(
        self,
        results: list[FileInfoOrError],
        item: dict[str, Any],
        info: MediaPipeline.SpiderInfo,
    ) -> dict[str, Any]:
        super().item_completed(results, item, info)
        item["outcomes"] = results
        return item

    def file_path(
        self,
        request: Request,
        response: Response | None = None,
        info: MediaPipeline.SpiderInfo | None = None,
        *,
        item: Any = None,
    ) -> str:
        return request.url


class MediaProcessRequestCallCountsTest(unittest.TestCase):
    def setUp(self) -> None:
        crawler = get_crawler(DefaultSpider)
        crawler.spider = crawler._create_spider()
        crawler.engine = ScenarioEngine()
        self.pipeline = ScenarioPipeline(crawler=crawler)
        self.pipeline.open_spider()

    @staticmethod
    def _recover(failure: Failure) -> FileInfo:
        marker = sum(ord(ch) for ch in failure.type.__name__)
        return {
            "url": "recovered://local",
            "path": f"recovery/{marker:x}",
            "checksum": None,
            "status": "recovered",
        }

    def _requests(
        self,
        seed: int,
        size: int,
        palette: tuple[str, ...],
        buckets: int,
        *,
        recover: bool = False,
    ) -> list[Request]:
        rng = random.Random(seed)
        requests = []
        for ordinal in range(size):
            slot = (ordinal * ordinal + rng.randrange(buckets)) % buckets
            mode = palette[(rng.randrange(len(palette)) + ordinal) % len(palette)]
            token = rng.getrandbits(31) ^ (ordinal << 9)
            payload = bytes(rng.randrange(1, 256) for _ in range(7 + ordinal % 11))
            requests.append(
                Request(
                    f"https://media.invalid/asset/{slot}?group={seed % 13}",
                    meta={"mode": mode, "token": token, "payload": payload},
                    errback=self._recover if recover else None,
                )
            )
        rng.shuffle(requests)
        return requests

    async def _process(self, requests: list[Request]) -> dict[str, Any]:
        item: dict[str, Any] = {"requests": requests}
        result = await self.pipeline.process_item(item)
        self.assertIs(result, item)
        self.assertEqual(len(result["outcomes"]), len(requests))
        self.assertTrue(all(isinstance(entry[0], bool) for entry in result["outcomes"]))
        return result

    def test_seeded_mixed_modes(self) -> None:
        requests = self._requests(
            0x51A7, len("interprocedural-calls"), ("shortcut", "download", "decode"), 17
        )
        result = asyncio.run(self._process(requests))
        self.assertGreater(len(result["outcomes"]), len(set("trace")))

    def test_dense_concurrent_duplicates(self) -> None:
        size = sum(range(3, 9))
        requests = self._requests(0xD00D, size, ("download", "shortcut"), 5)
        result = asyncio.run(self._process(requests))
        self.assertLess(len(self.pipeline.spiderinfo.downloaded), len(result["outcomes"]))

    def test_shortcut_only(self) -> None:
        size = len("cached-without-engine")
        requests = self._requests(0xCA5E, size, ("shortcut",), size)
        result = asyncio.run(self._process(requests))
        self.assertTrue(any(ok for ok, _value in result["outcomes"]))

    def test_download_only(self) -> None:
        size = len("engine-download-branch")
        requests = self._requests(0xE11E, size, ("download",), size - 3)
        result = asyncio.run(self._process(requests))
        self.assertFalse(all(not ok for ok, _value in result["outcomes"]))

    def test_transport_failures(self) -> None:
        size = len("transport-error-volume")
        requests = self._requests(0xFA17, size, ("transport", "download"), size)
        result = asyncio.run(self._process(requests))
        self.assertTrue(any(not ok for ok, _value in result["outcomes"]))

    def test_decode_failures(self) -> None:
        size = len("post-download-failures")
        requests = self._requests(0xDEC0DE, size, ("decode", "download"), size - 4)
        result = asyncio.run(self._process(requests))
        self.assertGreater(sum(not ok for ok, _value in result["outcomes"]), 0)

    def test_filtered_requests(self) -> None:
        size = len("filtering-before-fetch")
        requests = self._requests(
            0xF11E, size, ("filtered", "shortcut", "download"), size // 2
        )
        result = asyncio.run(self._process(requests))
        self.assertEqual(len(result["outcomes"]), size)

    def test_errback_recovery(self) -> None:
        size = len("failure-recovery-hooks")
        requests = self._requests(
            0xEBAC, size, ("transport", "decode", "download"), size - 2, recover=True
        )
        result = asyncio.run(self._process(requests))
        self.assertTrue(any(ok for ok, _value in result["outcomes"]))

    def test_cache_across_items(self) -> None:
        size = len("cross-item-cache-pass")
        first = self._requests(0xCACE, size, ("download", "shortcut"), size)
        second = self._requests(0xCACE, size, ("decode", "transport"), size)
        asyncio.run(self._process(first))
        result = asyncio.run(self._process(second))
        self.assertEqual(len(result["outcomes"]), len(first))

    def test_reversed_generated_order(self) -> None:
        size = len("reverse-request-stream")
        requests = self._requests(
            0xA11CE, size, ("shortcut", "filtered", "download"), size - 5
        )
        requests.reverse()
        result = asyncio.run(self._process(requests))
        self.assertIsInstance(result["outcomes"], list)

    def test_partitioned_batches(self) -> None:
        base = self._requests(
            0xB47C, len("partitioned-request-volume"), ("download", "decode"), 19
        )
        observed = []
        for boundary in (7, 15, len(base)):
            start = len(observed)
            part = base[start:boundary]
            observed.extend(part)
            result = asyncio.run(self._process(part))
            self.assertEqual(len(result["outcomes"]), len(part))

    def test_mutated_second_wave(self) -> None:
        size = len("mutating-metadata-wave")
        requests = self._requests(
            0x5EC0, size, ("shortcut", "download", "transport"), size - 1, recover=True
        )
        asyncio.run(self._process(requests[::2]))
        for request in requests[1::2]:
            request.meta["mode"] = (
                "filtered" if request.meta["token"] & 1 else "download"
            )
        result = asyncio.run(self._process(requests[1::2]))
        self.assertTrue(result["outcomes"])
