import random
import unittest

import networkx as nx
from networkx.algorithms.cycles import chordless_cycles


def _undirected_sample(seed, n, m):
    rng = random.Random(seed)
    G = nx.Graph()
    G.add_nodes_from(range(n))
    while G.number_of_edges() < m:
        u, v = rng.sample(range(n), 2)
        G.add_edge(u, v)
    return G


def _directed_multi_sample(seed, n):
    rng = random.Random(seed)
    G = nx.MultiDiGraph()
    G.add_nodes_from(range(n))
    for u in range(n):
        for _ in range(rng.randint(1, 3)):
            G.add_edge(u, (u + rng.choice([1, 2, 3, 5, n - 1])) % n)
    # a few parallel copies and self-loops chosen from the existing structure
    edges = sorted(set(G.edges()))
    for u, w in rng.sample(edges, 3):
        G.add_edge(u, w)
    for u in rng.sample(range(n), 2):
        G.add_edge(u, u)
    return G


def _undirected_multi_sample(seed, n):
    rng = random.Random(seed)
    G = nx.MultiGraph()
    for u in range(n):
        G.add_edge(u, (u + 1) % n)
        G.add_edge(u, (u + rng.randint(2, n - 2)) % n)
    for u in rng.sample(range(n), 3):
        for _ in range(rng.randint(1, 2)):
            G.add_edge(u, (u + 1) % n)
    return G


class TestChordlessCyclesPaths(unittest.TestCase):
    def test_chordless_cycles_batch(self):
        jobs = [
            (_undirected_sample(3, 8, 11), 0),
            (_undirected_sample(11, 9, 14), None),
            (_directed_multi_sample(87, 12), 5),
            (_undirected_multi_sample(7, 7), 3),
            (_directed_multi_sample(41, 6).to_directed(), 2),
        ]
        results = []
        for G, bound in jobs:
            results.append(list(chordless_cycles(G, length_bound=bound)))

        self.assertEqual(results[0], [])
        for (G, bound), cycles in zip(jobs, results):
            for c in cycles:
                if bound is not None:
                    self.assertLessEqual(len(c), bound)
                self.assertTrue(set(c) <= set(G))
        self.assertTrue(all(len(r) > 0 for r in results[1:]))
        self.assertEqual(
            sum(len(r) for r in results),
            sum(len(list(chordless_cycles(G, length_bound=b))) for G, b in jobs),
        )


if __name__ == "__main__":
    unittest.main()
