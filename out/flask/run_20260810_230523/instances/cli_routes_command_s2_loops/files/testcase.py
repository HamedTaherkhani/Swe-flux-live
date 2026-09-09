import io
import random
import unittest
from contextlib import redirect_stdout

from flask import Flask
from flask.cli import routes_command


class RoutesCommandLoopTest(unittest.TestCase):
    def test_generated_route_table(self) -> None:
        rng = random.Random(8675309)
        app = Flask(__name__, static_folder=None)

        rolling = rng.randrange(1000, 9000)
        route_specs = []

        for index in range(rng.randrange(60, 90)):
            draw = rng.randrange(1, 10_000)
            rolling = (rolling * 37 + draw + index * index) % 104_729

            if (rolling ^ draw) % 7 not in {0, 2}:
                methods = ["GET"]

                if rolling % 3 == 0:
                    methods.append("POST")

                if (rolling + index) % 5 == 0:
                    methods.append("PATCH")

                route_specs.append(
                    (
                        f"generated_{index}_{rolling:x}",
                        f"/generated/{index}/<int:item_{index}>",
                        methods,
                        f"zone-{(rolling + draw) % 11}" if index % 4 else "",
                    )
                )

        for endpoint, rule, methods, subdomain in route_specs:
            app.add_url_rule(
                rule,
                endpoint=endpoint,
                view_func=lambda **values: str(sum(values.values())),
                methods=methods,
                subdomain=subdomain,
            )

        sort_options = ("endpoint", "methods", "domain", "rule", "match")
        sort_key = sort_options[(rolling + len(route_specs)) % len(sort_options)]
        include_implicit = bool((rolling ^ len(route_specs)) & 1)
        output = io.StringIO()

        with app.app_context(), redirect_stdout(output):
            routes_command.callback.__wrapped__(
                sort=sort_key, all_methods=include_implicit
            )

        rendered = output.getvalue()
        self.assertIn("Endpoint", rendered)
        self.assertIn("Methods", rendered)
        self.assertIn("generated_", rendered)
        self.assertGreater(len(rendered.splitlines()), len(route_specs))
