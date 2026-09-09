import random
import unittest

from flask import Flask


class TestGeneratedRuleRegistration(unittest.TestCase):
    def test_registers_computed_rule_matrix(self) -> None:
        rng = random.Random(918_273)
        app_name_parts = ["qa", "routing", str(rng.randrange(1000, 9999))]
        app = Flask("-".join(app_name_parts), static_folder=None)
        registrations = []

        method_pool = ("get", "post", "put", "delete", "patch")
        required_pool = ("OPTIONS", "TRACE")

        for turn in range(28):
            samples = [
                (rng.randrange(37, 997) * (turn + index + 3) + index**3) % 1009
                for index in range(9)
            ]
            folded = sum(
                (index + 5) * (value ^ samples[index - 1])
                for index, value in enumerate(samples)
            )
            route_parts = [
                f"s{(value + folded + index * turn) % 211:03d}"
                for index, value in enumerate(samples[:4])
            ]
            route = "/" + "/".join(route_parts)
            endpoint_code = (
                folded * (turn + 11) + sum(value * value for value in samples)
            ) % 1_000_003

            def generated_view(marker=endpoint_code):
                return str(marker)

            generated_view.__name__ = f"handler_{turn:02d}_{endpoint_code:06d}"

            branch = (folded + samples[turn % len(samples)] + turn) % 6
            selected_methods = [
                method_pool[(samples[index] + turn + index) % len(method_pool)]
                for index in range(1 + branch % 3)
            ]
            selected_methods = list(dict.fromkeys(selected_methods))

            if branch in (0, 3):
                generated_view.methods = tuple(selected_methods)
            if branch in (1, 4):
                generated_view.required_methods = {
                    required_pool[(folded + turn) % len(required_pool)]
                }
            if branch == 2:
                generated_view.provide_automatic_options = bool(folded % 2)

            rule_options = {
                "defaults": {
                    "bucket": (sum(samples[::2]) * (turn + 7)) % 4093,
                    "token": f"d{(folded ^ samples[-1]) % 8191:04d}",
                },
                "subdomain": f"z{(samples[0] + samples[-1] + turn) % 17}",
            }
            if branch not in (0, 3):
                rule_options["methods"] = selected_methods

            automatic = (None, True, False)[
                (samples[-1] + folded + branch) % 3
            ]
            app.add_url_rule(
                route,
                view_func=generated_view,
                provide_automatic_options=automatic,
                **rule_options,
            )
            registrations.append((route, generated_view))

        self.assertEqual(len(app.url_map._rules), len(registrations))
        self.assertEqual(
            {rule.rule for rule in app.url_map.iter_rules()},
            {route for route, _view in registrations},
        )
        self.assertTrue(
            all(view in app.view_functions.values() for _route, view in registrations)
        )
