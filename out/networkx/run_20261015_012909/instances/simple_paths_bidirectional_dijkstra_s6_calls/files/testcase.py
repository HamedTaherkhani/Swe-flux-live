import random
import unittest

import networkx as nx
from networkx.algorithms.simple_paths import _bidirectional_dijkstra


def _build_graph(seed):
    rng = random.Random(seed)
    G = nx.gnp_random_graph(80, 0.08, seed=seed, directed=True)
    for u, v in G.edges():
        G[u][v]["weight"] = rng.randint(1, 25) + (u * v) % 7
    return G, rng


class TestBidirectionalDijkstraFiltered(unittest.TestCase):
    def test_filtered_bidirectional_searches(self):
        G, rng = _build_graph(191)
        nodes = sorted(G)
        edges = sorted(G.edges())

        results = []

        # first search: only a node filter
        banned = {n for n in nodes if n % 7 == 3}
        src, dst = nodes[1], nodes[-2]
        results.append(_bidirectional_dijkstra(G, src, dst, ignore_nodes=banned))

        # second search: node and edge filters derived from the first result
        first_path = results[0][1]
        banned2 = {n for n in nodes if (n * 5 + 2) % 11 == 0} - set(first_path[:1])
        cut = set(zip(first_path, first_path[1:]))
        cut |= set(rng.sample(edges, 9))
        src2 = first_path[0]
        dst2 = max(
            (n for n in nodes if n not in banned2 and n != src2 and n % 3 == 1),
            key=lambda n: (G.in_degree(n), -n),
        )
        results.append(
            _bidirectional_dijkstra(
                G, src2, dst2, ignore_nodes=banned2, ignore_edges=cut
            )
        )

        # third search: only an edge filter
        cut3 = {e for e in edges if (e[0] + 2 * e[1]) % 6 == 1}
        results.append(
            _bidirectional_dijkstra(G, nodes[0], nodes[-1], ignore_edges=cut3)
        )

        for (length, path), (b_nodes, b_edges) in zip(
            results, [(banned, set()), (banned2, cut), (set(), cut3)]
        ):
            self.assertTrue(nx.is_path(G, path))
            self.assertEqual(
                length,
                sum(G[u][v]["weight"] for u, v in zip(path, path[1:])),
            )
            self.assertFalse(set(path) & b_nodes)
            self.assertFalse(set(zip(path, path[1:])) & b_edges)
