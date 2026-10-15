import random
import unittest

from werkzeug.exceptions import MethodNotAllowed
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map
from werkzeug.routing import RequestRedirect
from werkzeug.routing import Rule


def build_rules(rng):
    sections = ["shop", "blog", "api"]
    converters = ["int", "string", "float", "any(red,green,blue)", "path"]
    rules = []
    for s_idx, section in enumerate(sections):
        for k in range(4):
            conv_a = converters[(s_idx + k) % len(converters)]
            conv_b = rng.choice(converters[:3])
            if k % 2 == 0:
                rule = f"/{section}/<{conv_a}:a>/<{conv_b}:b>"
            else:
                rule = f"/{section}/<{conv_a}:a>/item-{k}/"
            methods = ["GET"] if (s_idx + k) % 3 else ["POST"]
            rules.append(
                Rule(rule, endpoint=f"{section}_{k}", methods=methods)
            )
    rules.append(Rule("/<string:lang>/<int:page>", endpoint="lang_page"))
    rules.append(Rule("/<path:rest>/end", endpoint="catch_end"))
    return rules


def build_paths(rng):
    pieces = ["7", "3.5", "red", "zz", "item-1", "item-3", "42", "x/y"]
    paths = []
    for section in ["shop", "blog", "api", "misc"]:
        for _ in range(3):
            a = rng.choice(pieces)
            b = rng.choice(pieces)
            paths.append(f"/{section}/{a}/{b}")
    paths.append("/blog/green/item-1")
    paths.append("/api//7/item-3/")
    paths.append("/en/12")
    return paths


class TestMatcherLoops(unittest.TestCase):
    def test_backtracking_dynamic_transitions(self):
        rng = random.Random(1337)
        url_map = Map(build_rules(rng), merge_slashes=True)
        adapter = url_map.bind("example.org", "/")
        outcomes = {"ok": 0, "notfound": 0, "method": 0, "redirect": 0}
        for path in build_paths(rng):
            try:
                endpoint, values = adapter.match(path, method="GET")
            except RequestRedirect:
                outcomes["redirect"] += 1
            except MethodNotAllowed:
                outcomes["method"] += 1
            except NotFound:
                outcomes["notfound"] += 1
            else:
                self.assertIsInstance(endpoint, str)
                self.assertIsInstance(values, dict)
                outcomes["ok"] += 1
        self.assertEqual(sum(outcomes.values()), 15)
        self.assertGreater(outcomes["ok"], 0)
        self.assertGreater(outcomes["notfound"] + outcomes["method"], 0)
