import random
import unittest

from werkzeug.routing import Map, Rule


def _build_rules():
    rng = random.Random(1729)
    words = ["api", "v2", "shop", "a.b", "x+y", "docs", "media", "u"]
    converters = [
        "int",
        "int(signed=True)",
        "float",
        "string(length=3)",
        "path",
        "any(red, blue)",
        "default",
        "uuid",
    ]
    rules = []
    for idx in range(6):
        segments = []
        for seg_no in range(rng.randint(3, 5)):
            kind = rng.random()
            name = f"p{idx}{seg_no}"
            conv = rng.choice(converters)
            spec = name if conv == "default" else f"{conv}:{name}"
            if kind < 0.35:
                segments.append(rng.choice(words))
            elif kind < 0.7:
                segments.append(f"<{spec}>")
            else:
                segments.append(rng.choice(words) + f"-<{spec}>")
        path = "/" + "/".join(segments)
        if rng.random() < 0.5:
            path += "/"
        host = f"<h{idx}>." + rng.choice(["example.org", "ex-<int:port>.net"])
        rules.append(Rule(path, endpoint=f"ep{idx}", host=host))
    return rules


class TestHostRuleCompilation(unittest.TestCase):
    def test_compile_host_rules(self):
        rules = _build_rules()
        url_map = Map(rules, host_matching=True)
        compiled = list(url_map.iter_rules())
        self.assertEqual(len(compiled), 6)
        for rule in compiled:
            self.assertTrue(rule._parts)
            self.assertGreaterEqual(len(rule.arguments), 1)
        total_parts = sum(len(r._parts) for r in compiled)
        self.assertGreater(total_parts, 12)


if __name__ == "__main__":
    unittest.main()
