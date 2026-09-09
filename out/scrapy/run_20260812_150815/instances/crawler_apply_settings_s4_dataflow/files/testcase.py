import asyncio
import random
import unittest
from unittest import mock

from scrapy.crawler import AsyncCrawlerRunner
from scrapy.spiders import Spider


class _Engine:
    def __init__(self, _crawler, _stop):
        self.running = False

    async def open_spider_async(self):
        return None

    async def start_async(self):
        self.running = True


async def _empty_start(_self):
    for value in ():
        yield value


def _spider_class(name, custom_settings):
    return type(
        name,
        (Spider,),
        {
            "name": name.lower(),
            "custom_settings": custom_settings,
            "start": _empty_start,
        },
    )


async def _run_all(runner, spider_classes):
    outcomes = []
    for spider_class in spider_classes:
        await runner.crawl(spider_class)
        outcomes.append((runner.bootstrap_failed, len(runner.crawlers)))
    return outcomes


class TestCrawlerSettingsDataFlow(unittest.TestCase):
    def test_runner_settings_paths(self):
        rng = random.Random(731)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        common = {
            "LOG_ENABLED": False,
            "TELNETCONSOLE_ENABLED": False,
            "ROBOTSTXT_OBEY": False,
        }

        try:
            reactorless_classes = []
            for index in range(rng.randrange(6, 9)):
                settings = dict(common)
                settings["TWISTED_REACTOR_ENABLED"] = False
                settings["DOWNLOAD_DELAY"] = rng.random() / (index + 1)
                reactorless_classes.append(
                    _spider_class(f"Reactorless{index}", settings)
                )

            reactorless_runner = AsyncCrawlerRunner(
                {"TWISTED_REACTOR_ENABLED": False, "LOG_ENABLED": False}
            )
            with (
                mock.patch("scrapy.crawler.ExecutionEngine", _Engine),
                mock.patch("scrapy.crawler.is_reactor_installed", return_value=False),
            ):
                outcomes = loop.run_until_complete(
                    _run_all(reactorless_runner, reactorless_classes)
                )

            reactor_path = (
                "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
            )
            event_loop_path = "asyncio.unix_events._UnixSelectorEventLoop"

            reactor_classes = []
            for index in range(rng.randrange(8, 11)):
                settings = dict(common)
                settings["TWISTED_REACTOR_ENABLED"] = True
                settings["TWISTED_REACTOR"] = (
                    reactor_path if index % 3 else ""
                )
                settings["ASYNCIO_EVENT_LOOP"] = (
                    event_loop_path if index % 2 else None
                )
                settings["CONCURRENT_REQUESTS"] = 1 + rng.randrange(4)
                reactor_classes.append(_spider_class(f"Reactor{index}", settings))

            reactor_runner = AsyncCrawlerRunner(
                {"TWISTED_REACTOR_ENABLED": True, "LOG_ENABLED": False}
            )
            with (
                mock.patch("scrapy.crawler.ExecutionEngine", _Engine),
                mock.patch("scrapy.crawler.is_reactor_installed", return_value=True),
                mock.patch(
                    "scrapy.crawler.is_asyncio_reactor_installed", return_value=True
                ),
                mock.patch("scrapy.crawler.verify_installed_reactor"),
                mock.patch("scrapy.crawler.verify_installed_asyncio_event_loop"),
                mock.patch("scrapy.crawler.log_reactor_info"),
            ):
                outcomes.extend(
                    loop.run_until_complete(_run_all(reactor_runner, reactor_classes))
                )

            self.assertTrue(outcomes)
            self.assertTrue(all(not failed and active == 0 for failed, active in outcomes))
        finally:
            loop.close()
            asyncio.set_event_loop(None)
