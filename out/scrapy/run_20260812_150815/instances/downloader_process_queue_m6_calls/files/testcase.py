from __future__ import annotations

import asyncio
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from twisted.internet.defer import Deferred

from scrapy import Request
from scrapy.core import downloader as downloader_module
from scrapy.core.downloader import Downloader, Slot
from scrapy.http import Response


class _Handlers:
    def __init__(self) -> None:
        self.calls = 0

    async def download_request_async(self, request: Request) -> Response:
        self.calls += 1
        return Response(request.url, status=200 + (len(request.url) % 7), request=request)


class _Signals:
    def __init__(self) -> None:
        self.seen = []

    def send_catch_log(self, **kwargs) -> None:
        self.seen.append((kwargs["signal"], kwargs["request"].url))


class _LaterCall:
    def cancel(self) -> None:
        pass


class TestDownloaderQueueCallGraph(unittest.TestCase):
    def _run_scenario(
        self, seed: int, width: int, delayed: bool, randomized: bool
    ) -> None:
        rng = random.Random(seed)
        rounds = width + rng.randrange(2, 6)
        handlers = _Handlers()
        signals = _Signals()
        downloader = Downloader.__new__(Downloader)
        downloader.handlers = handlers
        downloader.signals = signals
        downloader.crawler = SimpleNamespace(spider=None)
        slot = Slot(
            concurrency=1 + rng.randrange(2, width + 3),
            delay=(rng.randrange(2, 8) / 10) if delayed else 0.0,
            randomize_delay=randomized,
        )
        downloader.slots = {"scenario": slot}
        downloader._slot_gc_loop = None
        scheduled_urls = []

        def consume(coro) -> None:
            request = coro.cr_frame.f_locals["request"]
            scheduled_urls.append(request.url)
            coro.close()

        async def exercise() -> list[int]:
            statuses = []
            caller = getattr(downloader, "_download")
            for turn in range(rounds):
                additions = 1 + (
                    rng.randrange(1, width + 4) + turn * (seed % 5 + 1)
                ) % (width + 3)
                for offset in range(additions):
                    token = (seed * 97 + turn * 31 + offset * 13) % 997
                    queued = Request(f"https://queue.invalid/{token:x}/{turn:x}")
                    slot.queue.append((queued, Deferred()))
                if delayed:
                    slot.latercall = None
                    slot.lastseen = 998.0 - slot.delay
                active = Request(
                    f"https://active.invalid/{seed:x}/{turn:x}/{rng.randrange(4096):x}"
                )
                response = await caller(slot, active)
                statuses.append(response.status)
                if (rng.randrange(11) + turn + width) % 3 == 0:
                    self.assertIn("downloader.Slot", str(slot))
            return statuses

        with (
            patch.object(downloader_module, "_schedule_coro", consume),
            patch.object(downloader_module, "monotonic", return_value=1000.0),
            patch.object(
                downloader_module,
                "call_later",
                side_effect=lambda *args, **kwargs: _LaterCall(),
            ),
            patch.object(
                downloader_module.random,
                "uniform",
                side_effect=lambda low, high: low + (high - low) * 0.625,
            ),
        ):
            statuses = asyncio.run(exercise())

        self.assertEqual(handlers.calls, len(statuses))
        self.assertEqual(len(signals.seen) // 2, len(statuses))
        self.assertEqual(len(signals.seen) % 2, 0)
        self.assertTrue(all(status >= 200 for status in statuses))
        self.assertTrue(scheduled_urls)
        downloader.close()
        self.assertIsNone(slot.latercall)

    def test_sparse_zero_delay(self) -> None:
        self._run_scenario(17, 3, False, False)

    def test_wide_zero_delay(self) -> None:
        self._run_scenario(29, 7, False, False)

    def test_short_fixed_delay(self) -> None:
        self._run_scenario(43, 4, True, False)

    def test_wide_fixed_delay(self) -> None:
        self._run_scenario(61, 8, True, False)

    def test_randomized_delay(self) -> None:
        self._run_scenario(73, 5, True, True)

    def test_dense_randomized_delay(self) -> None:
        self._run_scenario(89, 9, True, True)

    def test_even_seed_queue(self) -> None:
        self._run_scenario(104, 6, False, False)

    def test_prime_seed_queue(self) -> None:
        self._run_scenario(131, 4, False, True)

    def test_high_concurrency_mix(self) -> None:
        self._run_scenario(157, 10, False, False)

    def test_delayed_backlog(self) -> None:
        self._run_scenario(181, 6, True, False)

    def test_randomized_backlog(self) -> None:
        self._run_scenario(211, 7, True, True)

    def test_compact_mixed_queue(self) -> None:
        self._run_scenario(239, 5, False, True)
