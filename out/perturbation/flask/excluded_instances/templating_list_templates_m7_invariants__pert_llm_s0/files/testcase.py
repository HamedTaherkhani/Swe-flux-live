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
        rng = random.Random(0xFACEFEED)
        alphabet = string.ascii_lowercase + string.digits

        def make_names(group, amount):
            names = []
            rolling = rng.randrange(1, 15)
            for index in range(amount):
                width = 2 + (rolling + rng.randrange(0, 6)) % 5
                token = "".join(rng.choice(alphabet) for _ in range(width))
                rolling = (rolling * 7 + ord(token[-1]) + index) % 31
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
        for ordinal in range(len("chromaticspectrum")):
            blueprint = Blueprint(f"generated_{ordinal}", __name__)
            amount = sum(rng.randrange(5, 12) for _ in range(8))
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
