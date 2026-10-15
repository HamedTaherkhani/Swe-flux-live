import random
import unittest

import networkx as nx


def _build_graph():
    rng = random.Random(5)
    G = nx.gnp_random_graph(120, 0.3, seed=5)
    for u, v in sorted(G.edges()):
        G[u][v]["weight"] = rng.randint(1, 10)
    return G


class TestMaxWeightMatchingBlossoms(unittest.TestCase):
    def test_random_dense_graph(self):
        G = _build_graph()
        matching = nx.max_weight_matching(G)
        self.assertTrue(nx.is_matching(G, matching))
        self.assertTrue(nx.is_maximal_matching(G, matching))
        total = sum(G[u][v]["weight"] for u, v in matching)
        self.assertGreater(total, 0)
