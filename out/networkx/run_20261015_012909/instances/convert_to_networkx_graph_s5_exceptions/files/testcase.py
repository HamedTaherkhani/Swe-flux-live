import random
import unittest

import numpy as np

import networkx as nx
from networkx.convert import to_networkx_graph


def _edge_stream(rng, n, pivot):
    for i in range(n):
        u = rng.randrange(12)
        v = (u * 7 + i) % 12
        yield (u, v, {"w": 60 // (pivot - i)})


def _build_inputs(seed):
    rng = random.Random(seed)
    inputs = []
    for k in range(18):
        kind = (k * 5 + rng.randrange(3)) % 7
        n = rng.randrange(5, 11)
        if kind == 0:
            # adjacency stored as lists of neighbours
            data = {u: [(u + j * 3) % n for j in range(1, rng.randrange(2, 4))]
                    for u in range(n)}
            inputs.append((data, None))
        elif kind == 1:
            # plain edge list, some entries carry an extra field
            width = 2 + (rng.random() < 0.5) * 2
            data = [tuple(range(i, i + width)) for i in range(n)]
            inputs.append((data, None))
        elif kind == 2:
            g = nx.path_graph(n)
            target = nx.DiGraph if rng.random() < 0.5 else n
            inputs.append((g, target))
        elif kind == 3:
            shape = (n, n) if rng.random() < 0.5 else (n * n,)
            arr = np.arange(n * n).reshape(shape) % 2
            inputs.append((arr, None))
        elif kind == 4:
            pivot = rng.randrange(2, 2 * n)
            inputs.append((_edge_stream(rng, n, pivot), None))
        elif kind == 5:
            data = {u: u * 2 for u in range(n)}
            inputs.append((data, None))
        else:
            data = [([i], i + 1) if rng.random() < 0.3 else (i, i + 1)
                    for i in range(n)]
            inputs.append((data, None))
    return inputs


class TestToNetworkxGraphExceptions(unittest.TestCase):
    def test_mixed_inputs(self):
        built = 0
        failed = 0
        edges = 0
        for data, create_using in _build_inputs(404):
            try:
                G = to_networkx_graph(data, create_using=create_using)
            except Exception:
                failed += 1
                continue
            built += 1
            edges += G.number_of_edges()
        self.assertEqual(built + failed, 18)
        self.assertGreater(built, 0)
        self.assertGreater(failed, 0)
        print("BUILT", built, "FAILED", failed, "EDGES", edges)


if __name__ == "__main__":
    unittest.main()
