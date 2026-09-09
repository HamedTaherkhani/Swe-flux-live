import random
import unittest

from flask import Blueprint, Flask


class TestGeneratedBlueprintRegistration(unittest.TestCase):
    def test_registers_generated_rule_matrix(self) -> None:
        rng = random.Random(947_231)
        app = Flask("_".join(("generated", "blueprint", "matrix")))
        blueprint_count = 5
        rules_per_blueprint = 19

        for group in range(blueprint_count):
            prefix = None
            if group != blueprint_count - 1:
                prefix_parts = [
                    format(rng.randrange(2**12, 2**18), "x"),
                    str((group + 3) * (rng.randrange(7, 29))),
                ]
                prefix = "/" + "/".join(prefix_parts)
                if group % 2:
                    prefix += "/"

            blueprint = Blueprint(
                f"bp_{group}_{rng.randrange(4_096, 65_537)}",
                __name__,
                url_prefix=prefix,
                url_defaults={"group_seed": rng.randrange(131, 1_231)},
            )

            order = list(range(rules_per_blueprint))
            rng.shuffle(order)
            for position, item in enumerate(order):
                use_empty_rule = prefix is not None and (item + group) % 8 == 0
                rule = ""
                if not use_empty_rule:
                    fragments = [
                        format(rng.getrandbits(20), "x"),
                        str((item + 1) * (group + 5)),
                    ]
                    rule = "/" + "-".join(fragments)

                token = rng.getrandbits(31) ^ (item << (group % 5))

                def generated_view(
                    _token=token, _group=group, _position=position
                ) -> str:
                    return f"{_token ^ (_group + _position):x}"

                generated_view.__name__ = (
                    f"view_{group}_{item}_{token & 0xFFFF:x}"
                )
                route_options = {}
                if (token + position + group) % 3:
                    route_options["endpoint"] = (
                        f"ep_{group}_{item}_{(token >> 5) & 0x7FFF:x}"
                    )
                if (token ^ item ^ position) % 4:
                    route_options["defaults"] = {
                        "runtime_default": (token + item * 17) % 2_017
                    }
                if (token + item) % 5 == 0:
                    route_options["methods"] = ["GET", "POST"]

                blueprint.route(rule, **route_options)(generated_view)

            registration_options = {}
            if group == 1:
                registration_options["url_prefix"] = (
                    f"/override-{rng.getrandbits(17):x}"
                )
            app.register_blueprint(blueprint, **registration_options)

        dynamic_rules = [rule for rule in app.url_map.iter_rules()]
        self.assertGreater(len(dynamic_rules), blueprint_count * 15)
        self.assertEqual(len(app.blueprints), blueprint_count)
        self.assertTrue(all(rule.rule.startswith("/") for rule in dynamic_rules))
