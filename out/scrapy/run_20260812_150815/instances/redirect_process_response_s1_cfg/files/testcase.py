import random
import unittest

from scrapy.downloadermiddlewares.redirect import RedirectMiddleware
from scrapy.http import Request, Response
from scrapy.utils.misc import build_from_crawler
from scrapy.utils.spider import DefaultSpider
from scrapy.utils.test import get_crawler


class RedirectProcessResponsePathTest(unittest.TestCase):
    def test_generated_redirect_matrix(self) -> None:
        crawler = get_crawler(DefaultSpider)
        crawler.spider = crawler._create_spider()
        middleware = build_from_crawler(RedirectMiddleware, crawler)

        generator = random.Random(0xD1CE7A)
        raw_values = [generator.getrandbits(52) for _ in range(41)]
        request_results = 0
        response_results = 0

        for index, raw in enumerate(raw_values):
            source_scheme = ("http", "https")[(raw >> 5) & 1]
            source_url = (
                f"{source_scheme}://origin-{raw % 23}.example.invalid/"
                f"{index:x}/{raw:x}"
            )
            if (raw ^ index) & 1:
                source_url += f"#seed-{(raw >> 17) % 997:x}"

            method = ("GET", "POST", "PUT", "HEAD")[(raw >> 9) & 3]
            meta = {}
            status = (200, 204, 301, 302, 303, 307, 308, 404)[
                (raw ^ (index * 13)) & 7
            ]
            headers = {}
            mode = (raw + index * index) % 11

            if mode == 0:
                meta["dont_redirect"] = True
            elif mode == 1:
                meta["handle_httpstatus_list"] = [status]
            elif mode == 2:
                meta["handle_httpstatus_all"] = True
            elif mode == 3:
                status = 302
            elif mode == 4:
                status = 200
                headers["Location"] = f"/ignored/{raw % 101}"
            elif mode == 5:
                status = 301
                headers["Location"] = f"ftp://mirror.invalid/{raw:x}"
            else:
                status = (301, 302, 303, 307, 308)[(raw >> 14) % 5]
                if mode & 1:
                    headers["Location"] = (
                        f"//edge-{(raw >> 21) % 29}.example.invalid/"
                        f"jump/{(raw ^ index) % 4093:x}"
                    )
                else:
                    headers["Location"] = f"../next/{(raw ^ (index << 7)) % 8191:x}"
                if (raw >> 31) & 1:
                    headers["Location"] += f"#target-{raw % 127:x}"

            if index == len(raw_values) // 2:
                source_url = (
                    f"https://origin-{raw % 23}.example.invalid/"
                    f"center/{raw:x}#seed-{(raw >> 17) % 997:x}"
                )
                method = "POST"
                meta = {}
                status = 302
                headers = {
                    "Location": (
                        f"//edge-{(raw >> 21) % 29}.example.invalid/"
                        f"center/{(raw ^ index) % 4093:x}"
                    )
                }

            request = Request(
                source_url,
                method=method,
                meta=meta,
                body=(f"payload-{raw:x}".encode() if method != "GET" else b""),
                headers={"Content-Type": "application/octet-stream"},
                priority=(raw >> 11) % 503,
            )
            response = Response(
                source_url, status=status, headers=headers, request=request
            )
            result = middleware.process_response(request, response)

            if isinstance(result, Request):
                request_results += 1
                self.assertIn(result.url.split(":", 1)[0], {"http", "https"})
            else:
                response_results += 1
                self.assertIs(result, response)

        self.assertGreater(request_results * response_results, len(raw_values))
