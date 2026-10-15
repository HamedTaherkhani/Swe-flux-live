import io
import random
import unittest

import networkx as nx


def _read(text, encoding="UTF-8"):
    """Feed ``text`` through the public Pajek reader via an in-memory file."""
    if isinstance(text, str):
        data = text.encode(encoding)
    else:
        data = text
    return nx.read_pajek(io.BytesIO(data), encoding=encoding)


def _roundtrip(G):
    buf = io.BytesIO()
    nx.write_pajek(G, buf)
    buf.seek(0)
    return nx.read_pajek(buf)


class TestPajekReaderScenarios(unittest.TestCase):
    def test_roundtrip_undirected_weighted(self):
        rng = random.Random(11)
        G = nx.gnm_random_graph(9, 14, seed=5)
        for n in G:
            if rng.random() < 0.6:
                G.nodes[n]["x"] = round(rng.uniform(-1, 1), 2)
                G.nodes[n]["y"] = round(rng.uniform(-1, 1), 2)
        for u, v in G.edges:
            G.edges[u, v]["weight"] = rng.randint(1, 9)
        H = _roundtrip(G)
        self.assertEqual(H.number_of_nodes(), G.number_of_nodes())
        self.assertEqual(H.number_of_edges(), G.number_of_edges())
        self.assertFalse(H.is_directed())

    def test_roundtrip_directed_with_string_attrs(self):
        rng = random.Random(23)
        G = nx.DiGraph()
        names = [f"node {i}" if i % 3 == 0 else f"n{i}" for i in range(7)]
        G.add_nodes_from(names)
        for name in names[::2]:
            G.nodes[name]["color"] = rng.choice(["red", "blue", "dark green"])
        for _ in range(10):
            u, v = rng.sample(names, 2)
            G.add_edge(u, v, kind=rng.choice(["a", "b c"]))
        H = _roundtrip(G)
        self.assertTrue(H.is_directed())
        self.assertEqual(sorted(H.nodes), sorted(names))
        self.assertEqual(H.number_of_edges(), G.number_of_edges())

    def test_mixed_vertex_and_edge_formats(self):
        rng = random.Random(3)
        n = 13
        lines = ["*network", f"*vertices {n}"]
        for i in range(1, n + 1):
            kind = (i * 7) % 5
            if kind == 0:
                lines.append(f"{i} v{i} {rng.random():.2f} {rng.random():.2f} box")
            elif kind == 1:
                lines.append(f"{i} v{i} {rng.random():.2f} {rng.random():.2f}")
            elif kind == 2:
                lines.append(f"{i} v{i} left {rng.random():.2f} ellipse")
            elif kind == 3:
                lines.append(f"{i} v{i}")
            else:
                lines.append(f'{i} "v {i}" 0.5 0.5 circle ic Red bc Blue')
        lines.append("*edges")
        for j in range(17):
            u, v = rng.randint(1, n), rng.randint(1, n)
            kind = (j * 3 + u) % 6
            if kind == 0:
                lines.append(f"{u} {v} {rng.randint(1, 5)}")
            elif kind == 1:
                lines.append(f"{u} {v}")
            elif kind == 2:
                lines.append(f"{u} {v} heavy")
            elif kind == 3:
                lines.append(f"{u}")
            elif kind == 4:
                lines.append("")
            else:
                lines.append(f"{u} {v} 2.5 label e{j}")
        G = _read("\n".join(lines))
        self.assertNotIn("name", G.graph)
        self.assertEqual(G.number_of_nodes() >= n, True)

    def test_named_network_arcs_swallow_later_headers(self):
        rng = random.Random(41)
        n = 8
        lines = ["*Network Field Survey 2", f"*Vertices {n}"]
        lines += [f"{i} p{i} {i / 10:.1f} {1 - i / 10:.1f} triangle" for i in range(1, n + 1)]
        lines.append("*Arcs")
        for k in range(12):
            u, v = rng.sample(range(1, n + 1), 2)
            lines.append(f"{u} {v} {rng.choice(['1', '2.0', 'w', ''])}".rstrip())
            if k == 5:
                lines.append("*Edges")
                lines.append("*Vertices 2")
        G = _read("\n".join(lines))
        self.assertTrue(G.is_directed())
        self.assertTrue(G.graph["name"].startswith("Field"))

    def test_matrix_section_valid(self):
        rng = random.Random(8)
        n = 6
        lines = [f"*vertices {n}"] + [f"{i} m{i}" for i in range(1, n + 1)]
        lines.append("*matrix")
        for r in range(n):
            lines.append(" ".join(str(rng.choice([0, 0, 1, 2])) for _ in range(n)))
        G = _read("\n".join(lines))
        self.assertIsInstance(G, nx.DiGraph)
        self.assertFalse(G.is_multigraph())

    def test_matrix_extra_zero_rows_then_nonzero(self):
        n = 4
        lines = [f"*vertices {n}"] + [f"{i} q{i} 0 0 box" for i in range(1, n + 1)]
        lines.append("*matrix")
        for r in range(n + 3):
            row = ["0"] * n
            if r < n:
                row[(r + 1) % n] = str(r + 1)
            elif r == n + 2:
                row[1] = "3"
            lines.append(" ".join(row))
        with self.assertRaises(Exception):
            _read("\n".join(lines))

    def test_matrix_non_integer_entry(self):
        n = 5
        lines = [f"*vertices {n}"] + [f"{i} r{i}" for i in range(1, n + 1)]
        lines.append("*matrix")
        for r in range(n):
            lines.append(" ".join("1.5" if (r, c) == (3, 2) else str((r + c) % 2) for c in range(n)))
        with self.assertRaises(Exception):
            _read("\n".join(lines))

    def test_vertex_count_exceeds_lines(self):
        lines = ["*vertices 9"] + [f"{i} s{i} 0.1 0.2" for i in range(1, 6)]
        with self.assertRaises(Exception):
            _read("\n".join(lines))

    def test_unbalanced_quote_in_label(self):
        lines = ["*vertices 6"]
        for i in range(1, 7):
            lines.append(f'{i} "t {i} 0 0 box' if i == 4 else f"{i} t{i} 0 0 box")
        with self.assertRaises(Exception):
            _read("\n".join(lines))

    def test_non_ascii_label_with_ascii_encoding(self):
        lines = ["*vertices 3", "1 alpha", "2 beta", "3 café", "*edges", "1 2", "2 3"]
        data = "\n".join(lines).encode("utf-8")
        with self.assertRaises(Exception):
            _read(data, encoding="ascii")

    def test_latin1_labels_decode_cleanly(self):
        names = ["Zürich", "Málaga", "São Paulo", "København", "Genève"]
        lines = [f"*vertices {len(names)}"]
        lines += [f'{i} "{name}" 0.{i} 0.{i} diamond' for i, name in enumerate(names, 1)]
        lines.append("*edges")
        lines += [f"{i} {i % len(names) + 1} {i}" for i in range(1, len(names) + 1)]
        G = _read("\n".join(lines), encoding="latin-1")
        self.assertEqual(set(G.nodes), set(names))
        self.assertEqual(G.number_of_edges(), len(names))

    def test_vertices_header_with_extra_token(self):
        lines = ["*network demo", "*vertices 3 extra", "1 a", "2 b", "3 c"]
        with self.assertRaises(Exception):
            _read("\n".join(lines))

    def test_vertex_line_missing_label(self):
        lines = ["*vertices 5"]
        for i in range(1, 6):
            lines.append(f"{i}" if i == 5 else f"{i} u{i} {i}.0")
        with self.assertRaises(Exception):
            _read("\n".join(lines))

    def test_edges_without_vertex_section(self):
        lines = ["*network orphan", "*edges", "", "7", "  ", "1 2 3.0", "2 3"]
        with self.assertRaises(Exception):
            _read("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
