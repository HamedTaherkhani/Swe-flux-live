from __future__ import annotations

import random
import unittest

from scrapy.link import Link
from scrapy.linkextractors.lxmlhtml import LxmlLinkExtractor


class LinkAllowedPathTest(unittest.TestCase):
    def test_generated_filter_matrix(self):
        rng = random.Random(100_499)
        categories = list(range(8)) * 18 + [0, 0, 0, 1, 1, 3, 5, 6, 7]
        rng.shuffle(categories)
        midpoint = len(categories) // 2
        accepted_index = categories.index(7)
        categories[midpoint], categories[accepted_index] = (
            categories[accepted_index],
            categories[midpoint],
        )

        extractor = LxmlLinkExtractor(
            allow=(r"/item/", r"/asset/", r"/archive/"),
            deny=(r"blocked", r"forbidden", r"reject"),
            allow_domains=("allowed.example", "mirror.allowed.example"),
            deny_domains=("deny.allowed.example", "spam.allowed.example"),
            deny_extensions=("pdf", "zip", "doc", "xls", "exe"),
            restrict_text=(r"keep", r"accept", r"approve"),
        )

        links = []
        for index, category in enumerate(categories):
            token = "".join(rng.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(13))
            serial = (index * rng.randrange(23, 113) + rng.randrange(211, 1999)) % 65537
            if category == 0:
                url = f"javascript:void({serial})"
                text = f"keep-{token}"
            elif category == 1:
                url = f"https://allowed.example/other/{token}?n={serial}&reject=1"
                text = f"keep-{token}"
            elif category == 2:
                url = f"https://allowed.example/item/forbidden-{token}?n={serial}"
                text = f"keep-{token}"
            elif category == 3:
                url = f"https://outside.example/item/{token}?n={serial}"
                text = f"keep-{token}"
            elif category == 4:
                url = f"https://spam.allowed.example/item/{token}?n={serial}"
                text = f"keep-{token}"
            elif category == 5:
                extension = ("pdf", "zip", "doc", "xls", "exe")[(serial + index) % 5]
                url = f"https://allowed.example/asset/{token}.{extension}?n={serial}"
                text = f"keep-{token}"
            elif category == 6:
                url = f"https://allowed.example/item/{token}?n={serial}"
                text = f"discard-{token}"
            else:
                url = f"https://allowed.example/item/{token}?n={serial}"
                text = ("keep-", "accept-", "approve-")[(serial + index) % 3] + token
            links.append(Link(url=url, text=text))

        outcomes = [extractor._link_allowed(link) for link in links]

        self.assertEqual(len(outcomes), len(links))
        self.assertTrue(any(outcomes))
        self.assertFalse(all(outcomes))