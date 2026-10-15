import io
import random
import unittest

import networkx as nx


def _vertex_line(rng, idx, name):
    kind = rng.randrange(3)
    if kind == 0:
        return f'{idx} "{name}"'
    if kind == 1:
        return f"{idx} {name} {rng.randint(1, 9) / 10} {rng.randint(1, 9) / 10} box"
    return f"{idx} {name} {rng.randint(1, 9) / 10} {rng.randint(1, 9) / 10} ellipse ic Red bc Blue"


def _edge_line(rng, ids):
    a, b = rng.choice(ids), rng.choice(ids)
    kind = rng.randrange(5)
    if kind == 0:
        return f"{a} {b}"
    if kind == 1:
        return f"{a} {b} {rng.randint(1, 50) / 4}"
    if kind == 2:
        return f"{a} {b} heavy"
    if kind == 3:
        return f"{a} {b} {rng.randint(1, 9)} c Green"
    return ""


def build_document(seed):
    rng = random.Random(seed)
    out = ["% generated pajek file", "*network"]
    first = [f"n{k}" for k in range(rng.randint(5, 7))]
    out.append(f"*Vertices {len(first)}")
    out += [_vertex_line(rng, i + 1, nm) for i, nm in enumerate(first)]
    out.append("*Network sample graph")
    second = [f"m{k}" for k in range(rng.randint(4, 6))]
    out.append(f"*vertices {len(second)}")
    out += [_vertex_line(rng, i + 1, nm) for i, nm in enumerate(second)]
    out.append("% edges follow")
    out.append("*Edges")
    ids = [str(i + 1) for i in range(len(second) + 2)]
    out += [_edge_line(rng, ids) for _ in range(18)]
    return "\n".join(out) + "\n"


class TestPajekRoundTrip(unittest.TestCase):
    def test_read_mixed_sections(self):
        text = build_document(20240607)
        G = nx.read_pajek(io.BytesIO(text.encode("UTF-8")))
        self.assertIsInstance(G, nx.MultiGraph)
        self.assertFalse(G.is_directed())
        self.assertIn("name", G.graph)
        self.assertGreater(G.number_of_edges(), 5)
        self.assertGreater(G.number_of_nodes(), 8)
