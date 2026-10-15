import random
import unittest

from werkzeug.routing import Map, Rule


def _make_rules(seed):
    rng = random.Random(seed)
    words = ["shop", "blog", "api", "docs", "user", "item", "tag", "feed"]
    hosts = ["<tenant>.example.org", "static.example.org", "<region>.<tenant>.cdn.net"]
    rules = []
    for i in range(14):
        host = hosts[rng.randrange(len(hosts))]
        segs = []
        names = []
        for j in range(rng.randint(1, 4)):
            if rng.random() < 0.45:
                name = f"v{i}x{j}"
                conv = rng.choice(["int", "string", "path"])
                segs.append(f"<{conv}:{name}>" if conv != "string" else f"<{name}>")
                names.append((name, conv))
            else:
                segs.append(rng.choice(words) + ("~" if rng.random() < 0.3 else ""))
        defaults = {}
        for name, conv in names:
            if conv == "int" and rng.random() < 0.5:
                defaults[name] = rng.randint(1, 9)
        if rng.random() < 0.3:
            defaults["lang"] = "en"
        rule = "/" + "/".join(segs)
        if rng.random() < 0.25:
            rule += "/"
        rules.append(
            Rule(rule, host=host, endpoint=f"ep{i}", defaults=defaults or None)
        )
    return rules


class CompileBuilderDataFlowTest(unittest.TestCase):
    def test_host_rules_build(self):
        rules = _make_rules(20240611)
        url_map = Map(rules, host_matching=True)
        adapter = url_map.bind("static.example.org")
        built = 0
        for rule in rules:
            values = {}
            for arg in sorted(rule.arguments):
                if arg in (rule.defaults or {}):
                    continue
                conv = rule._converters.get(arg)
                if conv is not None and type(conv).__name__ == "IntegerConverter":
                    values[arg] = 7
                else:
                    values[arg] = "z"
            try:
                url = adapter.build(rule.endpoint, values, force_external=True)
            except Exception:
                continue
            self.assertTrue(url.startswith("http://"))
            built += 1
        self.assertGreater(built, 0)
        self.assertEqual(len(url_map._rules), len(rules))
