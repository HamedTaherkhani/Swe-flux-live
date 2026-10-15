import random
import unittest

import networkx as nx
from networkx.algorithms.flow import edmonds_karp, shortest_augmenting_path


def build_network(seed, n, p):
    """Seeded random capacitated digraph on nodes 0..n-1."""
    rng = random.Random(seed)
    G = nx.DiGraph()
    G.add_nodes_from(range(n))
    for u in range(n):
        for v in range(n):
            if u != v and rng.random() < p:
                G.add_edge(u, v, capacity=rng.randint(1, 9))
    return G


class TestShortestAugmentingPathBatch(unittest.TestCase):
    def test_batch_of_max_flows(self):
        scenarios = [
            {"seed": 9, "n": 40, "p": 0.06, "two_phase": False},
            {"seed": 6, "n": 40, "p": 0.06, "two_phase": False},
            {"seed": 7, "n": 30, "p": 0.08, "two_phase": True},
        ]
        for sc in scenarios:
            G = build_network(sc["seed"], sc["n"], sc["p"])
            s, t = 0, sc["n"] - 1
            value = nx.maximum_flow_value(
                G, s, t, flow_func=shortest_augmenting_path, two_phase=sc["two_phase"]
            )
            expected = nx.maximum_flow_value(G, s, t, flow_func=edmonds_karp)
            self.assertEqual(value, expected)
            self.assertGreater(value, 0)
            cut_value, (S, T) = nx.minimum_cut(G, s, t, flow_func=edmonds_karp)
            self.assertEqual(cut_value, value)
            self.assertIn(s, S)
            self.assertIn(t, T)


if __name__ == "__main__":
    unittest.main()
