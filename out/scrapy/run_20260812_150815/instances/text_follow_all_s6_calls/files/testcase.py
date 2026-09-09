import random
import unittest

from scrapy.http import TextResponse


class TestTextResponseFollowAll(unittest.TestCase):
    def test_mixed_xpath_selectors(self):
        rng = random.Random(7319)
        kinds = [index % 5 for index in range(73)]
        rng.shuffle(kinds)

        fragments = []
        rolling = rng.randrange(1000, 9000)
        for index, kind in enumerate(kinds):
            rolling = (rolling * 37 + index * 19 + kind) % 104729
            token = f"{rolling:x}-{index:x}"
            if kind == 0:
                fragments.append(
                    f"<a href=' /jump/{token}?rank={rolling % 17} '>A{index}</a>"
                )
            elif kind == 1:
                fragments.append(
                    f"<link href='/asset/{token}.css' rel='stylesheet'>"
                )
            elif kind == 2:
                fragments.append(f"<a data-seq='{token}'>missing {index}</a>")
            elif kind == 3:
                fragments.append(f"<section data-seq='{token}'>S{index}</section>")
            else:
                fragments.append(f"<img src='/image/{token}.png'>")

        html = "<html><body>" + "".join(fragments) + "</body></html>"
        response = TextResponse(
            url="https://example.invalid/root/index.html",
            body=html.encode(),
            encoding="utf-8",
        )

        selector_query = "//body/* | //a/@href | //link/@href"
        requests = list(
            response.follow_all(
                xpath=selector_query,
                headers={"X-Run": str(rolling)},
                priority=rolling % 11,
            )
        )

        self.assertGreater(len(requests), len(fragments) // 3)
        self.assertTrue(all(request.url.startswith("https://example.invalid/") for request in requests))
        self.assertLess(len({request.url for request in requests}), len(requests))
