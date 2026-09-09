import random
import string
import unittest

from flask import Blueprint
from flask import Flask
from flask.templating import DispatchingJinjaLoader
from jinja2 import BaseLoader


class GeneratedTemplateLoader(BaseLoader):
    def __init__(self, names):
        self._names = tuple(names)

    def list_templates(self):
        return list(self._names)


class TestDispatchingLoaderInvariants(unittest.TestCase):
    def test_seeded_template_inventory(self):
        rng = random.Random(0x71A5EED)
        alphabet = string.ascii_lowercase

        def make_names(group, amount):
            names = []
            rolling = rng.randrange(1, 9)
            for index in range(amount):
                width = 2 + (rolling + rng.randrange(0, 4)) % 4
                token = "".join(rng.choice(alphabet) for _ in range(width))
                rolling = (rolling * 5 + ord(token[-1]) + index) % 23
                names.append(f"{group}/{token}-{index:x}.j")
            if rolling % 2:
                names.reverse()
            else:
                shift = rolling % len(names)
                names[:] = names[shift:] + names[:shift]
            return names

        app = Flask(__name__)
        app.jinja_loader = GeneratedTemplateLoader(
            make_names("app", sum(rng.randrange(3, 7) for _ in "root"))
        )

        inventories = []
        for ordinal in range(len("azure")):
            blueprint = Blueprint(f"generated_{ordinal}", __name__)
            amount = sum(rng.randrange(2, 6) for _ in range(3))
            inventory = make_names(f"g{ordinal}", amount)
            inventories.append(inventory)
            blueprint.jinja_loader = GeneratedTemplateLoader(inventory)
            app.register_blueprint(blueprint)

        templates = DispatchingJinjaLoader(app).list_templates()

        expected_members = {
            name
            for inventory in inventories
            for name in inventory
        }
        self.assertTrue(expected_members.issubset(set(templates)))
        self.assertEqual(len(templates), len(set(templates)))
        self.assertTrue(all(name.endswith(".j") for name in templates))
