from __future__ import annotations

import asyncio
import importlib
import math
import unittest
from dataclasses import dataclass
from typing import Any

from scrapy import Spider
from scrapy.crawler import AsyncCrawlerRunner, Crawler


class _QuietSpider(Spider):
    name = "generated-runtime-probe"


def _computed_failure(kind: int, salt: int) -> None:
    width = sum((value * value + salt) % 11 for value in range(17 + salt % 5))
    if kind == 0:
        math.exp(width * (sum(value + 1 for value in range(8)) ** 2))
    elif kind == 1:
        mapping = {value * value + salt: value for value in range(width % 17 + 8)}
        mapping[sum(mapping) + width]
    elif kind == 2:
        payload = bytes((value * 37 + width) % 256 for value in range(width % 19 + 11))
        payload.decode("ascii")
    elif kind == 3:
        attribute = "".join(chr(97 + (value + width) % 26) for value in range(width % 23 + 7))
        getattr(object(), attribute)
    elif kind == 4:
        values = [value ^ (value << 1) for value in range(width % 29 + 6)]
        values[sum(values) + width]
    elif kind == 5:
        numerator = sum(value**3 for value in range(width % 31 + 5))
        denominator = sum((-1) ** value for value in range((width % 7 + 4) * 2))
        numerator // denominator
    elif kind == 6:
        candidate = next((value for value in range(width) if value > width + salt), None)
        iter(candidate)
    else:
        token = "".join(chr(97 + (value * 7 + salt) % 26) for value in range(width % 9 + 8))
        int(token)


@dataclass(frozen=True)
class _Plan:
    stage: str
    primary: int
    cleanup: int | None
    salt: int


class _Engine:
    def __init__(self, plan: _Plan) -> None:
        self.plan = plan
        self.close_calls = 0

    async def open_spider_async(self) -> None:
        await asyncio.sleep(0)
        if self.plan.stage == "open":
            _computed_failure(self.plan.primary, self.plan.salt)
        if self.plan.stage.startswith("signal"):
            module = importlib.import_module(".".join(("scrapy", "exceptions")))
            exception_class = getattr(module, "".join(("Close", "Spider")))
            raise exception_class(reason=str(self.plan.salt))
        if self.plan.stage == "swallowed":
            try:
                _computed_failure(self.plan.primary, self.plan.salt)
            except Exception:
                pass

    async def start_async(self) -> None:
        await asyncio.sleep(0)
        if self.plan.stage == "start":
            _computed_failure(self.plan.primary, self.plan.salt)

    async def close_async(self, reason: str | None = None) -> None:
        self.close_calls += 1
        await asyncio.sleep(0)
        if self.plan.cleanup is not None:
            _computed_failure(
                self.plan.cleanup,
                self.plan.salt + self.close_calls + len(reason or ""),
            )


class _ScenarioCrawler(Crawler):
    def __init__(self, plan: _Plan) -> None:
        self.plan = plan
        self.armed = False
        super().__init__(
            _QuietSpider,
            {
                "LOG_ENABLED": False,
                "TWISTED_REACTOR_ENABLED": True,
            },
        )
        self.armed = True

    def _create_spider(self, *args: Any, **kwargs: Any) -> Spider:
        if self.plan.stage == "spider":
            _computed_failure(self.plan.primary, self.plan.salt + len(args) + len(kwargs))
        return _QuietSpider.from_crawler(self, *args, **kwargs)

    def _apply_settings(self) -> None:
        if self.plan.stage == "settings":
            _computed_failure(self.plan.primary, self.plan.salt)

    def _update_root_log_handler(self) -> None:
        if self.armed and self.plan.stage == "logging":
            _computed_failure(self.plan.primary, self.plan.salt)

    def _create_engine(self) -> _Engine:
        if self.plan.stage == "engine":
            _computed_failure(self.plan.primary, self.plan.salt)
        return _Engine(self.plan)


