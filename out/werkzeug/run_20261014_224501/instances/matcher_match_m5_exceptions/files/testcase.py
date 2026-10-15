import random
import string
import unittest

from werkzeug.routing import BaseConverter, Map, Rule


class HexConverter(BaseConverter):
    regex = "[0-9a-z]+"

    def to_python(self, value):
        return int(value, 16)


class LookupConverter(BaseConverter):
    regex = "[a-z]{2,5}"
    table = {"red": 1, "blue": 2, "green": 3}

    def to_python(self, value):
        try:
            return self.table[value]
        except KeyError:
            return len(value) * 10


def _run(adapter, cases):
    """Match each (path, kwargs) and record a generic outcome per case."""
    outcomes = []
    for path, kwargs in cases:
        try:
            adapter.match(path, **kwargs)
        except Exception:  # noqa: BLE001 - outcome recorded generically
            outcomes.append(("err", None))
        else:
            outcomes.append(("ok", None))
    return outcomes


def _word(rng, lo=3, hi=6):
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(lo, hi)))


class MatcherExceptionScenarios(unittest.TestCase):
    def test_static_hits_only(self):
        rng = random.Random(11)
        words = sorted({_word(rng) for _ in range(18)})
        m = Map([Rule(f"/{w}/{w[::-1]}", endpoint=w) for w in words])
        adapter = m.bind("example.org", "/")
        cases = [(f"/{w}/{w[::-1]}", {}) for w in words for _ in range(1)]
        out = _run(adapter, cases)
        self.assertTrue(all(o[0] == "ok" for o in out))
        self.assertEqual(len(out), len(words))

    def test_int_bounds(self):
        rng = random.Random(23)
        m = Map([Rule("/item/<int(min=10, max=60):n>", endpoint="item")])
        adapter = m.bind("example.org", "/")
        cases = [(f"/item/{rng.randint(0, 90)}", {}) for _ in range(17)]
        out = _run(adapter, cases)
        self.assertEqual(len(out), 17)
        self.assertTrue(any(o[0] == "ok" for o in out))

    def test_fixed_digits(self):
        rng = random.Random(37)
        m = Map(
            [
                Rule("/code/<int(fixed_digits=4):c>", endpoint="code"),
                Rule("/code/<int(fixed_digits=4):c>/<int(fixed_digits=2):d>", endpoint="cd"),
            ]
        )
        adapter = m.bind("example.org", "/")
        cases = []
        for _ in range(14):
            c = "".join(rng.choice("0123456789") for _ in range(rng.randint(3, 5)))
            if rng.random() < 0.4:
                d = "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 3)))
                cases.append((f"/code/{c}/{d}", {}))
            else:
                cases.append((f"/code/{c}", {}))
        out = _run(adapter, cases)
        self.assertEqual(len(out), 14)

    def test_strict_slash_redirects(self):
        rng = random.Random(41)
        names = sorted({_word(rng, 4, 5) for _ in range(9)})
        rules = []
        for i, n in enumerate(names):
            rules.append(Rule(f"/{n}/", endpoint=n, strict_slashes=(i % 3 != 0)))
        m = Map(rules)
        adapter = m.bind("example.org", "/")
        cases = []
        for i, n in enumerate(names):
            cases.append((f"/{n}" if i % 2 == 0 else f"/{n}/", {}))
        out = _run(adapter, cases)
        self.assertEqual(len(out), len(names))
        self.assertTrue(any(o[0] == "err" for o in out))

    def test_merge_slashes(self):
        rng = random.Random(53)
        rules = [
            Rule("/a/b/<x>", endpoint="ab"),
            Rule("/keep/<x>", endpoint="keep", merge_slashes=False),
            Rule("/c/", endpoint="c"),
        ]
        m = Map(rules)
        adapter = m.bind("example.org", "/")
        prefixes = ["/a//b/", "/a/b/", "/keep//", "//keep/", "/c//", "/zz//"]
        cases = [(rng.choice(prefixes) + _word(rng, 2, 3), {}) for _ in range(15)]
        out = _run(adapter, cases)
        self.assertEqual(len(out), 15)

    def test_method_mismatch(self):
        rng = random.Random(67)
        m = Map(
            [
                Rule("/res/<int:i>", endpoint="get", methods=["GET"]),
                Rule("/res/<int:i>", endpoint="put", methods=["PUT"]),
                Rule("/res/new", endpoint="post", methods=["POST"]),
            ]
        )
        adapter = m.bind("example.org", "/")
        methods = ["GET", "PUT", "POST", "DELETE", "PATCH"]
        cases = []
        for _ in range(16):
            tail = "new" if rng.random() < 0.3 else str(rng.randint(1, 999))
            cases.append((f"/res/{tail}", {"method": rng.choice(methods)}))
        out = _run(adapter, cases)
        self.assertEqual(len(out), 16)

    def test_websocket_mismatch(self):
        rng = random.Random(79)
        m = Map(
            [
                Rule("/ws/<name>", endpoint="ws", websocket=True),
                Rule("/http/<name>", endpoint="http"),
                Rule("/both/<name>", endpoint="bws", websocket=True),
                Rule("/both/<name>", endpoint="bhttp"),
            ]
        )
        cases = []
        for _ in range(14):
            kind = rng.choice(["ws", "http", "both"])
            cases.append((f"/{kind}/{_word(rng)}", {"websocket": rng.random() < 0.5}))
        adapter = m.bind("example.org", "/")
        out = _run(adapter, cases)
        self.assertEqual(len(out), 14)

    def test_alias_redirects(self):
        rng = random.Random(83)
        m = Map(
            [
                Rule("/page/<int:n>", endpoint="page"),
                Rule("/p/<int:n>", endpoint="page", alias=True),
                Rule("/p/<int:n>/<int:m>", endpoint="page2", alias=True),
                Rule("/page/<int:n>/<int:m>", endpoint="page2"),
            ]
        )
        adapter = m.bind("example.org", "/")
        cases = []
        for _ in range(13):
            pre = rng.choice(["page", "p"])
            nums = "/".join(str(rng.randint(1, 50)) for _ in range(rng.randint(1, 3)))
            cases.append((f"/{pre}/{nums}", {}))
        out = _run(adapter, cases)
        self.assertEqual(len(out), 13)

    def test_hex_converter(self):
        rng = random.Random(97)
        m = Map([Rule("/hex/<hex:h>", endpoint="hex")], converters={"hex": HexConverter})
        adapter = m.bind("example.org", "/")
        alphabet = "0123456789abcdefghk"
        cases = [
            ("/hex/" + "".join(rng.choice(alphabet) for _ in range(rng.randint(2, 4))), {})
            for _ in range(15)
        ]
        out = _run(adapter, cases)
        self.assertEqual(len(out), 15)
        self.assertTrue(any(o[0] == "err" for o in out))

    def test_lookup_converter(self):
        rng = random.Random(101)
        m = Map(
            [Rule("/color/<look:c>", endpoint="color")],
            converters={"look": LookupConverter},
        )
        adapter = m.bind("example.org", "/")
        pool = ["red", "blue", "green", "teal", "ab", "pink", "toolong", "x"]
        cases = [(f"/color/{rng.choice(pool)}", {}) for _ in range(16)]
        out = _run(adapter, cases)
        self.assertEqual(len(out), 16)

    def test_missing_paths(self):
        rng = random.Random(113)
        known = sorted({_word(rng, 3, 4) for _ in range(6)})
        m = Map([Rule(f"/{k}", endpoint=k) for k in known])
        adapter = m.bind("example.org", "/")
        cases = []
        for _ in range(18):
            if rng.random() < 0.45:
                cases.append((f"/{rng.choice(known)}", {}))
            else:
                cases.append((f"/{_word(rng, 3, 4)}", {}))
        out = _run(adapter, cases)
        self.assertEqual(len(out), 18)

    def test_float_and_path(self):
        rng = random.Random(127)
        m = Map(
            [
                Rule("/f/<float(max=5.0):v>", endpoint="f"),
                Rule("/files/<path:p>", endpoint="files"),
                Rule("/files/<path:p>/edit/", endpoint="edit"),
            ]
        )
        adapter = m.bind("example.org", "/")
        cases = []
        for _ in range(15):
            r = rng.random()
            if r < 0.4:
                cases.append((f"/f/{rng.randint(0, 9)}.{rng.randint(0, 9)}", {}))
            elif r < 0.7:
                segs = "/".join(_word(rng, 1, 3) for _ in range(rng.randint(1, 3)))
                cases.append((f"/files/{segs}", {}))
            else:
                segs = "/".join(_word(rng, 1, 3) for _ in range(rng.randint(1, 2)))
                cases.append((f"/files/{segs}/edit", {}))
        out = _run(adapter, cases)
        self.assertEqual(len(out), 15)

    def test_host_matching(self):
        rng = random.Random(131)
        hosts = ["alpha.test", "beta.test", "gamma.test"]
        m = Map(
            [
                Rule("/", endpoint="root", host="alpha.test"),
                Rule("/dash/", endpoint="dash", host="beta.test"),
                Rule("/n/<int(max=20):n>", endpoint="n", host="<sub>.test"),
            ],
            host_matching=True,
        )
        cases = []
        for _ in range(14):
            host = rng.choice(hosts)
            path = rng.choice(["/", "/dash", "/dash/", f"/n/{rng.randint(0, 40)}"])
            cases.append((host, path))
        outcomes = []
        for host, path in cases:
            adapter = m.bind(host, "/")
            outcomes.extend(_run(adapter, [(path, {})]))
        self.assertEqual(len(outcomes), 14)
