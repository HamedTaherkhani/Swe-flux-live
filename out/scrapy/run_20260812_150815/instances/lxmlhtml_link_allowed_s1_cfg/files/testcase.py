from __future__ import annotations

import random
import unittest

from scrapy.link import Link
from scrapy.linkextractors.lxmlhtml import LxmlLinkExtractor


class LinkAllowedPathTest(unittest.TestCase):
    def test_generated_filter_matrix(self):
        rng = random.Random(481_927)
        categories = list(range(8)) * 7 + [0]
        rng.shuffle(categories)
        midpoint = len(categories) // 2
        accepted_index = categories.index(7)
        categories[midpoint], categories[accepted_index] = (
            categories[accepted_index],
            categories[midpoint],
        )

        extractor = LxmlLinkExtractor(
            allow=(r"/item/", r"/asset/"),
            deny=(r"blocked", r"forbidden"),
            allow_domains=("allowed.example",),
            deny_domains=("deny.allowed.example",),
            deny_extensions=("pdf", "zip"),
            restrict_text=(r"keep", r"accept"),
        )

        links = []
        for index, category in enumerate(categories):
            token = "".join(rng.choice("abcdefghjkmnpqrstuvwxyz") for _ in range(9))
            serial = (index * rng.randrange(17, 97) + rng.randrange(101, 997)) % 10007
            if category == 0:
                url = f"javascript:void({serial})"
                text = f"keep-{token}"
            elif category == 1:
                url = f"https://allowed.example/other/{token}?n={serial}"
                text = f"keep-{token}"
            elif category == 2:
                url = f"https://allowed.example/item/blocked-{token}?n={serial}"
                text = f"keep-{token}"
            elif category == 3:
                url = f"https://outside.example/item/{token}?n={serial}"
                text = f"keep-{token}"
            elif category == 4:
                url = f"https://deny.allowed.example/item/{token}?n={serial}"
                text = f"keep-{token}"
            elif category == 5:
                extension = ("pdf", "zip")[(serial + index) % 2]
                url = f"https://allowed.example/asset/{token}.{extension}?n={serial}"
                text = f"keep-{token}"
            elif category == 6:
                url = f"https://allowed.example/item/{token}?n={serial}"
                text = f"discard-{token}"
            else:
                url = f"https://allowed.example/item/{token}?n={serial}"
                text = ("keep-", "accept-")[(serial + index) % 2] + token
            links.append(Link(url=url, text=text))

        outcomes = [extractor._link_allowed(link) for link in links]

        self.assertEqual(len(outcomes), len(links))
        self.assertTrue(any(outcomes))
        self.assertFalse(all(outcomes))
