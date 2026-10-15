import random
import unittest

import networkx as nx
from networkx.algorithms.connectivity.kcutsets import all_node_cuts


def build_graph():
    rng = random.Random(1)
    G = nx.random_regular_graph(3, 16, seed=rng.randrange(10**6))
    perm = list(range(16))
    rng.shuffle(perm)
    return nx.relabel_nodes(G, {i: perm[i] * 3 + 1 for i in range(16)})


class TestAllNodeCutsLoops(unittest.TestCase):
    def test_all_node_cuts_regular_graph(self):
        G = build_graph()
        self.assertTrue(nx.is_connected(G))
        k = nx.node_connectivity(G)
        cuts = list(all_node_cuts(G))
        self.assertTrue(len(cuts) > 0)
        for cut in cuts:
            self.assertEqual(len(cut), k)
            H = G.copy()
            H.remove_nodes_from(cut)
            self.assertFalse(nx.is_connected(H))
        self.assertEqual(len({frozenset(c) for c in cuts}), len(cuts))
