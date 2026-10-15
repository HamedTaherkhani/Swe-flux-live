import random
import unittest

import networkx as nx
from networkx.algorithms.matching import max_weight_matching


def _build_graph(seed):
    rng = random.Random(seed)
    n = rng.randint(10, 24)
    p = rng.uniform(0.15, 0.5)
    G = nx.gnp_random_graph(n, p, seed=seed)
    for u, v in G.edges:
        G[u][v]["weight"] = rng.randint(1, 20)
    return G


class TestAddBlossomDataFlow(unittest.TestCase):
    def test_blossoms_on_random_graphs(self):
        total = 0
        for seed in (3, 7):
            G = _build_graph(seed)
            mate = max_weight_matching(G)
            self.assertTrue(nx.is_matching(G, mate))
            total += len(mate)
        self.assertGreater(total, 0)
