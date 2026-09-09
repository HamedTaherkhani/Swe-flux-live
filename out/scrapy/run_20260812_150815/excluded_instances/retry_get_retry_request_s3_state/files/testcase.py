import logging
import random
import unittest

from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.http import Request, Response
from scrapy.utils.misc import build_from_crawler
from scrapy.utils.spider import DefaultSpider
from scrapy.utils.test import get_crawler


class RetryProgramStateTest(unittest.TestCase):
    def test_generated_response_retries(self) -> None:
        retry_codes = list(range(400, 600))
        crawler = get_crawler(
            DefaultSpider,
            settings_dict={
                "RETRY_HTTP_CODES": retry_codes,
                "RETRY_TIMES": len(retry_codes),
                "RETRY_GIVE_UP_LOG_LEVEL": "ERROR",
            },
        )
        crawler.spider = crawler._create_spider()
        middleware = build_from_crawler(RetryMiddleware, crawler)

        level_names = sorted(
            name
            for name, value in logging.getLevelNamesMapping().items()
            if value > 0 and logging.getLevelName(value) == name
        )
        generator = random.Random(0x5A17C0DE)
        returned_requests = 0
        returned_responses = 0

        for index in range(72):
            raw = generator.getrandbits(48)
            meta = {
                "retry_times": (raw ^ (raw >> 17)) % 31,
                "max_retry_times": (raw >> 9) % 11,
                "priority_adjust": ((raw >> 21) % 47) - 23,
                "give_up_log_level": level_names[(raw >> 33) % len(level_names)],
            }
            status = retry_codes[(raw ^ (index * index + index)) % len(retry_codes)]
            url = f"https://example.invalid/{index:x}/{raw:x}"
            request = Request(url, meta=meta, priority=(raw >> 7) % 997)
            response = Response(url, status=status, request=request)

            result = middleware.process_response(request, response)
            if isinstance(result, Request):
                returned_requests += 1
                self.assertTrue(result.dont_filter)
            else:
                returned_responses += 1
                self.assertIs(result, response)

        self.assertGreater(returned_requests * returned_responses, len(level_names))
        self.assertEqual(
            crawler.stats.get_value("retry/max_reached"), returned_responses
        )
