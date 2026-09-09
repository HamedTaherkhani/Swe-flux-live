import random
import string
import unittest

from flask import Blueprint
from flask import Flask


class TestAppUrlForProgramState(unittest.TestCase):
    def test_computed_blueprint_urls(self):
        rng = random.Random(731_927)

        def word(length):
            alphabet = string.ascii_lowercase
            return "".join(rng.choice(alphabet) for _ in range(length))

        blueprint_name = word(7)
        endpoint_name = word(9)
        prefix = "/" + word(6)
        landing_rule = "/" + word(8)
        item_rule = "/".join(
            ("/" + word(5), "<int:item_id>", "<slug>")
        )

        app = Flask(__name__)
        app.config.update(SERVER_NAME="example.test", PREFERRED_URL_SCHEME="https")
        blueprint = Blueprint(blueprint_name, __name__, url_prefix=prefix)
        blueprint.add_url_rule(landing_rule, endpoint="landing", view_func=lambda: "")
        blueprint.add_url_rule(
            item_rule,
            endpoint=endpoint_name,
            view_func=lambda item_id, slug: f"{item_id}:{slug}",
            methods=("GET", "POST"),
        )

        @app.url_defaults
        def add_computed_defaults(endpoint, values):
            if endpoint.rpartition(".")[2] != endpoint_name:
                return
            material = endpoint + "|" + str(values.get("item_id")) + "|" + values["slug"]
            checksum = sum((index + 3) * ord(char) for index, char in enumerate(material))
            values.setdefault("signature", format(checksum ^ 0x5A5A, "x"))
            values.setdefault("phase", (checksum % 11) + len(values["slug"]))

        app.register_blueprint(blueprint)
        relative_endpoint = "." + endpoint_name
        request_path = prefix + landing_rule
        results = []

        with app.test_request_context(request_path):
            rolling = rng.randrange(200, 900)
            for index in range(24):
                rolling = (rolling * 37 + rng.randrange(17, 211) + index * index) % 10007
                slug_parts = [
                    word(3 + ((rolling + offset) % 5))
                    for offset in range(2 + (index % 4))
                ]
                slug = "-".join(slug_parts)
                anchor_raw = " / ".join(
                    (
                        word(4 + (index % 3)),
                        str((rolling * (index + 5)) % 997),
                        word(5),
                    )
                )
                method = "POST" if (rolling + index) % 3 == 0 else "GET"
                results.append(
                    app.url_for(
                        relative_endpoint,
                        _anchor=anchor_raw,
                        _method=method,
                        _external=(index % 5 == 0),
                        item_id=rolling + index * 13,
                        slug=slug,
                        batch=(rolling ^ index) % 19,
                    )
                )

        self.assertEqual(len(results), len(set(results)))
        self.assertTrue(all("#" in result and "signature=" in result for result in results))
        self.assertGreater(sum(map(len, results)), len(results) ** 2)
