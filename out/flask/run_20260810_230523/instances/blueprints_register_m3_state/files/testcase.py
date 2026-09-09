import random
import unittest

from flask import Blueprint
from flask import Flask


class TestBlueprintRegisterState(unittest.TestCase):
    def test_generated_nested_options(self) -> None:
        rng = random.Random(0xB10E)
        app = Flask(__name__)
        callback_observations = []
        roots = []

        for root_index in range(4):
            root_token = rng.randrange(10**5, 10**6)
            root = Blueprint(
                f"root_{root_index}_{root_token:x}",
                __name__,
                url_prefix=(
                    f"/base-{(root_token * 7) % 997}"
                    if root_index in {1, 2}
                    else None
                ),
                subdomain=(
                    f"zone-{(root_token * 11) % 991}"
                    if root_index in {1, 3}
                    else None
                ),
            )

            for callback_index in range(19):
                marker = (root_token ^ (callback_index * 131)) % 1009
                root.record(
                    lambda state, marker=marker: callback_observations.append(
                        (state.name, marker, state.url_prefix, state.subdomain)
                    )
                )

            for child_index in range(18):
                child_token = rng.randrange(10**6, 10**8)
                child = Blueprint(
                    f"child_{root_index}_{child_index}_{child_token:x}",
                    __name__,
                    url_prefix=(
                        f"/leaf-{(child_token * 13) % 1237}"
                        if child_index % 4 in {0, 1}
                        else None
                    ),
                    subdomain=(
                        f"node-{(child_token * 17) % 1213}"
                        if child_index % 5 in {0, 2}
                        else None
                    ),
                )
                child_options = {}

                if child_index % 3 == 0:
                    child_options["url_prefix"] = (
                        f"/override-{(child_token // 7) % 1291}"
                    )
                elif child_index % 3 == 1:
                    child_options["url_prefix"] = None

                if child_index % 4 == 0:
                    child_options["subdomain"] = (
                        f"edge-{(child_token // 11) % 1301}"
                    )
                elif child_index % 4 == 1:
                    child_options["subdomain"] = None

                if (child_token + child_index) % 2:
                    child_options["name"] = (
                        f"alias_{child_index}_{(child_token ^ root_token) % 1321}"
                    )

                root.register_blueprint(child, **child_options)

            root_options = {}

            if root_index == 0:
                root_options["url_prefix"] = f"/entry-{root_token % 1361}"
                root_options["subdomain"] = f"hub-{root_token % 1327}"
            elif root_index == 2:
                root_options["subdomain"] = None
            elif root_index == 3:
                root_options["url_prefix"] = None

            roots.append((root, root_options))

        for root, root_options in roots:
            Blueprint.register(root, app, root_options)

        self.assertTrue(callback_observations)
        self.assertEqual(len({item[0] for item in callback_observations}), len(roots))
        self.assertGreater(len(app.blueprints), len(roots))
