import random
import unittest

import networkx as nx
from networkx.algorithms.community.lukes import lukes_partitioning


def _build_tree(seed, n):
    rng = random.Random(seed)
    G = nx.DiGraph()
    labels = [(k * 7 + 3) % n for k in range(n)]
    for i in range(n):
        G.add_node(labels[i], w=rng.choice([1, 1, 2, 3]))
    for i in range(1, n):
        p = rng.randrange(max(0, i - 4), i)
        G.add_edge(labels[p], labels[i], c=round(rng.uniform(0.5, 4.0), 2))
    return G


class TestLukesSeededTree(unittest.TestCase):
    def test_seeded_directed_tree(self):
        G = _build_tree(5, 9)
        self.assertTrue(nx.is_arborescence(G))
        max_size = 5
        partition = lukes_partitioning(G, max_size, node_weight="w", edge_weight="c")
        covered = set().union(*partition)
        self.assertEqual(covered, set(G.nodes))
        self.assertEqual(sum(len(c) for c in partition), G.number_of_nodes())
        for cluster in partition:
            self.assertLessEqual(sum(G.nodes[v]["w"] for v in cluster), max_size)
