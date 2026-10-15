import itertools
import random
import unittest

import networkx as nx
from networkx.algorithms import isomorphism as iso


def _build_host(seed):
    rng = random.Random(seed)
    host = nx.DiGraph()
    host.add_nodes_from(range(12))
    for u, v in itertools.permutations(range(12), 2):
        if rng.random() < 0.22:
            host.add_edge(u, v)
    return host


def _pattern_from(host, seed):
    rng = random.Random(seed)
    chosen = sorted(rng.sample(sorted(host.nodes), 5))
    pattern = host.subgraph(chosen).copy()
    labels = {n: f"p{i}" for i, n in enumerate(reversed(chosen))}
    return nx.relabel_nodes(pattern, labels)


class TestDiGraphSubgraphSearch(unittest.TestCase):
    def test_induced_subgraph_embeddings(self):
        host = _build_host(2024)
        pattern = _pattern_from(host, 77)
        matcher = iso.DiGraphMatcher(host, pattern)
        embeddings = list(itertools.islice(matcher.subgraph_isomorphisms_iter(), 3))
        self.assertGreaterEqual(len(embeddings), 1)
        for emb in embeddings:
            self.assertEqual(len(emb), pattern.number_of_nodes())
            induced = host.subgraph(emb)
            relabeled = nx.relabel_nodes(induced, emb)
            self.assertEqual(set(relabeled.edges), set(pattern.edges))
