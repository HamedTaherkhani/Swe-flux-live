import random
import unittest

import networkx as nx


def _color_and_check(testcase, G, strategy):
    coloring = nx.coloring.greedy_color(G, strategy=strategy, interchange=True)
    testcase.assertEqual(set(coloring), set(G))
    for u, v in G.edges():
        testcase.assertNotEqual(coloring[u], coloring[v])
    return coloring


def _seeded_order(seed):
    # Deterministic replacement for the "random_sequential" strategy.
    def strategy(G, colors):
        order = sorted(G, key=repr)
        random.Random(seed).shuffle(order)
        return iter(order)

    return strategy


def _shuffled_crown(n, seed):
    # Crown graph (K_{n,n} minus a perfect matching) with interleaved labels,
    # the classic bad case for plain greedy coloring.
    G = nx.Graph()
    G.add_nodes_from(range(2 * n))
    for i in range(n):
        for j in range(n):
            if i != j:
                G.add_edge(2 * i, 2 * j + 1)
    mapping = list(G)
    random.Random(seed).shuffle(mapping)
    return nx.relabel_nodes(G, dict(zip(G, mapping)))


class TestGreedyColorInterchangeBatch(unittest.TestCase):
    def test_crown_graph_interleaved(self):
        G = _shuffled_crown(7, seed=3)
        coloring = _color_and_check(self, G, _seeded_order(3))
        self.assertLessEqual(max(coloring.values()) + 1, 7)

    def test_gnp_dense_largest_first(self):
        G = nx.gnp_random_graph(24, 0.35, seed=11)
        _color_and_check(self, G, "largest_first")

    def test_gnp_sparse_smallest_last(self):
        G = nx.gnp_random_graph(30, 0.15, seed=29)
        _color_and_check(self, G, "smallest_last")

    def test_petersen_bfs(self):
        G = nx.petersen_graph()
        coloring = _color_and_check(self, G, "connected_sequential_bfs")
        self.assertGreaterEqual(max(coloring.values()) + 1, 3)

    def test_mycielski_dfs(self):
        G = nx.mycielski_graph(5)
        _color_and_check(self, G, "connected_sequential_dfs")

    def test_random_bipartite_shuffled_order(self):
        G = nx.bipartite.random_graph(9, 11, 0.4, seed=5)
        _color_and_check(self, G, _seeded_order(16))

    def test_grid_with_diagonals_custom_order(self):
        G = nx.grid_2d_graph(5, 5)
        G.add_edges_from(((r, c), (r + 1, c + 1)) for r in range(4) for c in range(4) if (r * c) % 3 == 1)
        G = nx.convert_node_labels_to_integers(G, ordering="sorted")
        order = sorted(G, key=lambda v: ((v * 7) % 25, v))

        def strategy(H, colors):
            return iter(order)

        _color_and_check(self, G, strategy)

    def test_wheel_and_cycles_independent_components(self):
        G = nx.disjoint_union_all([nx.wheel_graph(8), nx.cycle_graph(9), nx.cycle_graph(6)])
        _color_and_check(self, G, "largest_first")

    def test_random_regular(self):
        G = nx.random_regular_graph(4, 18, seed=17)
        _color_and_check(self, G, _seeded_order(52))

    def test_watts_strogatz_smallest_last(self):
        G = nx.connected_watts_strogatz_graph(20, 4, 0.3, seed=8)
        _color_and_check(self, G, "smallest_last")

    def test_queens_like_conflict_graph(self):
        n = 5
        G = nx.Graph()
        cells = [(r, c) for r in range(n) for c in range(n)]
        G.add_nodes_from(cells)
        for a in cells:
            for b in cells:
                if a < b and (a[0] == b[0] or a[1] == b[1] or abs(a[0] - b[0]) == abs(a[1] - b[1])) and abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 2:
                    G.add_edge(a, b)
        _color_and_check(self, G, "connected_sequential_bfs")

    def test_random_tree_plus_chords(self):
        G = nx.random_labeled_tree(22, seed=4)
        rng = random.Random(4)
        nodes = sorted(G)
        for _ in range(12):
            u, v = rng.sample(nodes, 2)
            G.add_edge(u, v)
        _color_and_check(self, G, _seeded_order(13))
