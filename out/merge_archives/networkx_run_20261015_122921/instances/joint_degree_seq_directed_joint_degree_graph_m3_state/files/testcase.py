import random
import unittest

import networkx as nx
from networkx.generators.joint_degree_seq import directed_joint_degree_graph


def _profile(g):
    in_degrees = [d for _, d in sorted(g.in_degree())]
    out_degrees = [d for _, d in sorted(g.out_degree())]
    nkk = nx.degree_mixing_dict(g)
    return in_degrees, out_degrees, nkk


class TestDirectedJointDegreeGraph(unittest.TestCase):
    def _check(self, g, seed):
        in_degrees, out_degrees, nkk = _profile(g)
        G = directed_joint_degree_graph(in_degrees, out_degrees, nkk, seed=seed)
        self.assertEqual(in_degrees, [d for _, d in sorted(G.in_degree())])
        self.assertEqual(out_degrees, [d for _, d in sorted(G.out_degree())])
        self.assertEqual(nkk, nx.degree_mixing_dict(G))
        self.assertEqual(G.number_of_edges(), g.number_of_edges())
        self.assertFalse(any(u == v for u, v in G.edges()))
        return G

    def test_gnm_small_sparse(self):
        g = nx.gnm_random_graph(8, 12, seed=3, directed=True)
        self._check(g, seed=11)

    def test_gnm_medium(self):
        g = nx.gnm_random_graph(12, 30, seed=7, directed=True)
        self._check(g, seed=5)

    def test_gnm_dense(self):
        g = nx.gnm_random_graph(10, 55, seed=21, directed=True)
        self._check(g, seed=2)

    def test_directed_cycle_with_chords(self):
        g = nx.cycle_graph(9, create_using=nx.DiGraph)
        g.add_edges_from((i, (i * 4 + 1) % 9) for i in range(0, 9, 2))
        g.remove_edges_from([(u, v) for u, v in g.edges() if u == v])
        self._check(g, seed=17)

    def test_star_out_and_in(self):
        g = nx.DiGraph()
        g.add_edges_from((0, i) for i in range(1, 7))
        g.add_edges_from((i, 7) for i in range(1, 7, 2))
        g.add_edges_from((7, i) for i in range(2, 7, 2))
        self._check(g, seed=29)

    def test_random_tournament(self):
        g = nx.tournament.random_tournament(7, seed=13)
        self._check(g, seed=31)

    def test_scale_free_collapsed(self):
        h = nx.scale_free_graph(14, seed=4)
        g = nx.DiGraph((u, v) for u, v in h.edges() if u != v)
        g = nx.convert_node_labels_to_integers(g)
        self._check(g, seed=8)

    def test_isolated_nodes_present(self):
        g = nx.gnm_random_graph(14, 20, seed=42, directed=True)
        g.add_nodes_from(range(14, 17))
        self._check(g, seed=0)

    def test_bipartite_layers(self):
        rng = random.Random(99)
        g = nx.DiGraph()
        g.add_nodes_from(range(12))
        for u in range(6):
            for v in range(6, 12):
                if rng.random() < 0.55:
                    g.add_edge(u, v)
        self._check(g, seed=77)

    def test_reciprocal_pairs(self):
        g = nx.DiGraph()
        for i in range(0, 10, 2):
            g.add_edge(i, i + 1)
            g.add_edge(i + 1, i)
            g.add_edge(i, (i + 3) % 10)
        self._check(g, seed=123)

    def test_repeated_seeds_same_profile(self):
        g = nx.gnp_random_graph(11, 0.3, seed=55, directed=True)
        a = self._check(g, seed=1)
        b = self._check(g, seed=1)
        self.assertEqual(sorted(a.edges()), sorted(b.edges()))

    def test_unrealizable_raises(self):
        g = nx.gnm_random_graph(9, 15, seed=6, directed=True)
        in_degrees, out_degrees, nkk = _profile(g)
        k = min(nkk)
        l = min(nkk[k])
        nkk[k][l] += 1
        with self.assertRaisesRegex(nx.NetworkXError, "realizable"):
            directed_joint_degree_graph(in_degrees, out_degrees, nkk, seed=3)
