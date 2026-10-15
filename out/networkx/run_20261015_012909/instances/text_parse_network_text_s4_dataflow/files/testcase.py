import random
import unittest

import networkx as nx
from networkx.readwrite.text import _parse_network_text


def _random_forest(seed, n_nodes, n_extra, directed):
    rng = random.Random(seed)
    G = nx.DiGraph() if directed else nx.Graph()
    G.add_nodes_from(range(n_nodes))
    for v in range(1, n_nodes):
        if rng.random() < 0.85:
            u = rng.randrange(v)
            G.add_edge(u, v) if rng.random() < 0.7 or not directed else G.add_edge(v, u)
    for _ in range(n_extra):
        u, v = rng.sample(range(n_nodes), 2)
        G.add_edge(u, v)
    return nx.relabel_nodes(G, {n: f"n{(n * 7 + seed) % 97}" for n in G})


class TestParseNetworkTextRoundTrips(unittest.TestCase):
    def test_parse_many_renderings(self):
        scenarios = []
        for seed in range(4):
            directed = seed % 2 == 1
            G = _random_forest(seed + 11, 9 + 3 * seed, seed, directed)
            opts = {
                "ascii_only": seed in (1, 2),
                "vertical_chains": seed >= 2,
            }
            scenarios.append((G, opts, True))
        deep = _random_forest(5, 14, 2, False)
        scenarios.append((deep, {"max_depth": 3, "vertical_chains": True}, False))
        chain = nx.relabel_nodes(
            nx.path_graph(6, create_using=nx.DiGraph), lambda i: f"c{i * i}"
        )
        scenarios.append((chain, {"ascii_only": True, "max_depth": 4}, False))
        scenarios.append((nx.Graph(), {}, True))

        parsed = []
        for G, opts, full in scenarios:
            lines = list(nx.generate_network_text(G, **opts))
            H = _parse_network_text(lines)
            parsed.append(H)
            if full:
                self.assertEqual(set(H.nodes), set(G.nodes))
                self.assertEqual(H.number_of_edges(), G.number_of_edges())
            else:
                self.assertTrue(set(H.nodes) <= set(G.nodes))
                self.assertLessEqual(H.number_of_nodes(), G.number_of_nodes())
                self.assertLessEqual(H.number_of_edges(), G.number_of_edges())

        empty = _parse_network_text([])
        self.assertEqual(empty.number_of_nodes(), 0)
        self.assertGreater(sum(H.number_of_nodes() for H in parsed), 40)


if __name__ == "__main__":
    unittest.main()
