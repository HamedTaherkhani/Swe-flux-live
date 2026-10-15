import random
import unittest

import networkx as nx
from networkx.algorithms.isomorphism import ISMAGS


def _seeded_digraph(n, p_one_way, p_mutual, seed):
    rng = random.Random(seed)
    g = nx.DiGraph()
    g.add_nodes_from(range(n))
    for u in range(n):
        for v in range(u + 1, n):
            r = rng.random()
            if r < p_mutual:
                g.add_edge(u, v)
                g.add_edge(v, u)
            elif r < p_mutual + p_one_way:
                if rng.random() < 0.5:
                    g.add_edge(u, v)
                else:
                    g.add_edge(v, u)
    return g


class TestIsmagsMixedSearches(unittest.TestCase):
    def test_directed_and_undirected_searches(self):
        # Directed host graph and a pattern lifted out of it.
        host = _seeded_digraph(9, 0.35, 0.15, seed=2024)
        picked = sorted(host, key=lambda n: (-host.degree(n), n))[:4]
        pattern = nx.DiGraph(host.subgraph(picked))
        pattern = nx.relabel_nodes(pattern, {n: f"p{i}" for i, n in enumerate(picked)})

        ism = ISMAGS(host, pattern)
        induced = list(ism.subgraph_isomorphisms_iter(symmetry=True))
        mono = list(ism.monomorphisms_iter(symmetry=True))
        self.assertGreaterEqual(len(mono), len(induced))
        self.assertTrue(induced)
        for m in induced:
            self.assertEqual(len(m), pattern.number_of_nodes())

        # Largest common subgraph of a cycle-with-chords pattern and the host.
        lcs_pattern = nx.DiGraph()
        k = 5
        for i in range(k):
            lcs_pattern.add_edge(("c", i), ("c", (i + 1) % k))
        lcs_pattern.add_edge(("c", 0), ("c", 2))
        lcs_pattern.add_edge(("c", 2), ("c", 0))
        lcs = list(ISMAGS(host, lcs_pattern).largest_common_subgraph(symmetry=True))
        self.assertTrue(lcs)
        sizes = {len(m) for m in lcs}
        self.assertEqual(len(sizes), 1)

        # Undirected: wheel-like pattern searched inside a seeded random graph.
        ug = nx.gnp_random_graph(10, 0.45, seed=7)
        upat = nx.cycle_graph(4)
        upat.add_edge(0, 2)
        upat = nx.relabel_nodes(upat, {1: 2 * upat.number_of_nodes()})
        uism = ISMAGS(ug, upat)
        u_induced = list(uism.subgraph_isomorphisms_iter(symmetry=True))
        u_mono = list(uism.monomorphisms_iter(symmetry=False))
        self.assertGreaterEqual(len(u_mono), len(u_induced))
        for m in u_mono:
            self.assertTrue(
                all(ug.has_edge(a, b) for a in m for b in m if upat.has_edge(m[a], m[b]))
            )
