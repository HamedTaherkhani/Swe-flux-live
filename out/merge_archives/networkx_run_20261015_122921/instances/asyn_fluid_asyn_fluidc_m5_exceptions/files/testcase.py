"""Scenarios driving asyn_fluidc through valid and invalid inputs."""

import random
import unittest

import networkx as nx
from networkx.algorithms.community.asyn_fluid import asyn_fluidc


def _partition_ok(G, comms):
    seen = set()
    for c in comms:
        if seen & c:
            return False
        seen |= c
    return seen == set(G)


def _seeded_tree(n, seed):
    rng = random.Random(seed)
    G = nx.Graph()
    G.add_node(0)
    for i in range(1, n):
        G.add_edge(i, rng.randrange(i))
    return G


class TestAsynFluidcScenarios(unittest.TestCase):
    def test_fractional_k(self):
        G = nx.cycle_graph(9)
        failures = 0
        for div in range(2, 8):
            k = sum(d for _, d in G.degree()) / div
            try:
                list(asyn_fluidc(G, k, seed=div))
            except Exception:
                failures += 1
        self.assertEqual(failures, 6)

    def test_nonpositive_k(self):
        G = nx.path_graph(6)
        k = len(G) - 2 * nx.diameter(G) + 4
        with self.assertRaises(Exception):
            list(asyn_fluidc(G, k, seed=2))

    def test_disconnected_graph(self):
        G = nx.disjoint_union(nx.complete_graph(4), nx.cycle_graph(5))
        with self.assertRaises(Exception):
            list(asyn_fluidc(G, 2, seed=3))

    def test_k_exceeds_order(self):
        G = nx.star_graph(4)
        with self.assertRaises(Exception):
            list(asyn_fluidc(G, G.number_of_edges() + 2, seed=4))

    def test_zero_max_iter(self):
        G = nx.wheel_graph(7)
        for shift in (6, 9):
            with self.assertRaises(Exception):
                list(asyn_fluidc(G, 2, max_iter=G.degree(0) - shift, seed=5))

    def test_none_max_iter(self):
        G = nx.ladder_graph(4)
        bad = [None, str(len(G)), [len(G)]]
        outcomes = []
        for value in bad:
            try:
                list(asyn_fluidc(G, 3, max_iter=value, seed=6))
                outcomes.append(True)
            except Exception:
                outcomes.append(False)
        self.assertFalse(any(outcomes))

    def test_empty_graph(self):
        G = nx.Graph()
        with self.assertRaises(Exception):
            list(asyn_fluidc(G, 1, seed=7))

    def test_directed_graph(self):
        G = nx.DiGraph(nx.path_graph(5))
        with self.assertRaises(Exception):
            list(asyn_fluidc(G, 2, seed=8))

    def test_complete_graph_all_seeded(self):
        G = nx.complete_graph(7)
        comms = list(asyn_fluidc(G, len(G), seed=9))
        self.assertEqual(len(comms), len(G))
        self.assertTrue(_partition_ok(G, comms))

    def test_random_tree(self):
        G = _seeded_tree(24, seed=10)
        comms = list(asyn_fluidc(G, 3, seed=11))
        self.assertTrue(1 <= len(comms) <= 3)
        self.assertTrue(_partition_ok(G, comms))

    def test_grid_single_community(self):
        G = nx.convert_node_labels_to_integers(nx.grid_2d_graph(4, 5))
        comms = list(asyn_fluidc(G, 1, seed=12))
        self.assertEqual(len(comms), 1)
        self.assertTrue(_partition_ok(G, comms))

    def test_karate_multiple_seeds(self):
        G = nx.karate_club_graph()
        sizes = []
        for s in range(13, 16):
            comms = list(asyn_fluidc(G, 2 + s % 3, seed=s))
            self.assertTrue(_partition_ok(G, comms))
            sizes.append(len(comms))
        self.assertEqual(len(sizes), 3)

    def test_watts_strogatz_capped_iterations(self):
        G = nx.connected_watts_strogatz_graph(30, 4, 0.3, seed=16)
        comms = list(asyn_fluidc(G, 4, max_iter=2, seed=17))
        self.assertTrue(_partition_ok(G, comms))


if __name__ == "__main__":
    unittest.main()
