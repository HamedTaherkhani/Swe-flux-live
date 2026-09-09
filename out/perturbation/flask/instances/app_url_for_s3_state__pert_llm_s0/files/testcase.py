import random
import string
import unittest

from flask import Blueprint
from flask import Flask


class TestAppUrlForProgramState(unittest.TestCase):
    def test_computed_blueprint_urls(self):
        rng = random.Random(948_314)

        def word(length):
            alphabet = string.ascii_lowercase + string.digits + "-_%"
            return "".join(rng.choice(alphabet) for _ in range(length))

        blueprint_name = word(11)
        endpoint_name = word(13)
        prefix = "/" + word(9)
        landing_rule = "/" + word(12)
        item_rule = "/".join(
            ("/" + word(8), "<int:item_id>", "<slug>", word(5))
        )

        app = Flask(__name__)
        app.config.update(
            SERVER_NAME="api.example.test",
            PREFERRED_URL_SCHEME="https",
            APPLICATION_ROOT="/myapp",
        )
        blueprint = Blueprint(blueprint_name, __name__, url_prefix=prefix)
        blueprint.add_url_rule(landing_rule, endpoint="landing", view_func=lambda: "")
        blueprint.add_url_rule(
            item_rule,
            endpoint=endpoint_name,
            view_func=lambda item_id, slug: f"{item_id}:{slug}",
            methods=("GET", "POST", "PUT"),
        )

        @app.url_defaults
        def add_computed_defaults(endpoint, values):
            if endpoint.rpartition(".")[2] != endpoint_name:
                return
            material = endpoint + "|" + str(values.get("item_id")) + "|" + values["slug"]
            checksum = sum((index + 3) * ord(char) for index, char in enumerate(material))
            values.setdefault("signature", format(checksum ^ 0x7B3C, "x"))
            values.setdefault("phase", (checksum % 13) + len(values["slug"]))

        app.register_blueprint(blueprint)
        relative_endpoint = "." + endpoint_name
        request_path = prefix + landing_rule
        results = []

        with app.test_request_context(request_path):
            rolling = rng.randrange(450, 1500)
            for index in range(52):
                rolling = (rolling * 43 + rng.randrange(29, 401) + index * index * 5) % 10013
                slug_parts = [
                    word(3 + ((rolling + offset) % 8))
                    for offset in range(2 + (index % 7))
                ]
                slug = "-".join(slug_parts)
                anchor_raw = " / ".join(
                    (
                        word(4 + (index % 5)),
                        str((rolling * (index + 9)) % 2999),
                        word(5 + (index % 4)),
                        ("#&?%!" if (rolling + index) % 6 == 0 else word(4)),
                    )
                )
                method = (
                    "PUT"
                    if (rolling + index) % 7 == 0
                    else (
                        "POST"
                        if (rolling + index) % 5 == 0
                        else (None if (rolling + index) % 11 == 0 else "GET")
                    )
                )
                results.append(
                    app.url_for(
                        relative_endpoint,
                        _anchor=anchor_raw,
                        _method=method,
                        _external=(
                            None
                            if (rolling + index) % 9 == 0
                            else (True if (rolling + index) % 5 == 0 else False)
                        ),
                        item_id=rolling + index * 19,
                        slug=slug,
                        batch=(rolling ^ index) % 97,
                    )
                )

        self.assertEqual(len(results), len(set(results)))
        self.assertTrue(all("#" in result and "signature=" in result for result in results))
        self.assertGreater(sum(map(len, results)), len(results) ** 2)
