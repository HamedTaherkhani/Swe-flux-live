"""Deterministic scenarios driving networkx.algorithms.sparsifiers.spanner."""

import random
import unittest

import networkx as nx
from networkx.algorithms.sparsifiers import spanner


def weighted_gnp(n, p, seed):
    """Seeded G(n, p) graph with distinct integer edge weights."""
    G = nx.gnp_random_graph(n, p, seed=seed)
    rng = random.Random(seed * 7 + 3)
    weights = rng.sample(range(1, 10 * G.number_of_edges() + 10), G.number_of_edges())
    for (u, v), w in zip(sorted(G.edges()), weights):
        G[u][v]["weight"] = w
    return G


def assert_is_spanner(tc, G, H, stretch, weight):
    tc.assertEqual(set(H.nodes), set(G.nodes))
    for u, v in H.edges():
        tc.assertTrue(G.has_edge(u, v))
    dist_g = dict(nx.all_pairs_dijkstra_path_length(G, weight=weight or (lambda u, v, d: 1)))
    dist_h = dict(nx.all_pairs_dijkstra_path_length(H, weight=weight or (lambda u, v, d: 1)))
    for u in dist_g:
        for v, d in dist_g[u].items():
            tc.assertLessEqual(dist_h[u][v], stretch * d + 1e-9)


class TestSpannerLoops(unittest.TestCase):
    def test_weighted_gnp_stretch3(self):
        G = weighted_gnp(24, 0.35, seed=11)
        H = spanner(G, 3, weight="weight", seed=5)
        assert_is_spanner(self, G, H, 3, "weight")

    def test_weighted_gnp_stretch5(self):
        G = weighted_gnp(30, 0.3, seed=4)
        H = spanner(G, 5, weight="weight", seed=17)
        assert_is_spanner(self, G, H, 5, "weight")

    def test_weighted_gnp_stretch7_random_instance(self):
        G = weighted_gnp(28, 0.4, seed=9)
        H = spanner(G, 7, weight="weight", seed=random.Random(2024))
        assert_is_spanner(self, G, H, 7, "weight")

    def test_unweighted_complete_stretch3(self):
        G = nx.complete_graph(14)
        H = spanner(G, 3, seed=8)
        assert_is_spanner(self, G, H, 3, None)

    def test_unweighted_grid_stretch4(self):
        G = nx.convert_node_labels_to_integers(nx.grid_2d_graph(5, 6))
        H = spanner(G, 4, seed=1)
        assert_is_spanner(self, G, H, 4, None)

    def test_stretch_one_keeps_everything(self):
        G = weighted_gnp(18, 0.3, seed=2)
        H = spanner(G, 1, weight="weight", seed=3)
        self.assertEqual(H.number_of_edges(), G.number_of_edges())

    def test_weighted_wheel_stretch3(self):
        G = nx.wheel_graph(20)
        for idx, (u, v) in enumerate(sorted(G.edges())):
            G[u][v]["weight"] = (idx * 37) % 101 + 1
        H = spanner(G, 3, weight="weight", seed=13)
        assert_is_spanner(self, G, H, 3, "weight")

    def test_barbell_weighted_stretch5(self):
        G = nx.barbell_graph(8, 4)
        rng = random.Random(77)
        ws = rng.sample(range(1, 500), G.number_of_edges())
        for (u, v), w in zip(sorted(G.edges()), ws):
            G[u][v]["weight"] = w
        H = spanner(G, 5, weight="weight", seed=21)
        assert_is_spanner(self, G, H, 5, "weight")

    def test_unweighted_gnm_stretch3(self):
        G = nx.gnm_random_graph(26, 90, seed=31)
        H = spanner(G, 3, seed=6)
        assert_is_spanner(self, G, H, 3, None)

    def test_disconnected_weighted_stretch3(self):
        G = nx.disjoint_union(weighted_gnp(12, 0.5, seed=5), weighted_gnp(10, 0.6, seed=6))
        H = spanner(G, 3, weight="weight", seed=99)
        assert_is_spanner(self, G, H, 3, "weight")

    def test_petersen_unweighted_stretch6(self):
        G = nx.petersen_graph()
        H = spanner(G, 6, seed=42)
        assert_is_spanner(self, G, H, 6, None)

    def test_invalid_stretch_raises(self):
        G = weighted_gnp(10, 0.5, seed=1)
        with self.assertRaises(ValueError):
            spanner(G, 0.5, weight="weight", seed=1)
