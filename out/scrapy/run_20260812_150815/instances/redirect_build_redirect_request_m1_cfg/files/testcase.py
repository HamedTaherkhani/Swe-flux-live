import random
import unittest

from scrapy.downloadermiddlewares.redirect import RedirectMiddleware
from scrapy.http import Request, Response
from scrapy.utils.misc import build_from_crawler
from scrapy.utils.spider import DefaultSpider
from scrapy.utils.test import get_crawler


class TestRedirectRequestControlFlow(unittest.TestCase):
    def setUp(self):
        crawler = get_crawler(DefaultSpider)
        crawler.spider = crawler._create_spider()
        self.middleware = build_from_crawler(RedirectMiddleware, crawler)

    def _redirect_many(self, seed, size, make_case):
        rng = random.Random(seed)
        results = []
        for index in range(size):
            source_url, target_url, method, status, headers, meta = make_case(
                rng, index
            )
            request = Request(
                source_url,
                method=method,
                headers=headers,
                meta=meta,
                body=(f"payload-{seed}-{index}".encode() if method != "GET" else b""),
            )
            response = Response(
                source_url,
                status=status,
                headers={"Location": target_url},
                request=request,
            )
            redirected = self.middleware.process_response(request, response)
            self.assertIsInstance(redirected, Request)
            self.assertGreaterEqual(redirected.meta["redirect_times"], 1)
            self.assertNotIn("Referer", redirected.headers)
            results.append(redirected)
        self.assertEqual(len(results), size)
        return results

    def test_authorization_default_port_equivalence(self):
        def cases(rng, index):
            explicit = ":80" if index % 2 else ""
            suffix = rng.randrange(100, 999)
            return (
                f"http://auth.example{explicit}/from/{suffix}",
                f"http://auth.example:{80 if explicit == '' else 80}/to/{suffix}",
                "GET",
                307,
                {"Authorization": f"Bearer token-{suffix}"},
                {},
            )

        results = self._redirect_many(1103, 3, cases)
        self.assertTrue(all("Authorization" in item.headers for item in results))

    def test_authorization_port_changes(self):
        def cases(rng, index):
            source_port = 8100 + rng.randrange(7)
            target_port = source_port + index + 1
            return (
                f"http://ports.example:{source_port}/source",
                f"http://ports.example:{target_port}/target",
                "HEAD",
                308,
                {"Authorization": f"Basic generated-{source_port}"},
                {},
            )

        results = self._redirect_many(2207, 4, cases)
        self.assertTrue(all("Authorization" not in item.headers for item in results))

    def test_both_sensitive_headers_cross_origin(self):
        def cases(rng, index):
            label = rng.randrange(1000, 9999)
            return (
                f"https://source-{index}.example/path/{label}",
                f"http://target-{label % 5}.example/landing",
                "GET",
                301,
                {
                    "Authorization": f"Bearer {label}",
                    "Cookie": f"session={label}; shard={index}",
                },
                {},
            )

        results = self._redirect_many(3301, 5, cases)
        self.assertTrue(
            all(
                "Authorization" not in item.headers and "Cookie" not in item.headers
                for item in results
            )
        )

    def test_cookie_http_to_https_same_host(self):
        def cases(rng, index):
            host = f"upgrade-{rng.randrange(3)}.example"
            marker = rng.randrange(100, 999)
            return (
                f"http://{host}/old/{index}",
                f"https://{host}/new/{marker}",
                "GET",
                302,
                {"Cookie": f"upgrade={marker}"},
                {},
            )

        results = self._redirect_many(4409, 4, cases)
        self.assertTrue(all("Cookie" in item.headers for item in results))

    def test_cookie_https_to_http_is_removed(self):
        def cases(rng, index):
            host = f"downgrade-{index % 2}.example"
            marker = rng.randrange(10000, 99999)
            return (
                f"https://{host}/secure/{marker}",
                f"http://{host}/plain/{index}",
                "HEAD",
                307,
                {"Cookie": f"secure={marker}"},
                {},
            )

        results = self._redirect_many(5519, 3, cases)
        self.assertTrue(all("Cookie" not in item.headers for item in results))

    def test_cookie_same_origin_relative_locations(self):
        def cases(rng, index):
            marker = rng.randrange(1000, 9999)
            return (
                f"http://relative.example/base/{index}",
                f"../next/{marker}?part={index}",
                "GET",
                308,
                {"Cookie": f"relative={marker}"},
                {},
            )

        results = self._redirect_many(6619, 5, cases)
        self.assertTrue(all("Cookie" in item.headers for item in results))

    def test_cookie_subdomain_changes(self):
        def cases(rng, index):
            marker = rng.randrange(100, 999)
            return (
                f"https://node-{index}.cluster.example/start",
                f"https://node-{index + 1}.cluster.example/end/{marker}",
                "GET",
                307,
                {"Cookie": f"node={marker}"},
                {},
            )

        results = self._redirect_many(7723, 4, cases)
        self.assertTrue(all("Cookie" not in item.headers for item in results))

    def test_no_sensitive_headers_mixed_hosts(self):
        def cases(rng, index):
            source_scheme = "https" if rng.randrange(2) else "http"
            target_scheme = "http" if index % 2 else "https"
            return (
                f"{source_scheme}://plain-{index}.example/source",
                f"{target_scheme}://elsewhere-{rng.randrange(9)}.example/target",
                "HEAD" if index % 2 else "GET",
                307 + index % 2,
                {"X-Sequence": str(rng.randrange(1000, 9999))},
                {},
            )

        results = self._redirect_many(8837, 5, cases)
        self.assertTrue(all("X-Sequence" in item.headers for item in results))

    def test_post_redirects_rebuild_as_get(self):
        def cases(rng, index):
            marker = rng.randrange(1000, 9999)
            headers = {
                "Authorization": f"Bearer post-{marker}",
                "Content-Type": "application/octet-stream",
                "Cookie": f"post={index}",
            }
            return (
                f"http://post-{index % 2}.example/submit/{marker}",
                f"https://post-{index % 2}.example/result/{index}",
                "POST",
                301 + index % 2,
                headers,
                {},
            )

        results = self._redirect_many(9949, 4, cases)
        self.assertTrue(all(item.method == "GET" and not item.body for item in results))

    def test_proxy_metadata_cross_scheme(self):
        def cases(rng, index):
            marker = rng.randrange(100, 999)
            meta = {
                "_auth_proxy": f"auth-{marker}",
                "_scheme_proxy": True,
                "proxy": f"http://proxy-{index}.example:8123",
            }
            return (
                f"http://proxy-source.example/item/{marker}",
                f"https://proxy-source.example/item/{marker + index}",
                "GET",
                302,
                {"Proxy-Authorization": f"Basic proxy-{marker}"},
                meta,
            )

        results = self._redirect_many(10103, 5, cases)
        self.assertTrue(
            all(
                "_scheme_proxy" not in item.meta
                and "proxy" not in item.meta
                and "_auth_proxy" not in item.meta
                and "Proxy-Authorization" not in item.headers
                for item in results
            )
        )

    def test_proxy_metadata_same_scheme(self):
        def cases(rng, index):
            marker = rng.randrange(100, 999)
            meta = {
                "_auth_proxy": f"same-{marker}",
                "_scheme_proxy": True,
                "proxy": f"http://stable-proxy.example:{8200 + index}",
            }
            return (
                f"https://same-proxy.example/from/{index}",
                f"https://same-proxy.example/to/{marker}",
                "HEAD",
                308,
                {"Proxy-Authorization": f"Basic same-{marker}"},
                meta,
            )

        results = self._redirect_many(11113, 3, cases)
        self.assertTrue(all("_scheme_proxy" in item.meta for item in results))

    def test_status_303_non_get_rebuilds(self):
        methods = ("PUT", "PATCH", "DELETE")

        def cases(rng, index):
            marker = rng.randrange(10000, 99999)
            return (
                f"https://method.example/action/{marker}",
                f"https://method.example/done/{index}",
                methods[index % len(methods)],
                303,
                {
                    "Authorization": f"Bearer method-{marker}",
                    "Cookie": f"method={marker}",
                    "Content-Type": "text/plain",
                },
                {},
            )

        results = self._redirect_many(12143, 5, cases)
        self.assertTrue(all(item.method == "GET" for item in results))
