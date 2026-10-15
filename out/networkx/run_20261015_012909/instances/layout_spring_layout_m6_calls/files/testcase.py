import random
import unittest

import numpy as np

import networkx as nx
from networkx.drawing.layout import spring_layout


def _weighted_gnm(n, m, seed):
    rng = random.Random(seed)
    G = nx.gnm_random_graph(n, m, seed=seed)
    for u, v in G.edges():
        G[u][v]["weight"] = round(rng.uniform(0.2, 3.0), 3)
    return G


class TestSpringLayoutCallGraph(unittest.TestCase):
    def test_force_path_graphs_of_growing_size(self):
        sizes = [n for n in range(0, 9) if n % 3 != 2]
        for n in sizes:
            G = nx.path_graph(n)
            pos = spring_layout(G, seed=n + 11)
            self.assertEqual(len(pos), n)

    def test_invalid_method_names(self):
        names = ["Force", "spring", "auto", "energy ", "kk"]
        G = nx.cycle_graph(5)
        for name in names:
            if name == name.lower().strip() and name.endswith(("o", "e", "y")):
                pos = spring_layout(G, method=name, seed=3, iterations=7)
                self.assertEqual(len(pos), 5)
            else:
                with self.assertRaisesRegex(ValueError, "must be either"):
                    spring_layout(G, method=name, seed=3)

    def test_center_dimension_mismatch(self):
        G = nx.star_graph(4)
        for dim in range(2, 5):
            center = [0.5] * (dim - (dim % 2))
            if len(center) == dim:
                pos = spring_layout(G, dim=dim, center=center, seed=dim)
                self.assertEqual(len(next(iter(pos.values()))), dim)
            else:
                with self.assertRaisesRegex(ValueError, "center coordinates"):
                    spring_layout(G, dim=dim, center=center, seed=dim)

    def test_fixed_nodes_validation(self):
        G = nx.grid_2d_graph(3, 3)
        nodes = sorted(G)
        with self.assertRaisesRegex(ValueError, "without positions"):
            spring_layout(G, fixed=nodes[:2], seed=1)
        partial = {nd: (i * 0.25, (i % 3) * 0.5) for i, nd in enumerate(nodes[:4])}
        with self.assertRaisesRegex(ValueError, "without positions"):
            spring_layout(G, fixed=nodes[:5], pos=partial, seed=1)
        partial[("x", "y")] = (0.75, 0.75)
        fixed = [nd for nd in nodes[:4] if sum(nd) % 2 == 0] + [("x", "y")]
        pos = spring_layout(G, fixed=fixed, pos=partial, seed=1, iterations=20)
        for nd in fixed[:-1]:
            np.testing.assert_allclose(pos[nd], partial[nd], atol=1e-6)

    def test_node_list_input_without_edges(self):
        for count in (1, 4, 9):
            nodes = [f"v{i}" for i in range(count)]
            pos = spring_layout(nodes, seed=count, iterations=15)
            self.assertEqual(sorted(pos), sorted(nodes))

    def test_energy_method_on_weighted_random_graphs(self):
        for idx, (n, m) in enumerate([(10, 14), (25, 40), (40, 30)]):
            G = _weighted_gnm(n, m, seed=100 + idx)
            pos = spring_layout(G, method="energy", seed=idx, iterations=25)
            self.assertEqual(len(pos), n)
            arr = np.array(list(pos.values()))
            self.assertLessEqual(np.abs(arr).max(), 1.0 + 1e-9)

    def test_energy_gravity_and_zero_iterations(self):
        G = nx.ladder_graph(6)
        for gravity in (2.0, 0.0, -1.0):
            if gravity > 0:
                pos = spring_layout(
                    G, method="energy", gravity=gravity, iterations=0, seed=4
                )
                self.assertEqual(len(pos), 12)
            else:
                with self.assertRaisesRegex(ValueError, "gravity"):
                    spring_layout(G, method="energy", gravity=gravity, seed=4)

    def test_scale_none_and_store_attribute(self):
        G = nx.wheel_graph(7)
        for scale in (None, 2.5, None):
            pos = spring_layout(G, scale=scale, seed=21, store_pos_as="xy")
            self.assertEqual(len(nx.get_node_attributes(G, "xy")), 7)
            self.assertEqual(len(pos), 7)

    def test_initial_positions_with_threshold(self):
        G = nx.circular_ladder_graph(5)
        init = {n: (np.cos(n), np.sin(n)) for n in G if n % 2 == 1}
        for thr in (1e-1, 1e-4):
            pos = spring_layout(G, pos=init, threshold=thr, seed=8, iterations=60)
            self.assertEqual(len(pos), len(G))

    def test_auto_method_large_graph(self):
        G = nx.connected_watts_strogatz_graph(510, 4, 0.2, seed=5)
        pos = spring_layout(G, seed=12, iterations=12)
        self.assertEqual(len(pos), 510)

    def test_energy_with_fixed_nodes_on_disconnected_graph(self):
        G = nx.disjoint_union(nx.cycle_graph(7), _weighted_gnm(9, 12, seed=31))
        init = {n: ((n * 29) % 11 / 10.0, (n * 53) % 13 / 12.0) for n in G if n % 4}
        fixed = sorted(n for n in init if n % 3 == 0)
        pos = spring_layout(
            G, method="energy", pos=init, fixed=fixed, seed=14, iterations=40
        )
        for n in fixed:
            np.testing.assert_allclose(pos[n], init[n], atol=1e-6)

    def test_three_dimensional_mixed_methods(self):
        G = nx.hypercube_graph(3)
        for method in ("force", "energy"):
            pos = spring_layout(G, dim=3, method=method, seed=9, iterations=18)
            self.assertEqual(len(pos), 8)
            self.assertEqual(len(next(iter(pos.values()))), 3)

    def test_fixed_with_empty_graph_and_k(self):
        empty = nx.empty_graph(0)
        self.assertEqual(spring_layout(empty, seed=1), {})
        G = nx.complete_graph(6)
        init = {i: (i, -i) for i in range(6)}
        pos = spring_layout(G, pos=init, fixed=[0, 3], seed=6, k=0.4)
        np.testing.assert_allclose(pos[3], [3.0, -3.0])


if __name__ == "__main__":
    unittest.main()
