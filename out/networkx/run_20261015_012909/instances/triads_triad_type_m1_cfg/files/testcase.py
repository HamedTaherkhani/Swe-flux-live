"""Scenarios that classify every triad of assorted directed graphs."""

import random
import unittest
from math import comb

import networkx as nx


def _census_total(result):
    return sum(len(v) for v in result.values())


class TestTriadsByTypeScenarios(unittest.TestCase):
    def _check(self, G):
        result = nx.triads_by_type(G)
        n = G.number_of_nodes()
        self.assertEqual(_census_total(result), comb(n, 3))
        for triads in result.values():
            for t in triads:
                self.assertEqual(t.number_of_nodes(), 3)
        return result

    def test_seeded_gnp_sparse(self):
        G = nx.gnp_random_graph(7, 0.22, seed=11, directed=True)
        self._check(G)

    def test_seeded_gnp_dense(self):
        G = nx.gnp_random_graph(6, 0.63, seed=5, directed=True)
        self._check(G)

    def test_random_tournament(self):
        G = nx.tournament.random_tournament(6, seed=3)
        result = self._check(G)
        self.assertEqual(len(result), 2)

    def test_directed_path_with_back_edges(self):
        G = nx.DiGraph()
        G.add_nodes_from(range(6))
        for i in range(5):
            G.add_edge(i, i + 1)
            if i % 2 == 0:
                G.add_edge(i + 1, i)
        self._check(G)

    def test_cycle_with_chords(self):
        G = nx.cycle_graph(6, create_using=nx.DiGraph)
        for i in range(0, 6, 3):
            G.add_edge(i, (i + 2) % 6)
            G.add_edge((i + 4) % 6, i)
        self._check(G)

    def test_out_and_in_stars(self):
        G = nx.DiGraph()
        G.add_edges_from((0, k) for k in range(1, 4))
        G.add_edges_from((k, 4) for k in range(1, 4))
        self._check(G)

    def test_mostly_isolated_nodes(self):
        G = nx.DiGraph()
        G.add_nodes_from(range(0, 14, 2))
        G.add_edges_from([(6, 2), (2, 6), (12, 6)])
        self._check(G)

    def test_reciprocal_ladder(self):
        G = nx.DiGraph()
        rng = random.Random(29)
        nodes = list(range(5))
        for u in nodes:
            for v in nodes:
                if u < v and rng.random() < 0.6:
                    G.add_edge(u, v)
                    if rng.random() < 0.5:
                        G.add_edge(v, u)
        G.add_nodes_from(nodes)
        self._check(G)

    def test_complete_minus_some(self):
        G = nx.complete_graph(5, create_using=nx.DiGraph)
        G.remove_edges_from([(u, v) for u, v in list(G.edges()) if (u * 3 + v) % 4 == 1])
        self._check(G)

    def test_self_loop_aborts(self):
        G = nx.DiGraph()
        G.add_edges_from([(1, 2), (2, 3), (3, 1), (2, 4), (4, 2)])
        G.add_edge(4, 4)
        with self.assertRaises(nx.NetworkXAlgorithmError):
            nx.triads_by_type(G)

    def test_gnc_growth(self):
        G = nx.gnc_graph(7, seed=8)
        self._check(G)

    def test_relabelled_shuffle(self):
        base = nx.gnp_random_graph(6, 0.4, seed=21, directed=True)
        order = list(base.nodes())
        random.Random(4).shuffle(order)
        H = nx.DiGraph()
        H.add_nodes_from(order)
        H.add_edges_from(sorted(base.edges(), key=lambda e: (-e[1], e[0])))
        self._check(H)
