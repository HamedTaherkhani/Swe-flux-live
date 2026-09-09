import random
import unittest

from flask import Blueprint
from flask import Flask


class TestBlueprintMergeRuntime(unittest.TestCase):
    def test_repeated_registration_call_path(self) -> None:
        rng = random.Random(8675309)
        app = Flask(__name__)
        blueprint = Blueprint("generated", __name__)

        route_ids = list(range(29))
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
            type(f"GeneratedProblem{index}", (Exception,), {})
            for index in rng.sample(range(100, 200), 19)
        ]

        for index, exception_type in enumerate(exception_types):
            def handler(error, marker=index):
                return str(marker + len(type(error).__name__)), 500

            blueprint.register_error_handler(exception_type, handler)

        for index in range(17):
            blueprint.before_request(
                lambda marker=index: None if marker % 2 else None
            )
            blueprint.after_request(lambda response, marker=index: response)

        registration_names = [
            f"mount_{value}"
            for value in rng.sample(range(200, 900), 4)
        ]
        for name in registration_names:
            app.register_blueprint(blueprint, name=name)

        self.assertGreater(len(app.url_map._rules), len(route_ids) * 3)
        self.assertEqual(set(registration_names), set(app.blueprints))
