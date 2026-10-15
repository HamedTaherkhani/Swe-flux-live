import random
import unittest

import networkx as nx
from networkx.algorithms.bipartite import eppstein_matching, hopcroft_karp_matching


def _random_bipartite(n_top, n_bottom, p, seed):
    """Seeded bipartite graph: top nodes are 0..n_top-1, bottom nodes follow."""
    rng = random.Random(seed)
    G = nx.Graph()
    top = list(range(n_top))
    bottom = list(range(n_top, n_top + n_bottom))
    G.add_nodes_from(top, bipartite=0)
    G.add_nodes_from(bottom, bipartite=1)
    for u in top:
        for v in bottom:
            if rng.random() < p:
                G.add_edge(u, v)
    return G, set(top)


def _greedy_trap(lengths):
    """Disjoint chains: in chain c, top i (< k) lists bottom i before bottom i+1
    and the last top only sees bottom 0, so the greedy pass leaves it stranded
    behind an augmenting path whose length grows with k."""
    G = nx.Graph()
    top = []
    for c, k in enumerate(lengths):
        for i in range(k):
            G.add_edge((0, c, i), (1, c, i))
            G.add_edge((0, c, i), (1, c, i + 1))
            top.append((0, c, i))
        G.add_edge((0, c, k), (1, c, 0))
        top.append((0, c, k))
    return G, set(top)


class TestEppsteinMatchingProfiles(unittest.TestCase):
    def _check(self, G, top, matching):
        self.assertTrue(nx.is_matching(G, matching))
        ref = hopcroft_karp_matching(G, top_nodes=top)
        self.assertEqual(len(matching), len(ref))
        for k, v in matching.items():
            self.assertEqual(matching[v], k)

    def test_sparse_random(self):
        G, top = _random_bipartite(14, 11, 0.18, seed=3)
        self._check(G, top, eppstein_matching(G, top_nodes=top))

    def test_dense_random(self):
        G, top = _random_bipartite(9, 9, 0.6, seed=11)
        self._check(G, top, eppstein_matching(G, top_nodes=top))

    def test_unbalanced_wide(self):
        G, top = _random_bipartite(4, 17, 0.25, seed=7)
        self._check(G, top, eppstein_matching(G, top_nodes=top))

    def test_unbalanced_tall(self):
        G, top = _random_bipartite(16, 5, 0.2, seed=21)
        self._check(G, top, eppstein_matching(G, top_nodes=top))

    def test_greedy_trap_chains(self):
        G, top = _greedy_trap([(3 * j) % 7 + 1 for j in range(1, 6)])
        self._check(G, top, eppstein_matching(G, top_nodes=top))

    def test_connected_path_without_top_nodes(self):
        G = nx.path_graph(13)
        top = {n for n in G if n % 2 == 0}
        matching = eppstein_matching(G)
        self._check(G, top, matching)

    def test_complete_bipartite(self):
        G = nx.complete_bipartite_graph(5, 7)
        top = set(range(5))
        self._check(G, top, eppstein_matching(G, top_nodes=top))

    def test_star_forest(self):
        G = nx.Graph()
        centers = [100 + c for c in range(4)]
        G.add_nodes_from(centers)
        leaf = 0
        for c in centers:
            for _ in range(c % 7 + 1):
                G.add_edge(c, leaf)
                leaf += 1
        self._check(G, set(centers), eppstein_matching(G, top_nodes=set(centers)))

    def test_isolated_top_nodes_only(self):
        G = nx.Graph()
        G.add_nodes_from(range(6))
        top = {n for n in G if n % 3 != 0}
        matching = eppstein_matching(G, top_nodes=top)
        self.assertFalse(matching)

    def test_crown_graph(self):
        # complete bipartite minus a perfect matching
        k = 6
        G = nx.Graph()
        for i in range(k):
            for j in range(k):
                if i != j:
                    G.add_edge((0, i), (1, (j * 5) % k))
        top = {(0, i) for i in range(k)}
        self._check(G, top, eppstein_matching(G, top_nodes=top))

    def test_shuffled_trap_plus_noise(self):
        G, top = _greedy_trap([2, 4])
        rng = random.Random(42)
        bottoms = sorted(n for n in G if n not in top)
        for t in sorted(top):
            if rng.random() < 0.3:
                G.add_edge(t, rng.choice(bottoms))
        self._check(G, top, eppstein_matching(G, top_nodes=top))

    def test_hypercube(self):
        G = nx.hypercube_graph(4)
        top = {n for n in G if sum(n) % 2 == 0}
        self._check(G, top, eppstein_matching(G, top_nodes=top))

    def test_repeated_small_grids(self):
        for w in range(2, 5):
            G = nx.grid_2d_graph(w, w + 1)
            top = {n for n in G if (n[0] + n[1]) % 2 == 1}
            self._check(G, top, eppstein_matching(G, top_nodes=top))
