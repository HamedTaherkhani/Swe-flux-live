import random
import unittest

import networkx as nx
from networkx.algorithms.triads import triadic_census


def _build_graph():
    rng = random.Random(8128)
    G = nx.DiGraph()
    G.add_nodes_from(range(3, 3 + 7 * 26, 7))
    nodes = sorted(G)
    for a in nodes:
        for b in nodes:
            if a == b:
                continue
            r = rng.random()
            if r < 0.07:
                G.add_edge(a, b)
                if rng.random() < 0.35:
                    G.add_edge(b, a)
    return G


class TestTriadicCensusSubset(unittest.TestCase):
    def test_census_on_node_subset(self):
        G = _build_graph()
        nodes = sorted(G)
        nodelist = [n for i, n in enumerate(nodes) if (i * 5) % 11 < 4]
        census = triadic_census(G, nodelist)

        # cross-check against a brute-force count restricted to nodelist
        full = triadic_census(G.subgraph(nodes))
        self.assertEqual(sum(full.values()), len(G) * (len(G) - 1) * (len(G) - 2) // 6)
        nset = set(nodelist)
        expected = {name: 0 for name in census}
        from itertools import combinations

        for tri in combinations(nodes, 3):
            if nset.intersection(tri):
                expected[nx.triad_type(G.subgraph(tri))] += 1
        self.assertEqual(census, expected)
        self.assertGreater(len(nodelist), 5)
        self.assertLess(len(nodelist), len(G))
