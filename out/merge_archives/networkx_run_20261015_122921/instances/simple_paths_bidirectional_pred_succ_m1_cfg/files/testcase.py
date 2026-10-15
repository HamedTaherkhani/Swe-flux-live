import random
import unittest
from itertools import islice

import networkx as nx


def take_paths(G, source, target, k):
    return list(islice(nx.shortest_simple_paths(G, source, target), k))


def check_paths(tc, G, paths, source, target):
    lengths = [len(p) for p in paths]
    tc.assertEqual(lengths, sorted(lengths))
    tc.assertEqual(len({tuple(p) for p in paths}), len(paths))
    for p in paths:
        tc.assertEqual(p[0], source)
        tc.assertEqual(p[-1], target)
        tc.assertEqual(len(set(p)), len(p))
        for u, v in zip(p, p[1:]):
            tc.assertTrue(G.has_edge(u, v))


class TestShortestSimplePathsBFS(unittest.TestCase):
    def test_grid_undirected(self):
        G = nx.grid_2d_graph(4, 5)
        paths = take_paths(G, (0, 0), (3, 4), 6)
        check_paths(self, G, paths, (0, 0), (3, 4))
        self.assertEqual(len(paths), 6)

    def test_cycle_undirected_both_ways(self):
        G = nx.cycle_graph(11)
        paths = list(nx.shortest_simple_paths(G, 2, 7))
        check_paths(self, G, paths, 2, 7)
        self.assertEqual(len(paths), 2)

    def test_directed_random_gnp(self):
        G = nx.gnp_random_graph(14, 0.25, seed=7, directed=True)
        nodes = sorted(G)
        src, dst = nodes[0], nodes[-1]
        paths = take_paths(G, src, dst, 5)
        check_paths(self, G, paths, src, dst)
        self.assertGreater(len(paths), 0)

    def test_same_source_and_target(self):
        G = nx.path_graph(6)
        paths = list(nx.shortest_simple_paths(G, 3, 3))
        self.assertEqual(paths, [[3]])

    def test_disconnected_raises(self):
        G = nx.Graph()
        nx.add_path(G, range(5))
        nx.add_path(G, range(10, 14))
        with self.assertRaises(nx.NetworkXNoPath):
            take_paths(G, 1, 12, 3)

    def test_directed_one_way_chain_exhausts(self):
        G = nx.DiGraph()
        nx.add_path(G, [0, 1, 2, 3, 4, 5])
        G.add_edges_from([(0, 2), (2, 4), (5, 0), (3, 1)])
        paths = list(nx.shortest_simple_paths(G, 0, 5))
        check_paths(self, G, paths, 0, 5)
        self.assertGreater(len(paths), 1)

    def test_ladder_undirected(self):
        G = nx.ladder_graph(5)
        paths = take_paths(G, 0, 9, 7)
        check_paths(self, G, paths, 0, 9)

    def test_complete_bipartite(self):
        G = nx.complete_bipartite_graph(3, 4)
        paths = take_paths(G, 0, 1, 4)
        check_paths(self, G, paths, 0, 1)

    def test_random_tree_unique_path(self):
        rng = random.Random(1234)
        G = nx.Graph()
        for v in range(1, 16):
            G.add_edge(v, rng.randrange(v))
        paths = list(nx.shortest_simple_paths(G, 15, 9))
        check_paths(self, G, paths, 15, 9)
        self.assertEqual(len(paths), 1)

    def test_directed_layered_dag(self):
        rng = random.Random(99)
        G = nx.DiGraph()
        layers = [[(layer, i) for i in range(rng.randint(2, 3))] for layer in range(5)]
        for a, b in zip(layers, layers[1:]):
            for u in a:
                for v in b:
                    if rng.random() < 0.6:
                        G.add_edge(u, v)
        G.add_edges_from((("s", u) for u in layers[0]))
        G.add_edges_from(((u, "t") for u in layers[-1]))
        paths = take_paths(G, "s", "t", 6)
        check_paths(self, G, paths, "s", "t")

    def test_wheel_with_extra_chord(self):
        G = nx.wheel_graph(8)
        G.add_edge(2, 6)
        paths = take_paths(G, 1, 5, 5)
        check_paths(self, G, paths, 1, 5)

    def test_directed_bidirectional_cycle_with_chords(self):
        G = nx.DiGraph()
        n = 9
        for i in range(n):
            G.add_edge(i, (i + 1) % n)
            if i % 3 == 0:
                G.add_edge((i + 4) % n, i)
        paths = list(nx.shortest_simple_paths(G, 1, 6))
        check_paths(self, G, paths, 1, 6)
