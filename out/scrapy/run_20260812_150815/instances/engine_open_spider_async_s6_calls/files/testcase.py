import random
import unittest
import warnings

from scrapy import signals
from scrapy.core.engine import ExecutionEngine
from scrapy.utils.defer import maybe_deferred_to_future
from scrapy.utils.spider import DefaultSpider
from scrapy.utils.test import get_crawler


class TestEngineOpenSpiderCallFlow(unittest.IsolatedAsyncioTestCase):
    async def test_dynamic_signal_dispatch(self):
        crawler = get_crawler(DefaultSpider, {"LOG_ENABLED": False})
        crawler.spider = crawler._create_spider()
        engine = ExecutionEngine(crawler, lambda _: None)
        crawler.engine = engine

        rng = random.Random(92417)
        method_names = ["pause", "unpause", "needs_backout", "spider_is_idle"]
        dispatch_plan = []
        for _ in range(len(method_names) + 2):
            batch = method_names.copy()
            rng.shuffle(batch)
            dispatch_plan.extend(batch)

        observed = []

        def dispatch_when_opened(spider):
            self.assertIs(spider, crawler.spider)
            for ordinal, method_name in enumerate(dispatch_plan):
                result = getattr(engine, method_name)()
                observed.append((ordinal, method_name, result, engine.paused))

        crawler.signals.connect(
            dispatch_when_opened,
            signal=signals.spider_opened,
            weak=False,
        )

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                deferred = engine.open_spider(
                    crawler.spider,
                    close_if_idle=bool(len(dispatch_plan) % len(method_names)),
                )
                await maybe_deferred_to_future(deferred)

            self.assertIsNotNone(engine._slot)
            self.assertGreater(len(observed), sum(range(len(method_names))))
            self.assertEqual({entry[1] for entry in observed}, set(method_names))
        finally:
            if engine.spider is not None:
                await engine.close_spider_async(reason="test-finished")
