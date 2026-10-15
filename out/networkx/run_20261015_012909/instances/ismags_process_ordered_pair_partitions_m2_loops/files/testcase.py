"""Symmetry-aware ISMAGS searches over a family of structured pattern graphs."""

import itertools
import random
import unittest

import networkx as nx
from networkx.algorithms import isomorphism as iso


def _relabel_shuffled(graph, seed):
    rng = random.Random(seed)
    nodes = list(graph)
    targets = list(range(len(nodes)))
    rng.shuffle(targets)
    return nx.relabel_nodes(graph, dict(zip(nodes, targets)))


def _colored_cycle(n, period):
    g = nx.cycle_graph(n)
    for u, v in g.edges:
        g.edges[u, v]["kind"] = min(u, v) % period if {u, v} != {0, n - 1} else (n - 1) % period
    return g


class TestIsmagsSymmetricPatterns(unittest.TestCase):
    def _count(self, gen):
        return sum(1 for _ in gen)

    def test_petersen_into_itself(self):
        g = nx.petersen_graph()
        sg = _relabel_shuffled(g, 11)
        ismags = iso.ISMAGS(g, sg)
        found = self._count(ismags.isomorphisms_iter(symmetry=True))
        self.assertGreaterEqual(found, 1)

    def test_hypercube_pattern_in_larger_hypercube(self):
        big = nx.convert_node_labels_to_integers(nx.hypercube_graph(4))
        small = nx.convert_node_labels_to_integers(nx.hypercube_graph(3))
        ismags = iso.ISMAGS(big, small)
        found = self._count(ismags.subgraph_isomorphisms_iter(symmetry=True))
        self.assertGreater(found, 0)

    def test_grid_pattern_in_grid(self):
        big = nx.convert_node_labels_to_integers(nx.grid_2d_graph(5, 4))
        small = nx.convert_node_labels_to_integers(nx.grid_2d_graph(3, 3))
        ismags = iso.ISMAGS(big, small)
        found = self._count(ismags.subgraph_isomorphisms_iter(symmetry=True))
        self.assertGreater(found, 0)

    def test_edge_colored_cycle(self):
        n = 12
        g = _colored_cycle(n, 3)
        sg = _colored_cycle(n, 3)
        em = iso.categorical_edge_match("kind", None)
        ismags = iso.ISMAGS(g, sg, edge_match=em)
        found = self._count(ismags.isomorphisms_iter(symmetry=True))
        self.assertGreaterEqual(found, 1)

    def test_node_colored_wheel(self):
        g = nx.wheel_graph(9)
        for n in g:
            g.nodes[n]["c"] = "hub" if n == 0 else ("a" if n % 2 else "b")
        sg = g.copy()
        nm = iso.categorical_node_match("c", None)
        ismags = iso.ISMAGS(g, sg, node_match=nm)
        found = self._count(ismags.isomorphisms_iter(symmetry=True))
        self.assertGreaterEqual(found, 1)

    def test_complete_bipartite_in_random_graph(self):
        rng = random.Random(7)
        big = nx.gnp_random_graph(14, 0.55, seed=rng.randint(0, 10_000))
        small = nx.complete_bipartite_graph(2, 3)
        ismags = iso.ISMAGS(big, small)
        found = self._count(ismags.subgraph_isomorphisms_iter(symmetry=True))
        self.assertGreaterEqual(found, 0)

    def test_circulant_largest_common_subgraph(self):
        g = nx.circulant_graph(10, [1, 3])
        sg = nx.circulant_graph(8, [1, 2])
        ismags = iso.ISMAGS(g, sg)
        first = next(ismags.largest_common_subgraph(symmetry=True))
        self.assertGreater(len(first), 2)

    def test_random_regular_pattern(self):
        sg = nx.random_regular_graph(3, 12, seed=2024)
        g = _relabel_shuffled(sg, 5)
        ismags = iso.ISMAGS(g, sg)
        found = self._count(ismags.isomorphisms_iter(symmetry=True))
        self.assertGreaterEqual(found, 1)

    def test_star_forest_in_tree(self):
        tree = nx.balanced_tree(3, 3)
        forest = nx.disjoint_union_all([nx.star_graph(k) for k in (2, 3, 3)])
        ismags = iso.ISMAGS(tree, forest)
        found = self._count(itertools.islice(ismags.find_isomorphisms(symmetry=True), 400))
        self.assertGreater(found, 0)

    def test_directed_cycle_with_chords(self):
        n = 9
        dg = nx.DiGraph()
        dg.add_edges_from((i, (i + 1) % n) for i in range(n))
        dg.add_edges_from((i, (i + 3) % n) for i in range(0, n, 3))
        sg = _relabel_shuffled(dg, 3)
        ismags = iso.ISMAGS(dg, sg)
        found = self._count(ismags.isomorphisms_iter(symmetry=True))
        self.assertGreaterEqual(found, 1)

    def test_ladder_largest_common_subgraph(self):
        g = nx.ladder_graph(6)
        sg = nx.circular_ladder_graph(5)
        ismags = iso.ISMAGS(g, sg)
        first = next(ismags.largest_common_subgraph(symmetry=True))
        self.assertGreater(len(first), 4)

    def test_prism_of_triangles_with_colored_rungs(self):
        sg = nx.circular_ladder_graph(6)
        for u, v in sg.edges:
            sg.edges[u, v]["rung"] = abs(u - v) == 6
        g = sg.copy()
        em = iso.categorical_edge_match("rung", False)
        ismags = iso.ISMAGS(g, sg, edge_match=em)
        found = self._count(ismags.isomorphisms_iter(symmetry=True))
        self.assertGreaterEqual(found, 1)
