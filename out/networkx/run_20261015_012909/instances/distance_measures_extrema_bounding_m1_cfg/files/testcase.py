import random
import unittest

import networkx as nx


def _seeded_tree(n, seed):
    rng = random.Random(seed)
    G = nx.Graph()
    G.add_node(0)
    for i in range(1, n):
        G.add_edge(i, rng.randrange(max(0, i - 4), i) if i % 3 else rng.randrange(i))
    return G


def _weighted(G, seed, lo=1, hi=5, attr="w"):
    rng = random.Random(seed)
    for u, v in sorted(G.edges()):
        G[u][v][attr] = rng.randint(lo, hi)
    return G


class TestBoundedDistanceMetrics(unittest.TestCase):
    def _check(self, func, G, **kw):
        fast = func(G, usebounds=True, **kw)
        slow = func(G, **kw)
        if isinstance(fast, list):
            self.assertEqual(sorted(fast), sorted(slow))
        else:
            self.assertEqual(fast, slow)
        return fast

    def test_diameter_random_tree(self):
        G = _seeded_tree(34, seed=7)
        self._check(nx.diameter, G)

    def test_radius_grid(self):
        G = nx.convert_node_labels_to_integers(nx.grid_2d_graph(5, 6))
        self._check(nx.radius, G)

    def test_periphery_odd_cycle(self):
        G = nx.cycle_graph(11)
        self._check(nx.periphery, G)

    def test_center_path(self):
        G = nx.path_graph(18)
        self._check(nx.center, G)

    def test_diameter_weighted_small_world(self):
        G = nx.connected_watts_strogatz_graph(26, 4, 0.3, seed=11)
        _weighted(G, seed=3)
        self._check(nx.diameter, G, weight="w")

    def test_center_barbell(self):
        G = nx.barbell_graph(5, 3)
        self._check(nx.center, G)

    def test_periphery_lollipop(self):
        G = nx.lollipop_graph(6, 7)
        self._check(nx.periphery, G)

    def test_radius_complete(self):
        G = nx.complete_graph(7)
        self._check(nx.radius, G)

    def test_radius_disconnected_raises(self):
        G = nx.disjoint_union(nx.path_graph(4), nx.star_graph(3))
        with self.assertRaises(nx.NetworkXError):
            nx.radius(G, usebounds=True)

    def test_center_largest_component_gnp(self):
        H = nx.gnp_random_graph(40, 0.07, seed=21)
        comp = max(nx.connected_components(H), key=lambda c: (len(c), min(c)))
        G = nx.convert_node_labels_to_integers(H.subgraph(comp).copy())
        self._check(nx.center, G)

    def test_diameter_weight_function(self):
        G = nx.convert_node_labels_to_integers(nx.circular_ladder_graph(7))

        def wfun(u, v, d):
            return 1 + (u * v) % 3

        self._check(nx.diameter, G, weight=wfun)

    def test_periphery_petersen(self):
        G = nx.petersen_graph()
        self._check(nx.periphery, G)

    def test_radius_weighted_caterpillar(self):
        G = nx.path_graph(9)
        nxt = 9
        for spine in range(9):
            for _ in range(spine % 3):
                G.add_edge(spine, nxt)
                nxt += 1
        _weighted(G, seed=5, lo=1, hi=3, attr="cost")
        self._check(nx.radius, G, weight="cost")


if __name__ == "__main__":
    unittest.main()
