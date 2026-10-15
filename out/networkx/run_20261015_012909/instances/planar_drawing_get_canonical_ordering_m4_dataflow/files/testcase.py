"""Planar layouts of assorted planar graphs (deterministic, integer node labels)."""

import random
import unittest

import networkx as nx


def _seeded_tree(n, seed):
    rnd = random.Random(seed)
    G = nx.Graph()
    G.add_node(0)
    for i in range(1, n):
        G.add_edge(i, rnd.randrange(i))
    return G


def _diagonal_grid(rows, cols):
    G = nx.grid_2d_graph(rows, cols)
    for r in range(rows - 1):
        for c in range(cols - 1):
            if (r + c) % 2 == 0:
                G.add_edge((r, c), (r + 1, c + 1))
            else:
                G.add_edge((r + 1, c), (r, c + 1))
    return nx.convert_node_labels_to_integers(G, ordering="sorted")


class TestPlanarLayoutScenarios(unittest.TestCase):
    def _check(self, G):
        pos = nx.planar_layout(G)
        self.assertEqual(set(pos), set(G))
        coords = {tuple(round(float(c), 9) for c in p) for p in pos.values()}
        self.assertEqual(len(coords), len(G))
        return pos

    def test_wheel(self):
        self._check(nx.wheel_graph(9))

    def test_cycle(self):
        self._check(nx.cycle_graph(11))

    def test_path(self):
        self._check(nx.path_graph(7))

    def test_star(self):
        self._check(nx.star_graph(8))

    def test_ladder(self):
        self._check(nx.ladder_graph(6))

    def test_complete_four(self):
        self._check(nx.complete_graph(4))

    def test_grid(self):
        G = nx.convert_node_labels_to_integers(nx.grid_2d_graph(3, 4))
        self._check(G)

    def test_diagonal_grid(self):
        self._check(_diagonal_grid(4, 4))

    def test_seeded_tree(self):
        self._check(_seeded_tree(12, seed=20240))

    def test_disconnected(self):
        G = nx.disjoint_union(nx.cycle_graph(3), nx.cycle_graph(3))
        G = nx.disjoint_union(G, nx.path_graph(3))
        self._check(G)

    def test_octahedral(self):
        self._check(nx.octahedral_graph())

    def test_icosahedral(self):
        self._check(nx.icosahedral_graph())

    def test_given_embedding(self):
        G = nx.dodecahedral_graph()
        is_planar, emb = nx.check_planarity(G)
        self.assertTrue(is_planar)
        self._check(emb)


if __name__ == "__main__":
    unittest.main()
