import random
import unittest

from flask import Blueprint
from flask import Flask


class TestBlueprintMergeRuntime(unittest.TestCase):
    def test_repeated_registration_call_path(self) -> None:
        rng = random.Random(1618033988)
        app = Flask(__name__)
        blueprint = Blueprint("generated", __name__)

        route_ids = list(range(53))
        rng.shuffle(route_ids)

        for position, route_id in enumerate(route_ids):
            endpoint = f"route_{route_id}_{position}"

            def view(value=route_id):
                return str((value * value + position) % len(route_ids))

            blueprint.add_url_rule(
                f"/item/{route_id}/{position}",
                endpoint=endpoint,
                view_func=view,
            )

        exception_types = [
            400, 401, 403, 404, 405, 406, 408, 409, 410, 411, 412, 413, 414,
            415, 416, 417, 418, 422, 429, 500, 501, 502, 503,
        ] + [
            type(f"GeneratedProblem{index}", (Exception,), {})
            for index in rng.sample(range(10, 320), 42)
        ]

        for index, exception_type in enumerate(exception_types):
            def handler(error, marker=index):
                return str(marker + len(type(error).__name__)), 500

            blueprint.register_error_handler(exception_type, handler)

        for index in range(37):
            blueprint.before_request(
                lambda marker=index: None if marker % 2 else None
            )
            blueprint.after_request(lambda response, marker=index: response)

        registration_names = [
            f"mount_{value}"
            for value in rng.sample(range(80, 990), 9)
        ]
        for name in registration_names:
            app.register_blueprint(blueprint, name=name)

        self.assertGreater(len(app.url_map._rules), len(route_ids) * 3)
        self.assertEqual(set(registration_names), set(app.blueprints))
