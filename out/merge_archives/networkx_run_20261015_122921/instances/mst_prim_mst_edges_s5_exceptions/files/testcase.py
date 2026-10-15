import math
import random
import unittest

import networkx as nx
from networkx.algorithms.tree.mst import prim_mst_edges


def build_graph():
    rng = random.Random(8980)
    G = nx.Graph()
    n = 36
    G.add_nodes_from(range(n))
    # Random spanning chain over a shuffled order keeps the graph connected.
    order = list(range(n))
    rng.shuffle(order)
    for a, b in zip(order, order[1:]):
        G.add_edge(a, b, weight=rng.randint(1, 60), cap=(a * 7 + b) % 13)
    # Extra random chords.
    for _ in range(40):
        a, b = rng.sample(range(n), 2)
        if not G.has_edge(a, b):
            G.add_edge(a, b, weight=rng.randint(1, 60), cap=(a * 7 + b) % 13)
    # Poison a handful of edges whose weight becomes NaN.
    edges = sorted(G.edges())
    for a, b in rng.sample(edges, 2):
        G[a][b]["weight"] = math.nan
    return G


class TestPrimNaNEdge(unittest.TestCase):
    def test_prim_maximum_hits_nan(self):
        G = build_graph()
        produced = []
        failure = None
        try:
            for edge in prim_mst_edges(G, minimum=False, weight="weight", data=True):
                produced.append(edge)
        except Exception as exc:  # noqa: BLE001
            failure = exc
        self.assertIsNotNone(failure)
        self.assertIn("weight", str(failure))
        self.assertLess(len(produced), G.number_of_nodes() - 1)
        self.assertTrue(all(not math.isnan(d["weight"]) for _, _, d in produced))


if __name__ == "__main__":
    unittest.main()
