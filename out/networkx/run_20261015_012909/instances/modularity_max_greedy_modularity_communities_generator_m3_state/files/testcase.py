import random
import unittest

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities, modularity


def _ring_of_cliques(k, size):
    G = nx.Graph()
    for c in range(k):
        base = c * size
        for i in range(size):
            for j in range(i + 1, size):
                G.add_edge(base + i, base + j)
        G.add_edge(base + size - 1, ((c + 1) % k) * size)
    return G


def _random_weighted(n, p, seed, attr="weight"):
    rng = random.Random(seed)
    G = nx.gnp_random_graph(n, p, seed=seed)
    for u, v in sorted(G.edges()):
        G[u][v][attr] = rng.choice([1, 2, 4])
    return G


def _random_digraph(n, seed):
    rng = random.Random(seed)
    D = nx.DiGraph()
    D.add_nodes_from(range(n))
    for u in range(n):
        for _ in range(2):
            v = rng.randrange(n)
            if v != u:
                D.add_edge(u, v)
    return D


class TestGreedyModularityScenarios(unittest.TestCase):
    def _assert_partition(self, G, comms):
        self.assertEqual(set().union(*comms), set(G))
        self.assertEqual(sum(len(c) for c in comms), len(G))
        sizes = [len(c) for c in comms]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_ring_of_cliques(self):
        G = _ring_of_cliques(3, 4)
        comms = greedy_modularity_communities(G)
        self._assert_partition(G, comms)
        self.assertGreater(modularity(G, comms), 0.3)

    def test_karate_default(self):
        G = nx.karate_club_graph()
        comms = greedy_modularity_communities(G)
        self._assert_partition(G, comms)
        self.assertGreater(len(comms), 1)

    def test_caveman_weighted_low_resolution(self):
        G = nx.relaxed_caveman_graph(3, 4, 0.3, seed=5)
        for u, v in sorted(G.edges()):
            G[u][v]["weight"] = 1 + (u + 2 * v) % 3
        comms = greedy_modularity_communities(G, weight="weight", resolution=0.5)
        self._assert_partition(G, comms)

    def test_random_weighted_graph(self):
        G = _random_weighted(16, 0.25, seed=7)
        comms = greedy_modularity_communities(G, weight="weight")
        self._assert_partition(G, comms)

    def test_high_resolution_path(self):
        G = nx.path_graph(10)
        comms = greedy_modularity_communities(G, resolution=1.75)
        self._assert_partition(G, comms)

    def test_best_n_forces_extra_merges(self):
        G = nx.barbell_graph(5, 2)
        comms = greedy_modularity_communities(G, best_n=1 + 1)
        self._assert_partition(G, comms)
        self.assertLessEqual(len(comms), 2)

    def test_cutoff_stops_early(self):
        G = nx.circular_ladder_graph(7)
        comms = greedy_modularity_communities(G, cutoff=5)
        self._assert_partition(G, comms)
        self.assertGreaterEqual(len(comms), 5)

    def test_directed_random(self):
        D = _random_digraph(12, seed=3)
        comms = greedy_modularity_communities(D)
        self._assert_partition(D, comms)

    def test_multigraph_with_self_loops(self):
        rng = random.Random(11)
        M = nx.MultiGraph()
        for i in range(9):
            M.add_edge(i, (i + 1) % 9)
            M.add_edge(i, rng.randrange(9))
        comms = greedy_modularity_communities(M)
        self._assert_partition(M, comms)

    def test_disconnected_components_exhaust(self):
        G = nx.disjoint_union(nx.star_graph(4), nx.cycle_graph(5))
        G.add_node(99)
        comms = greedy_modularity_communities(G, best_n=len(G) - 6)
        self._assert_partition(G, comms)

    def test_lollipop_relabelled(self):
        G = nx.convert_node_labels_to_integers(
            nx.lollipop_graph(5, 4), first_label=20
        )
        comms = greedy_modularity_communities(G, resolution=0.8)
        self._assert_partition(G, comms)

    def test_grid_weighted_directed(self):
        D = nx.DiGraph(nx.grid_2d_graph(3, 3))
        D = nx.convert_node_labels_to_integers(D, ordering="sorted")
        for u, v in sorted(D.edges()):
            D[u][v]["cap"] = 1 + (u * 3 + v) % 4
        comms = greedy_modularity_communities(D, weight="cap", best_n=4)
        self._assert_partition(D, comms)
        self.assertLessEqual(len(comms), 4)
