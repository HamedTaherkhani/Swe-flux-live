import random
import unittest

from flask import Flask
from jinja2 import BaseLoader
from jinja2 import TemplateNotFound


class VariableMetadataLoader(BaseLoader):
    def __init__(self, seed, slot):
        rng = random.Random(seed ^ (slot * 0x9E3779B1))

        for group in range(2 + slot % 4):
            item_count = 12 + rng.randrange(31)
            values = [
                "".join(
                    chr(97 + (rng.randrange(26) + item * 7 + offset * 3) % 26)
                    for offset in range(5 + (item + group) % 6)
                )
                for item in range(item_count)
            ]
            container = tuple(values) if (slot + group) % 2 else values
            setattr(self, f"search_group_{group:02d}", container)

        self.display_name = "".join(
            chr(65 + rng.randrange(26)) for _ in range(7 + slot % 5)
        )
        self.revision = sum(rng.randrange(1000) for _ in range(3 + slot % 3))
        self.enabled = slot % 3 != 1
        self.unsupported_mapping = {"slot": slot}
        self.mixed_entries = ["valid", slot, "also-valid"]
        self._private_entries = [str(rng.randrange(10000)) for _ in range(40)]

    def get_source(self, environment, template):
        raise TemplateNotFound(template)


class TestLoaderInfoLoopDynamics(unittest.TestCase):
    def test_seeded_loader_metadata(self):
        app = Flask(__name__)
        app.config["EXPLAIN_TEMPLATE_LOADING"] = True
        slots = list(range(len("tracepaths")))
        random.Random(0xC0FFEE).shuffle(slots)

        observed_names = set()
        for ordinal, slot in enumerate(slots):
            app.jinja_loader = VariableMetadataLoader(0x5EEDFACE, slot)
            template_name = "".join(
                chr(97 + ((slot * 13 + ordinal * 7 + index * index) % 26))
                for index in range(9 + slot % 7)
            )
            template_name = f"{ordinal}-{template_name}.html"

            with self.assertRaises(TemplateNotFound) as caught:
                app.jinja_env.get_template(template_name)

            self.assertEqual(caught.exception.name, template_name)
            observed_names.add(template_name)

        self.assertEqual(len(observed_names), len(slots))
        self.assertTrue(all(name.endswith(".html") for name in observed_names))
