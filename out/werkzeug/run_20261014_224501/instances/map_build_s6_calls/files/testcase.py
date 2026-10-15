import random
import unittest

from werkzeug.routing import BaseConverter
from werkzeug.routing import Map
from werkzeug.routing import RequestRedirect
from werkzeug.routing import Rule
from werkzeug.routing import ValidationError


class PickyConverter(BaseConverter):
    """Matches digits; refuses to serialize multiples of 3 or 5."""

    regex = r"\d+"

    def to_python(self, value):
        return int(value)

    def to_url(self, value):
        if value % 3 == 0 or value % 5 == 0:
            raise ValidationError()
        return str(value)


HOSTS = ["main.test", "mirror.test", "cdn.test"]
METHOD_CHOICES = [None, ["GET"], ["POST"], ["GET", "POST"], ["PUT"]]


def make_url_map(rng):
    rules = []
    for i in range(8):
        endpoint = f"ep{i}"
        rules.append(
            Rule(f"/a{i}/<int:n>", endpoint=endpoint, host="main.test", alias=True)
        )
        for j in range(rng.randint(3, 6)):
            conv = rng.choice(["int", "picky", "picky", "slug"])
            host = rng.choice(HOSTS)
            methods = rng.choice(METHOD_CHOICES)
            if conv == "slug":
                path = f"/c{i}_{j}/<int:n>/<slug>"
            else:
                path = f"/c{i}_{j}/<{conv}:n>"
            rules.append(Rule(path, endpoint=endpoint, host=host, methods=methods))
    return Map(rules, host_matching=True, converters={"picky": PickyConverter})


class TestAliasRedirectBuild(unittest.TestCase):
    def test_alias_redirects(self):
        rng = random.Random(2718)
        url_map = make_url_map(rng)
        adapter = url_map.bind("main.test")
        redirects = []
        for _ in range(18):
            i = rng.randrange(8)
            n = rng.randint(1, 40)
            method = rng.choice(["GET", "POST"])
            with self.assertRaises(RequestRedirect) as ctx:
                adapter.match(f"/a{i}/{n}", method=method)
            redirects.append(ctx.exception.new_url)
        self.assertEqual(len(redirects), 18)
        self.assertTrue(all("//" in u for u in redirects))
        self.assertTrue(any("main.test" in u for u in redirects))
