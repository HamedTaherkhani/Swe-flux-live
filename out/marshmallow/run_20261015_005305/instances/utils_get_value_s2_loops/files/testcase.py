import random
import unittest

from marshmallow.utils import get_value


class Box:
    """Node whose item lookups and attribute lookups may point to different nodes."""

    def __init__(self, tag):
        self.tag = tag
        self.table = {}

    def __getitem__(self, key):
        return self.table[key]

    def __repr__(self):
        return f"Box({self.tag!r})"


NAMES = ["al", "be", "ga", "de", "ep"]


def build_graph(seed=20240611, size=12):
    rng = random.Random(seed)
    nodes = [Box("n%02d" % ((i * 7 + 3) % 31)) for i in range(size)]
    fallback = Box("dflt")
    for node in nodes + [fallback]:
        for name in NAMES:
            roll = rng.random()
            if roll < 0.45:
                node.table[name] = rng.choice(nodes)
            elif roll < 0.8:
                setattr(node, name, rng.choice(nodes))
            # otherwise: neither item nor attribute -> default is used
    return nodes, fallback


def build_path(seed=97, length=46):
    rng = random.Random(seed)
    parts = []
    while len(parts) < length:
        name = rng.choice(NAMES)
        if parts and parts[-1] == name and rng.random() < 0.5:
            continue
        parts.append(name)
    return ".".join(parts)


class GetValueWalkTest(unittest.TestCase):
    def test_dotted_walk_over_box_graph(self):
        nodes, fallback = build_graph()
        path = build_path()
        result = get_value(nodes[0], path, default=fallback)
        self.assertIsInstance(result, Box)
        self.assertIn(result, nodes + [fallback])
        self.assertEqual(path.count(".") + 1, 46)


if __name__ == "__main__":
    unittest.main()
