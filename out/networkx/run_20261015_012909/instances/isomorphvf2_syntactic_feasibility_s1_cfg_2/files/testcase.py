import random
import unittest

import networkx as nx
from networkx.algorithms.isomorphism.isomorphvf2 import GMState, GraphMatcher


def build_graphs():
    rng = random.Random(8128)
    G1 = nx.gnp_random_graph(13, 0.38, seed=4021)
    for n in sorted(G1.nodes):
        if rng.random() < 0.3:
            G1.add_edge(n, n)
    keep = sorted(rng.sample(sorted(G1.nodes), 9))
    sub = G1.subgraph(keep).copy()
    for u, v in sorted(sub.edges()):
        if u != v and rng.random() < 0.2:
            sub.remove_edge(u, v)
    names = [chr(ord("a") + i) for i in range(len(keep))]
    rng.shuffle(names)
    relabel = dict(zip(keep, names))
    G2 = nx.relabel_nodes(sub, relabel)
    return G1, G2, relabel


class TestSyntacticFeasibilityDirect(unittest.TestCase):
    def test_candidate_pairs_after_partial_mapping(self):
        G1, G2, relabel = build_graphs()
        gm = GraphMatcher(G1, G2)
        gm.initialize()
        gm.test = "subgraph"
        seeded = sorted(relabel.items())[:3]
        for n1, n2 in seeded:
            GMState(gm, n1, n2)

        results = []
        for n2 in sorted(G2.nodes):
            if n2 in gm.core_2:
                continue
            for n1 in sorted(G1.nodes, key=lambda x: (-G1.degree(x), x)):
                if n1 in gm.core_1:
                    continue
                if (n1 + ord(n2)) % 3 == 0 and n1 % 2 == 1:
                    continue
                results.append(gm.syntactic_feasibility(n1, n2))

        self.assertGreater(len(results), 15)
        self.assertTrue(any(results))
        self.assertFalse(all(results))
        self.assertEqual(len(gm.core_1), len(seeded))
