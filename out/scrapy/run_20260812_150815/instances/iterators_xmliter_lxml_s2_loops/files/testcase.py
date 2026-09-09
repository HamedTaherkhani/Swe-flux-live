from __future__ import annotations

import random
import unittest

from scrapy.utils.iterators import xmliter_lxml


class XmlIterLoopTest(unittest.TestCase):
    def test_generated_namespaced_catalog(self):
        rng = random.Random(814_729)
        fragments = [
            '<catalog xmlns:z="urn:catalog:noise" '
            'xmlns:q="urn:catalog:primary">'
        ]
        expected_codes = []

        for group_index in range(29):
            namespace_attr = (
                f' xmlns:n{group_index}="urn:generated:{rng.randrange(10_000, 99_999)}"'
                if rng.randrange(4) != 0
                else ""
            )
            fragments.append(f"<group{namespace_attr}>")
            for record_index in range(3 + rng.randrange(6)):
                code = f"{group_index:x}-{record_index:x}-{rng.randrange(1_000, 9_999):x}"
                is_target = (rng.randrange(11) + group_index + record_index) % 4 != 0
                tag = "q:item" if is_target else "entry"
                fragments.append(f'<{tag} code="{code}">')
                fragments.append(f"<label>{rng.randrange(100_000, 999_999)}</label>")
                for field_index in range(1 + rng.randrange(5)):
                    value = rng.randrange(1_000_000, 9_999_999) ^ (
                        group_index * 257 + record_index * 17 + field_index
                    )
                    fragments.append(
                        f'<field rank="{field_index}">{value}</field>'
                    )
                if rng.randrange(3) == 0:
                    fragments.append(
                        f"<note><part>{rng.randrange(10_000, 99_999)}</part></note>"
                    )
                fragments.append(f"</{tag}>")
                if is_target:
                    expected_codes.append(code)
            fragments.append("</group>")
        fragments.append("</catalog>")

        document = "".join(fragments)
        selected = list(xmliter_lxml(document, "q:item"))
        actual_codes = [selector.xpath("@code").get() for selector in selected]

        self.assertEqual(actual_codes, expected_codes)
        self.assertGreater(len(selected), len(set(code.split("-")[0] for code in expected_codes)))
