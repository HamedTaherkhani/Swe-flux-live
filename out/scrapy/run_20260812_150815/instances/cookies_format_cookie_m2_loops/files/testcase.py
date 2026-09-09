import random
import unittest

from scrapy.downloadermiddlewares.cookies import CookiesMiddleware
from scrapy.http import Request


class TestCookieFormattingLoops(unittest.TestCase):
    def setUp(self) -> None:
        self.middleware = CookiesMiddleware()

    def _exercise(self, token: str, mode: int, scheme: str) -> None:
        generator = random.Random(f"cookie-matrix:{token}:{mode}:{scheme}")
        population = (
            sum((index + mode) * ord(char) for index, char in enumerate(token, 1))
            % (len(token) + 13)
            + len(token) * 3
            + 9
        )
        cookies = []
        for index in range(population):
            selector = (
                generator.getrandbits(20)
                ^ ((index + 1) * (mode + 17))
                ^ sum(ord(char) for char in token[: (index % len(token)) + 1])
            )
            cookie = {
                "name": f"{token}_{index:x}",
                "value": f"{selector:x}_{token[::-1]}",
            }

            if (selector + index + mode) % 13 == 0:
                cookie.pop("name" if selector & 1 else "value")
            else:
                if (selector ^ mode) % 5 != 0:
                    cookie["path"] = (
                        "/" if (selector + index) % 4 else "/matrix"
                    )
                if (selector + len(token) * mode) % 3:
                    cookie["domain"] = "qa.invalid"

            secure_case = (selector + index * mode) % 4
            if secure_case == 0:
                cookie["secure"] = True
            elif secure_case == 1:
                cookie["secure"] = False
            elif secure_case == 2:
                cookie["secure"] = None
            cookies.append(cookie)

        request = Request(
            f"{scheme}://qa.invalid/matrix/{token[::-1]}",
            cookies=cookies,
            meta={"cookiejar": f"{token}:{mode}"},
        )
        result = self.middleware.process_request(request)

        self.assertIsNone(result)
        self.assertIn("Cookie", request.headers)
        header = request.headers["Cookie"]
        self.assertIsInstance(header, bytes)
        self.assertNotIn(b"\r", header)
        self.assertNotIn(b"\n", header)
        self.assertGreater(len(header.split(b";")), len(token))

    def test_amber_https_sparse(self) -> None:
        self._exercise("amber", 2, "https")

    def test_bronze_http_dense(self) -> None:
        self._exercise("bronze", 5, "http")

    def test_cerulean_https_mixed(self) -> None:
        self._exercise("cerulean", 7, "https")

    def test_dahlia_http_sparse(self) -> None:
        self._exercise("dahlia", 11, "http")

    def test_ember_https_dense(self) -> None:
        self._exercise("ember", 13, "https")

    def test_fuchsia_http_mixed(self) -> None:
        self._exercise("fuchsia", 17, "http")

    def test_garnet_https_sparse(self) -> None:
        self._exercise("garnet", 19, "https")

    def test_hickory_http_dense(self) -> None:
        self._exercise("hickory", 23, "http")

    def test_indigo_https_mixed(self) -> None:
        self._exercise("indigo", 29, "https")

    def test_juniper_http_sparse(self) -> None:
        self._exercise("juniper", 31, "http")

    def test_kestrel_https_dense(self) -> None:
        self._exercise("kestrel", 37, "https")

    def test_lilac_http_mixed(self) -> None:
        self._exercise("lilac", 41, "http")
