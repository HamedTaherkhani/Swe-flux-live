import random
import unittest

from lxml import etree

from scrapy.utils.sitemap import Sitemap


class SitemapElementLoopTest(unittest.TestCase):
    def test_programmatic_siblings_and_children(self):
        sibling_rng = random.Random(
            sum((position + 3) * ord(character) for position, character in enumerate("sitemap"))
        )
        parent = etree.Element("urlset")
        rolling = sibling_rng.randrange(101)
        for index in range(67):
            draw = sibling_rng.randrange(10_000)
            rolling = (rolling * 37 + draw + index * index) % 997
            if (draw ^ rolling ^ (index * 29)) % 11 not in {0, 3, 8}:
                sibling = etree.SubElement(parent, "noise")
                sibling.text = str((rolling + draw) % 313)

        target = etree.SubElement(parent, "url")
        child_rng = random.Random(rolling ^ sibling_rng.randrange(1 << 16))
        loc_added = False
        for index in range(59):
            selector = (index * index + child_rng.randrange(23) + rolling) % 9
            if selector == 0:
                target.append(etree.Comment(f"generated-{index}"))
            elif selector in {1, 2}:
                link = etree.SubElement(target, "{http://www.w3.org/1999/xhtml}link")
                if (child_rng.randrange(31) + index + rolling) % 4:
                    link.set("href", f"https://mirror.invalid/{index:x}/{rolling % 17}")
            elif selector == 3 and not loc_added:
                loc = etree.SubElement(target, "loc")
                loc.text = f"  https://example.invalid/{rolling:x}/{index:x}  "
                loc_added = True
            else:
                field = etree.SubElement(target, ("lastmod", "changefreq", "priority")[selector % 3])
                field.text = f" value-{(rolling + index * 13) % 101} "

        if not loc_added:
            loc = etree.SubElement(target, "loc")
            loc.text = f"https://example.invalid/fallback/{rolling:x}"

        sitemap = Sitemap.__new__(Sitemap)
        result = Sitemap._process_sitemap_element(sitemap, target)

        self.assertIsNotNone(result)
        self.assertIn("loc", result)
        self.assertGreater(len(result), 2)
        self.assertIs(target.getparent(), parent)
        self.assertEqual(list(target), [])
