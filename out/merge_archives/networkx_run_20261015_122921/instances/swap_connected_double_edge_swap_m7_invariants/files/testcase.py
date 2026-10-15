import random
import unittest

import networkx as nx
from networkx.algorithms.swap import connected_double_edge_swap


def _int_relabel(G, seed):
    """Relabel nodes of G with a seeded permutation of 0..len(G)-1."""
    rng = random.Random(seed)
    labels = list(range(len(G)))
    rng.shuffle(labels)
    mapping = dict(zip(sorted(G.nodes(), key=repr), labels))
    H = nx.Graph()
    H.add_nodes_from(sorted(mapping.values()))
    H.add_edges_from(sorted((mapping[a], mapping[b]) for a, b in G.edges()))
    return H


def _connected_gnp(n, p, seed):
    s = seed
    while True:
        G = nx.gnp_random_graph(n, p, seed=s)
        if nx.is_connected(G):
            return G
        s += 1


class TestConnectedDoubleEdgeSwapInvariants(unittest.TestCase):
    def _run(self, G, nswap, threshold, seed):
        degs = sorted(d for _, d in G.degree())
        m = G.number_of_edges()
        res = connected_double_edge_swap(
            G, nswap=nswap, _window_threshold=threshold, seed=seed
        )
        self.assertIsInstance(res, int)
        self.assertGreaterEqual(res, 0)
        self.assertLessEqual(res, nswap)
        self.assertTrue(nx.is_connected(G))
        self.assertEqual(sorted(d for _, d in G.degree()), degs)
        self.assertEqual(G.number_of_edges(), m)
        return res

    def test_path_small_window(self):
        G = _int_relabel(nx.path_graph(12), seed=11)
        self._run(G, nswap=40, threshold=3, seed=1)

    def test_cycle_threshold_two(self):
        G = _int_relabel(nx.cycle_graph(15), seed=12)
        self._run(G, nswap=60, threshold=2, seed=2)

    def test_watts_strogatz(self):
        G = _int_relabel(nx.connected_watts_strogatz_graph(30, 4, 0.3, seed=7), seed=13)
        self._run(G, nswap=150, threshold=3, seed=3)

    def test_grid(self):
        G = _int_relabel(nx.grid_2d_graph(5, 5), seed=14)
        self._run(G, nswap=80, threshold=5, seed=4)

    def test_barabasi_albert(self):
        G = _int_relabel(nx.barabasi_albert_graph(40, 2, seed=3), seed=15)
        self._run(G, nswap=200, threshold=4, seed=5)

    def test_complete_graph_no_swaps(self):
        G = _int_relabel(nx.complete_graph(6), seed=16)
        res = self._run(G, nswap=30, threshold=3, seed=6)
        self.assertEqual(res, 0)

    def test_wheel(self):
        G = _int_relabel(nx.wheel_graph(10), seed=17)
        self._run(G, nswap=50, threshold=3, seed=7)

    def test_disconnected_raises(self):
        G = nx.disjoint_union(nx.cycle_graph(5), nx.path_graph(4))
        with self.assertRaisesRegex(nx.NetworkXError, "connected"):
            connected_double_edge_swap(G, nswap=10, seed=8)

    def test_random_tree(self):
        rng = random.Random(9)
        prufer = [rng.randrange(20) for _ in range(18)]
        G = nx.from_prufer_sequence(prufer)
        self._run(G, nswap=70, threshold=3, seed=9)

    def test_barbell(self):
        G = _int_relabel(nx.barbell_graph(5, 3), seed=18)
        self._run(G, nswap=90, threshold=6, seed=10)

    def test_gnp_large_threshold(self):
        G = _int_relabel(_connected_gnp(25, 0.2, seed=21), seed=19)
        self._run(G, nswap=120, threshold=10, seed=11)

    def test_ladder_always_large_window(self):
        G = _int_relabel(nx.ladder_graph(10), seed=20)
        self._run(G, nswap=100, threshold=1, seed=12)

    def test_hypercube(self):
        G = _int_relabel(nx.hypercube_graph(4), seed=22)
        self._run(G, nswap=64, threshold=3, seed=13)


if __name__ == "__main__":
    unittest.main()
