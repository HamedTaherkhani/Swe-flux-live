import ast
import io
import random
import unittest

import networkx as nx


def _read(lines, **kwargs):
    """Feed text lines to nx.read_multiline_adjlist through an in-memory file."""
    payload = "".join(line + "\n" for line in lines).encode("utf-8")
    return nx.read_multiline_adjlist(io.BytesIO(payload), **kwargs)


def _blocks(G, delimiter=" "):
    """Split generated multiline adjlist output into (header, [neighbor lines])."""
    out = []
    it = iter(nx.generate_multiline_adjlist(G, delimiter))
    for header in it:
        deg = int(header.rsplit(delimiter, 1)[1])
        out.append((header, [next(it) for _ in range(deg)]))
    return out


def _flatten(blocks):
    return [line for header, nbrs in blocks for line in [header, *nbrs]]


class TestMultilineAdjlistReadScenarios(unittest.TestCase):
    def test_weighted_roundtrip(self):
        rng = random.Random(11)
        G = nx.gnm_random_graph(14, 30, seed=3)
        for u, v in G.edges:
            G[u][v]["weight"] = rng.randint(1, 9)
        buf = io.BytesIO()
        nx.write_multiline_adjlist(G, buf)
        buf.seek(0)
        H = nx.read_multiline_adjlist(buf, nodetype=int)
        self.assertEqual(H.number_of_edges(), G.number_of_edges())
        self.assertTrue(all(H[u][v]["weight"] == d for u, v, d in G.edges(data="weight")))

    def test_digraph_partially_stripped(self):
        rng = random.Random(5)
        G = nx.gnm_random_graph(12, 26, seed=8, directed=True)
        for u, v in G.edges:
            G[u][v]["w"] = rng.randint(0, 4)
        lines = []
        for header, nbrs in _blocks(G):
            lines.append(header)
            for nbr in nbrs:
                v, data = nbr.split(" ", 1)
                lines.append(v if (int(v) + len(data)) % 3 else nbr)
        H = _read(lines, create_using=nx.DiGraph, nodetype=int)
        self.assertEqual(H.number_of_edges(), G.number_of_edges())

    def test_comment_noise(self):
        G = nx.circular_ladder_graph(7)
        lines = []
        k = 0
        for header, nbrs in _blocks(G):
            lines.append(header)
            for nbr in nbrs:
                k += 1
                if k % 4 == 1:
                    lines.append("# filler %d" % k)
                if k % 5 == 2:
                    nbr = nbr.split(" ")[0] + " # trailing"
                lines.append(nbr)
        H = _read(lines)
        self.assertEqual(H.number_of_edges(), G.number_of_edges())

    def test_bad_source_label(self):
        G = nx.path_graph(16)
        blocks = _blocks(G)
        bad = 9
        header, nbrs = blocks[bad]
        blocks[bad] = ("n" + header, nbrs)
        lines =_flatten(blocks[:bad]) + _flatten([blocks[bad]])
        lines = [ln.replace(" {}", "") if i % 2 else ln for i, ln in enumerate(lines)]
        with self.assertRaises(Exception):
            _read(lines, nodetype=int)

    def test_fractional_degree(self):
        G = nx.star_graph(6)
        G.add_edges_from((i, i + 1) for i in range(1, 6))
        lines = []
        for idx, (header, nbrs) in enumerate(_blocks(G)):
            if idx == 4:
                s, d = header.split(" ")
                header = s + " " + d + ".0"
            lines.append(header)
            lines.extend(n.split(" ")[0] for n in nbrs)
        with self.assertRaises(Exception):
            _read(lines)

    def test_comma_delimiter_extra_field(self):
        rng = random.Random(21)
        G = nx.cycle_graph(10)
        for u, v in G.edges:
            G[u][v].update(a=rng.randint(0, 3), b=rng.randint(0, 3))
            if (u + v) % 3 == 0:
                del G[u][v]["b"]
        blocks = _blocks(G, delimiter=",")
        header, nbrs = blocks[7]
        blocks[7] = (header + ",x", nbrs)
        with self.assertRaises(Exception):
            _read(_flatten(blocks), delimiter=",")

    def test_truncated_tail(self):
        G = nx.wheel_graph(9)
        lines = [ln.split(" ")[0] if " " in ln and not ln.split(" ")[1].isdigit() else ln
                 for ln in _flatten(_blocks(G))]
        lines = lines[: len(lines) - 4]
        with self.assertRaises(Exception):
            _read(lines)

    def test_truncated_into_comments(self):
        G = nx.complete_graph(6)
        blocks = _blocks(G)
        lines = _flatten(blocks[:2])
        lines = lines[:-2] + ["# gone %d" % i for i in range(3)]
        with self.assertRaises(Exception):
            _read(lines, nodetype=int)

    def test_edgetype_float_bad_value(self):
        rng = random.Random(4)
        G = nx.grid_2d_graph(3, 4)
        G = nx.convert_node_labels_to_integers(G)
        lines = []
        count = 0
        for header, nbrs in _blocks(G):
            lines.append(header)
            for nbr in nbrs:
                v = nbr.split(" ")[0]
                count += 1
                value = "%d.%d" % (rng.randint(0, 9), rng.randint(0, 9))
                if count == 13:
                    value = value + "e"
                lines.append(v + " " + value)
        with self.assertRaises(Exception):
            _read(lines, edgetype=float)

    def test_non_mapping_literal(self):
        G = nx.path_graph(12)
        lines = []
        for header, nbrs in _blocks(G):
            lines.append(header)
            for nbr in nbrs:
                v = nbr.split(" ")[0]
                n = int(v)
                if n % 4 == 1:
                    lines.append("%s {'w': z%d}" % (v, n))
                elif n == 10:
                    lines.append("%s [%d, %d]" % (v, n, n))
                else:
                    lines.append("%s {'w': %d}" % (v, n))
        with self.assertRaises(Exception):
            _read(lines)

    def test_bad_neighbor_label(self):
        G = nx.balanced_tree(2, 3)
        lines = []
        for header, nbrs in _blocks(G):
            lines.append(header)
            for nbr in nbrs:
                v = nbr.split(" ")[0]
                if v == "11":
                    v = "1/1"
                lines.append(v)
        with self.assertRaises(Exception):
            _read(lines, nodetype=float)

    def test_multigraph_int_weights(self):
        rng = random.Random(9)
        G = nx.MultiGraph()
        for _ in range(18):
            u, v = rng.randrange(7), rng.randrange(7)
            G.add_edge(u, v, weight=rng.randint(1, 50))
        lines = []
        for header, nbrs in _blocks(G):
            lines.append(header)
            for nbr in nbrs:
                v, data = nbr.split(" ", 1)
                lines.append(v + " " + str(ast.literal_eval(data)["weight"]))
        H = _read(lines, create_using=nx.MultiGraph, nodetype=int, edgetype=int)
        self.assertEqual(H.number_of_edges(), G.number_of_edges())

    def test_integer_key_mapping(self):
        G = nx.ladder_graph(6)
        lines = []
        for header, nbrs in _blocks(G):
            lines.append(header)
            for nbr in nbrs:
                v = nbr.split(" ")[0]
                n = int(v)
                if n % 3 == 0:
                    lines.append(v)
                elif n == 8:
                    lines.append("%s {%d: 'k'}" % (v, n))
                else:
                    lines.append("%s {'k': %d}" % (v, n))
        with self.assertRaises(Exception):
            _read(lines, create_using=nx.DiGraph)

    def test_undecodable_neighbor_bytes(self):
        G = nx.lollipop_graph(4, 5)
        rows = []
        for idx, (header, nbrs) in enumerate(_blocks(G)):
            rows.append(header.encode("utf-8"))
            for j, nbr in enumerate(nbrs):
                v = nbr.split(" ")[0]
                row = (v if (idx + j) % 2 else nbr).encode("utf-8")
                if idx == 5 and j == 0:
                    row = row + b" \xff"
                rows.append(row)
        with self.assertRaises(Exception):
            nx.read_multiline_adjlist(io.BytesIO(b"\n".join(rows) + b"\n"))
