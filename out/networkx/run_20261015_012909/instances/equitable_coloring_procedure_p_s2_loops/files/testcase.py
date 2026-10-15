import unittest

import networkx as nx
from networkx.algorithms.coloring.equitable_coloring import is_equitable


class TestEquitableColoringRegular(unittest.TestCase):
    def test_tight_equitable_coloring_of_random_regular_graph(self):
        G = nx.random_regular_graph(12, 64, seed=15)
        num_colors = max(d for _, d in G.degree()) + 1

        coloring = nx.equitable_color(G, num_colors=num_colors)

        self.assertEqual(set(coloring), set(G.nodes))
        self.assertTrue(all(coloring[u] != coloring[v] for u, v in G.edges))
        self.assertTrue(is_equitable(G, coloring, num_colors=num_colors))
        self.assertLessEqual(len(set(coloring.values())), num_colors)