class TestCrawlerCrawlAsyncExceptions(unittest.IsolatedAsyncioTestCase):
    async def _run_once(self, plan: _Plan, *, expected_failures: int) -> _ScenarioCrawler:
        runner = AsyncCrawlerRunner({"TWISTED_REACTOR_ENABLED": True})
        crawler = _ScenarioCrawler(plan)
        outcomes = await asyncio.gather(
            runner.crawl(crawler, generated=sum((value + plan.salt) % 9 for value in range(37))),
            return_exceptions=True,
        )
        self.assertEqual(
            sum(isinstance(outcome, Exception) for outcome in outcomes),
            expected_failures,
        )
        return crawler

    async def test_apply_settings_failure(self) -> None:
        await self._run_once(_Plan("start", 1, None, sum(range(13))), expected_failures=1)

    async def test_clean_completion(self) -> None:
        crawler = await self._run_once(
            _Plan("clean", 0, None, sum(value % 5 for value in range(38))),
            expected_failures=0,
        )
        self.assertIsNotNone(crawler.spider)

    async def test_close_signal_cleanup_failure(self) -> None:
        crawler = await self._run_once(
            _Plan("signal-cleanup", 0, 3, sum(value * 5 for value in range(27))),
            expected_failures=1,
        )
        self.assertGreater(crawler.engine.close_calls, 1)

    async def test_close_signal_recovery(self) -> None:
        crawler = await self._run_once(
            _Plan("signal", 0, None, sum(value ^ 5 for value in range(28))),
            expected_failures=0,
        )
        self.assertEqual(crawler.engine.close_calls, 1)

    async def test_engine_creation_failure(self) -> None:
        await self._run_once(
            _Plan("engine", 2, None, sum(value * value for value in range(15))),
            expected_failures=1,
        )

    async def test_logging_update_failure(self) -> None:
        await self._run_once(
            _Plan("logging", 3, None, sum(value | 5 for value in range(23))),
            expected_failures=1,
        )

    async def test_open_and_cleanup_failures(self) -> None:
        crawler = await self._run_once(
            _Plan("open", 6, 1, sum(value % 7 for value in range(33))),
            expected_failures=1,
        )
        self.assertEqual(crawler.engine.close_calls, 1)

    async def test_open_failure(self) -> None:
        await self._run_once(
            _Plan("open", 7, None, sum(value // 3 for value in range(26))),
            expected_failures=1,
        )

    async def test_parallel_reentry(self) -> None:
        runner = AsyncCrawlerRunner({"TWISTED_REACTOR_ENABLED": True})
        crawler = _ScenarioCrawler(
            _Plan("clean", 0, None, sum(value * 4 % 11 for value in range(41)))
        )
        outcomes = await asyncio.gather(
            runner.crawl(crawler, generated=sum(range(23))),
            runner.crawl(crawler, generated=sum(range(16))),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(item, Exception) for item in outcomes), 1)

    async def test_spider_creation_failure(self) -> None:
        await self._run_once(
            _Plan("open", 0, None, sum(value + 2 for value in range(17))),
            expected_failures=1,
        )

    async def test_start_and_cleanup_failures(self) -> None:
        crawler = await self._run_once(
            _Plan("start", 2, 5, sum(value * 7 % 23 for value in range(29))),
            expected_failures=1,
        )
        self.assertEqual(crawler.engine.close_calls, 1)

    async def test_start_failure(self) -> None:
        await self._run_once(
            _Plan("start", 4, None, sum(value & 7 for value in range(32))),
            expected_failures=1,
        )

    async def test_swallowed_callee_failure(self) -> None:
        crawler = await self._run_once(
            _Plan("open", 7, None, sum(value % 9 for value in range(43))),
            expected_failures=1,
        )
        self.assertEqual(crawler.engine.close_calls, 1)

    async def test_sequential_reuse(self) -> None:
        runner = AsyncCrawlerRunner({"TWISTED_REACTOR_ENABLED": True})
        crawler = _ScenarioCrawler(
            _Plan("settings", 1, None, sum(value * value % 13 for value in range(35)))
        )
        first = await asyncio.gather(
            runner.crawl(crawler, generated=sum(range(21))),
            return_exceptions=True,
        )
        second = await asyncio.gather(
            runner.crawl(crawler, generated=sum(range(24))),
            return_exceptions=True,
        )
        self.assertEqual(
            sum(isinstance(item, Exception) for item in first + second),
            2,
        )