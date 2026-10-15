import random
import unittest

import networkx as nx
from networkx.algorithms.community import (
    is_partition,
    louvain_communities,
    louvain_partitions,
)


def _covers(G, communities):
    return is_partition(G, communities)


class TestLouvainScenarios(unittest.TestCase):
    def test_karate_club(self):
        G = nx.karate_club_graph()
        comms = louvain_communities(G, seed=7)
        self.assertTrue(_covers(G, comms))
        self.assertGreater(len(comms), 1)

    def test_planted_partition(self):
        G = nx.planted_partition_graph(4, 7, 0.7, 0.06, seed=3)
        comms = louvain_communities(G, seed=19)
        self.assertTrue(_covers(G, comms))

    def test_random_fractional_weights(self):
        rng = random.Random(11)
        G = nx.gnm_random_graph(26, 60, seed=5)
        for u, v in G.edges():
            G[u][v]["weight"] = rng.choice([0.25, 0.5, 1.5, 2.0, 3.75])
        comms = louvain_communities(G, seed=4)
        self.assertTrue(_covers(G, comms))

    def test_multigraph_parallel_edges(self):
        rng = random.Random(23)
        M = nx.MultiGraph()
        M.add_nodes_from(range(14))
        for _ in range(40):
            a, b = rng.sample(range(14), 2)
            M.add_edge(a, b, weight=rng.randint(1, 4))
        comms = louvain_communities(M, seed=8)
        self.assertTrue(_covers(M, comms))

    def test_self_loops_and_custom_weight_key(self):
        G = nx.cycle_graph(18)
        for i, (u, v) in enumerate(list(G.edges())):
            G[u][v]["cap"] = 1 + (i * 7) % 5
        for n in range(0, 18, 4):
            G.add_edge(n, n, cap=3)
        comms = louvain_communities(G, weight="cap", seed=13)
        self.assertTrue(_covers(G, comms))

    def test_caveman_low_resolution(self):
        G = nx.connected_caveman_graph(5, 5)
        comms = louvain_communities(G, resolution=0.5, seed=2)
        self.assertTrue(_covers(G, comms))

    def test_lollipop_high_resolution(self):
        G = nx.lollipop_graph(7, 9)
        comms = louvain_communities(G, resolution=2.5, seed=31)
        self.assertTrue(_covers(G, comms))

    def test_edgeless_directed_graph(self):
        D = nx.DiGraph()
        D.add_nodes_from(f"n{i}" for i in range(9))
        comms = louvain_communities(D, seed=1)
        self.assertEqual(len(comms), D.number_of_nodes())

    def test_max_level_one(self):
        G = nx.barbell_graph(6, 3)
        comms = louvain_communities(G, max_level=1, seed=17)
        self.assertTrue(_covers(G, comms))

    def test_partitions_high_threshold(self):
        G = nx.windmill_graph(4, 5)
        levels = list(louvain_partitions(G, threshold=0.2, seed=6))
        self.assertGreaterEqual(len(levels), 1)
        self.assertTrue(_covers(G, levels[-1]))

    def test_unweighted_with_isolates(self):
        G = nx.star_graph(8)
        nx.add_path(G, range(9, 20))
        G.add_nodes_from(range(20, 24))
        for u, v in G.edges():
            G[u][v]["weight"] = 100
        comms = louvain_communities(G, weight=None, seed=29)
        self.assertTrue(_covers(G, comms))

    def test_ladder_decreasing_weights(self):
        G = nx.ladder_graph(10)
        for idx, (u, v) in enumerate(sorted(G.edges())):
            G[u][v]["weight"] = 20 / (1 + idx)
        comms = louvain_communities(G, seed=41)
        self.assertTrue(_covers(G, comms))
