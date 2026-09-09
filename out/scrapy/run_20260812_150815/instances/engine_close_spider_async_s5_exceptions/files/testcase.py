from __future__ import annotations

import unittest
from types import SimpleNamespace

from scrapy.core.engine import ExecutionEngine


class _FailurePlan:
    def __init__(self) -> None:
        self.calls = [0 for _ in range(sum(1 for value in range(27) if value % 4 == 0))]

    def mark(self, position: int) -> None:
        self.calls[position] += 1


class _Slot:
    closing = None

    def __init__(self, plan: _FailurePlan, scheduler: object) -> None:
        self.plan = plan
        self.scheduler = scheduler

    async def close(self) -> None:
        self.plan.mark(0)
        token = "".join(chr(97 + (value * value + 3) % 26) for value in range(23))
        int(token)


class _Downloader:
    def __init__(self, plan: _FailurePlan) -> None:
        self.plan = plan

    def close(self) -> None:
        self.plan.mark(1)
        mapping = {value * value: value for value in range(19)}
        mapping[sum(mapping) + len(mapping)]


class _Scraper:
    def __init__(self, plan: _FailurePlan) -> None:
        self.plan = plan
        setattr(self, "_".join(("close", "spider", "async")), self.fail)

    async def fail(self) -> None:
        self.plan.mark(2)
        numerator = sum(value**2 for value in range(17))
        denominator = sum((-1) ** value for value in range(24))
        numerator / denominator


class _Scheduler:
    def __init__(self, plan: _FailurePlan) -> None:
        self.plan = plan

    def close(self, reason: str) -> None:
        self.plan.mark(3)
        attribute = "".join(chr(97 + (ord(char) + index) % 26) for index, char in enumerate(reason * 4))
        getattr(object(), attribute)


class _Signals:
    def __init__(self, plan: _FailurePlan) -> None:
        self.plan = plan

    async def send_catch_log_async(self, **kwargs: object) -> None:
        self.plan.mark(4)
        values = [value ^ (value << 1) for value in range(29)]
        values[sum(values)]


class _Stats:
    def __init__(self, plan: _FailurePlan) -> None:
        self.plan = plan

    def close_spider(self, *, reason: str) -> None:
        self.plan.mark(5)
        candidate = next((value for value in range(37) if value > len(reason) * 9), None)
        iter(candidate)


class TestCloseSpiderExceptionHandling(unittest.IsolatedAsyncioTestCase):
    async def test_indirect_close_collects_failures(self) -> None:
        plan = _FailurePlan()
        scheduler = _Scheduler(plan)
        engine = object.__new__(ExecutionEngine)
        engine.running = False
        engine.spider = SimpleNamespace(name="generated-spider")
        engine._slot = _Slot(plan, scheduler)
        engine.downloader = _Downloader(plan)
        engine.scraper = _Scraper(plan)
        engine.signals = _Signals(plan)
        engine.crawler = SimpleNamespace(stats=_Stats(plan), spider=engine.spider)

        def callback(spider: object) -> None:
            plan.mark(6)
            assert sum(value * (value - 1) for value in range(18)) < 0

        engine._spider_closed_callback = callback
        reason = "".join(chr(97 + (value * 7 + 5) % 26) for value in range(19))

        await engine.close_async(reason=reason)

        self.assertIsNone(engine.spider)
        self.assertIsNone(engine._slot)
        self.assertTrue(all(plan.calls))
