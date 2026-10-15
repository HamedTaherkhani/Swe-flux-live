import random
import unittest

from werkzeug.debug.repr import DebugReprGenerator


class Probe:
    """Object whose attribute listing and lookups are fully controlled."""

    def __init__(self, names, broken):
        self._names = list(names)
        self._broken = set(broken)

    def __dir__(self):
        return list(self._names)

    def __getattr__(self, name):
        if name in self._broken:
            raise LookupError(name)
        if name.startswith("_"):
            raise AttributeError(name)
        return len(name) * 3


class Plain:
    def __init__(self, seed):
        rng = random.Random(seed)
        for i in range(rng.randint(3, 7)):
            setattr(self, f"field_{rng.randint(0, 99)}", rng.random())


def _dump(obj):
    out = DebugReprGenerator().dump_object(obj)
    assert out.startswith("<div class=box>")
    return out


class DumpObjectScenarios(unittest.TestCase):
    def test_str_keyed_dict(self):
        data = {f"k{(i * 7) % 23}": i * i for i in range(14)}
        out = _dump(data)
        self.assertIn("Contents of", out)
        self.assertEqual(out.count("<tr>"), len(data))

    def test_nonstr_key_midway(self):
        rng = random.Random(11)
        data = {}
        for i in range(rng.randint(5, 12)):
            data[f"name{rng.randint(10, 99)}"] = rng.random()
        data[rng.randint(100, 200)] = "int key"
        data["after"] = 1
        out = _dump(data)
        self.assertIn("Details for", out)

    def test_empty_dict(self):
        out = _dump({})
        self.assertIn("Nothing", out)

    def test_probe_seeded_names(self):
        rng = random.Random(2024)
        letters = "abcdefg_"
        names = sorted(
            {"".join(rng.choice(letters) for _ in range(rng.randint(2, 6))) for _ in range(20)}
        )
        broken = [n for n in names if n.count(names[0][0]) >= 2]
        out = _dump(Probe(names, broken))
        self.assertIn("Details for", out)

    def test_list_instance(self):
        out = _dump([n * 3 for n in range(9)])
        self.assertIn("Details for", out)

    def test_tuple_first_key(self):
        data = {(1, 2): "pair"}
        data.update({str(i): i for i in range(4)})
        out = _dump(data)
        self.assertIn("Details for", out)

    def test_growing_dicts(self):
        outs = []
        for n in range(1, 8):
            outs.append(_dump({chr(97 + j) * (j + 1): j for j in range(n)}))
        self.assertEqual(len(outs), 7)

    def test_probe_mixed_dunder(self):
        names = [f"__x{i}__" if i % 3 == 0 else f"attr{i}" for i in range(13)]
        broken = [n for i, n in enumerate(names) if i % 4 == 1]
        out = _dump(Probe(names, broken))
        self.assertIn("Details for", out)

    def test_bytes_key_last(self):
        data = {f"s{i:02d}": [i] * (i % 3) for i in range(0, 20, 3)}
        data[b"raw"] = None
        out = _dump(data)
        self.assertIn("Details for", out)

    def test_plain_instance(self):
        out = _dump(Plain(5))
        self.assertIn("field_", out)

    def test_underscore_str_keys(self):
        keys = ["_" * (i % 3) + f"v{i}" for i in range(9)]
        out = _dump(dict(zip(keys, reversed(keys))))
        self.assertIn("Contents of", out)

    def test_empty_probe_and_none_key(self):
        out1 = _dump(Probe([], []))
        self.assertIn("Nothing", out1)
        out2 = _dump({None: 0, "z": 1})
        self.assertIn("Details for", out2)


if __name__ == "__main__":
    unittest.main()
