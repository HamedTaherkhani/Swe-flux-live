import random
import unittest

import networkx as nx


def _float_value(rng):
    roll = rng.random()
    if roll < 0.15:
        return float("inf")
    if roll < 0.25:
        return float("-inf")
    if roll < 0.35:
        return float("nan")
    return round(rng.uniform(-5, 5), 2)


def _history(rng, length):
    hist = []
    for t in range(length):
        start = t * 2 if rng.random() < 0.5 else None
        end = (t * 2 + 1) if rng.random() < 0.4 else None
        hist.append((_float_value(rng), start, end))
    return hist


def _attributes(rng):
    makers = {
        "score": lambda: _float_value(rng),
        "flag": lambda: rng.random() < 0.5,
        "rank": lambda: rng.randint(0, 99),
        "tag": lambda: rng.choice(["alpha", "beta", "gamma"]),
        "hist": lambda: _history(rng, rng.randint(1, 4)),
    }
    names = sorted(makers)
    rng.shuffle(names)
    chosen = names[: rng.randint(0, len(names))]
    return {name: makers[name]() for name in chosen}


class TestGexfAttributeSerialization(unittest.TestCase):
    def test_generate_gexf_mixed_attributes(self):
        rng = random.Random(8412)
        G = nx.MultiGraph()
        for n in range(9):
            G.add_node(n, **_attributes(rng))
        for _ in range(11):
            u, v = rng.sample(range(9), 2)
            G.add_edge(u, v, **_attributes(rng))

        text = "\n".join(nx.generate_gexf(G, prettyprint=False))

        self.assertIn("<attvalues>", text)
        self.assertEqual(text.count("<node "), G.number_of_nodes())
        self.assertEqual(text.count("<edge "), G.number_of_edges())
        self.assertGreater(text.count("<attvalue "), G.number_of_edges())
