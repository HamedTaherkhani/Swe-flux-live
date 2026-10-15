import random
import unittest

import networkx as nx
from networkx.algorithms.centrality.group import group_betweenness_centrality


def build_graph():
    # Two components: a seeded random connected-ish core and a small cycle with chords.
    G = nx.gnm_random_graph(14, 24, seed=20240611)
    offset = 14
    for i in range(6):
        G.add_edge(offset + i, offset + (i + 1) % 6)
    G.add_edge(offset, offset + 3)
    return G


def build_groups(G):
    rng = random.Random(7331)
    nodes = sorted(G)
    groups = []
    for size in (2, 3, 4):
        groups.append(sorted(rng.sample(nodes, size)))
    return groups


class TestGroupBetweennessHistory(unittest.TestCase):
    def test_multi_group_unnormalized(self):
        G = build_graph()
        groups = build_groups(G)
        result = group_betweenness_centrality(G, groups, normalized=False)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), len(groups))
        for val in result:
            self.assertIsInstance(val, float)
            self.assertGreaterEqual(val, 0.0)
