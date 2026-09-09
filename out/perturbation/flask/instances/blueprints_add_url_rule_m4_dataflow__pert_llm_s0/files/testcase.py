import random
import unittest

from flask import Blueprint, Flask


class TestGeneratedBlueprintRegistration(unittest.TestCase):
    def test_registers_generated_rule_matrix(self) -> None:
        rng = random.Random(3_141_592_653)
        app = Flask("_".join(("generated", "blueprint", "matrix", "stress")))
        blueprint_count = 15
        rules_per_blueprint = 47

        for group in range(blueprint_count):
            prefix = None
            if group != blueprint_count - 1:
                prefix_parts = [
                    format(rng.randrange(2**10, 2**20), "x"),
                    str((group + 11) * (rng.randrange(3, 37))),
                ]
                prefix = "/" + "/".join(prefix_parts)
                if group % 2:
                    prefix += "/"

            blueprint = Blueprint(
                f"bp_{group}_{rng.randrange(8_192, 131_073)}",
                __name__,
                url_prefix=prefix,
                url_defaults={
                    "group_seed": rng.randrange(17, 4_097),
                    "batch_lane": (group * 37 + rng.randrange(512)) % 9_007,
                },
            )

            order = list(range(rules_per_blueprint))
            rng.shuffle(order)
            for position, item in enumerate(order):
                use_empty_rule = prefix is not None and (item + group) % 8 == 0
                rule = ""
                if not use_empty_rule:
                    fragments = [
                        format(rng.getrandbits(24), "x"),
                        str((item + 1) * (group + 9)),
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
                        "runtime_default": (token + item * 17) % 8_193,
                        "lane_shift": (token ^ position ^ group) % 1_024,
                    }
                if (token + item) % 5 == 0:
                    route_options["methods"] = ["GET", "HEAD", "POST", "OPTIONS"]

                blueprint.route(rule, **route_options)(generated_view)

            registration_options = {}
            if group == 1:
                registration_options["url_prefix"] = (
                    f"/override-{rng.getrandbits(21):x}-{group}"
                )
            app.register_blueprint(blueprint, **registration_options)

        dynamic_rules = [rule for rule in app.url_map.iter_rules()]
        self.assertGreater(len(dynamic_rules), blueprint_count * 15)
        self.assertEqual(len(app.blueprints), blueprint_count)
        self.assertTrue(all(rule.rule.startswith("/") for rule in dynamic_rules))
