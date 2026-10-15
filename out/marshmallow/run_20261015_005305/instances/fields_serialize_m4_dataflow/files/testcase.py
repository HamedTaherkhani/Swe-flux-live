"""Deterministic scenarios that serialize mapping-valued attributes through Schema.dump."""

import random
import unittest

from marshmallow import Schema, fields


def _rng(seed):
    return random.Random(seed)


def _word(rng, n=4):
    return "".join(rng.choice("abcdefgh") for _ in range(n))


class MappingDumpScenarios(unittest.TestCase):
    def test_untyped_dicts_many(self):
        class S(Schema):
            meta = fields.Dict()
            tags = fields.Dict()

        rng = _rng(11)
        objs = []
        for i in range(9):
            meta = {_word(rng): rng.randint(0, 50) for _ in range(i % 4)}
            tags = None if i % 3 == 0 else {f"t{j}": j for j in range(i % 5)}
            objs.append({"meta": meta, "tags": tags})
        out = S(many=True).dump(objs)
        self.assertEqual(len(out), 9)
        self.assertEqual(sum(1 for o in out if o["tags"] is None), 3)

    def test_key_field_only(self):
        class S(Schema):
            counts = fields.Dict(keys=fields.Str())

        rng = _rng(23)
        data = {_word(rng, 3): rng.random() for _ in range(rng.randint(5, 9))}
        out = S().dump({"counts": data})
        self.assertEqual(len(out["counts"]), len(data))

    def test_value_field_only(self):
        class S(Schema):
            scores = fields.Dict(values=fields.Int())

        rng = _rng(37)
        objs = [
            {"scores": {k: str(rng.randint(1, 99)) for k in range(n)}}
            for n in (rng.randint(2, 6), rng.randint(3, 7))
        ]
        out = S(many=True).dump(objs)
        self.assertTrue(all(isinstance(v, int) for o in out for v in o["scores"].values()))

    def test_both_fields(self):
        class S(Schema):
            prices = fields.Dict(keys=fields.Str(), values=fields.Float())

        rng = _rng(41)
        prices = {i * 7 % 13: rng.randint(1, 500) / 4 for i in range(11)}
        out = S().dump({"prices": prices})
        self.assertTrue(all(isinstance(k, str) for k in out["prices"]))

    def test_nested_dict_values(self):
        class S(Schema):
            grid = fields.Dict(keys=fields.Str(), values=fields.Dict(values=fields.Int()))

        rng = _rng(53)
        grid = {}
        for r in range(6):
            if r % 4 == 3:
                grid[r] = None
            else:
                grid[r] = {c: rng.randint(0, 9) for c in range(rng.randint(0, 4))}
        out = S().dump({"grid": grid})
        self.assertIsNone(out["grid"]["3"])

    def test_list_of_keyed_dicts(self):
        class S(Schema):
            rows = fields.List(fields.Dict(keys=fields.Str()))

        rng = _rng(67)
        rows = []
        for i in range(5):
            rows.append(None if i == 2 else {j * i: _word(rng, 2) for j in range(1, i + 2)})
        out = S().dump({"rows": rows})
        self.assertEqual(len(out["rows"]), 5)

    def test_tuple_of_dicts(self):
        class S(Schema):
            pair = fields.Tuple((fields.Dict(), fields.Dict(values=fields.Str())))

        rng = _rng(79)
        left = {_word(rng, 2): rng.randint(0, 3) for _ in range(4)}
        right = {n: n * n for n in range(rng.randint(3, 6))}
        out = S().dump({"pair": (left, right)})
        self.assertEqual(len(out["pair"]), 2)

    def test_dict_of_lists_of_dicts(self):
        class S(Schema):
            groups = fields.Dict(
                values=fields.List(fields.Dict(keys=fields.Str(), values=fields.Int()))
            )

        rng = _rng(83)
        groups = {}
        for g in range(3):
            groups[_word(rng, 3)] = [
                {rng.randint(0, 20): str(rng.randint(0, 9)) for _ in range(rng.randint(1, 3))}
                for _ in range(g + 1)
            ]
        out = S().dump({"groups": groups})
        self.assertEqual(sum(len(v) for v in out["groups"].values()), 6)

    def test_nested_schema_many(self):
        class Inner(Schema):
            attrs = fields.Dict(values=fields.Str())

        class Outer(Schema):
            children = fields.Nested(Inner, many=True)
            extra = fields.Dict(keys=fields.Int())

        rng = _rng(97)
        children = [
            {"attrs": {_word(rng, 2): rng.randint(0, 9) for _ in range(rng.randint(1, 4))}}
            for _ in range(4)
        ]
        extra = {str(i): i for i in range(rng.randint(2, 5))}
        out = Outer().dump({"children": children, "extra": extra})
        self.assertEqual(len(out["children"]), 4)

    def test_empty_mappings(self):
        class S(Schema):
            a = fields.Dict(values=fields.Int())
            b = fields.Dict(keys=fields.Str())
            c = fields.Dict(keys=fields.Str(), values=fields.Int())

        objs = [{"a": {}, "b": {}, "c": {}}, {"a": None, "b": {}, "c": None}]
        out = S(many=True).dump(objs)
        self.assertEqual(out[0], {"a": {}, "b": {}, "c": {}})

    def test_untyped_inner_dicts(self):
        class S(Schema):
            layers = fields.Dict(keys=fields.Str(), values=fields.Dict())

        rng = _rng(101)
        layers = {}
        for i in range(7):
            layers[i] = None if rng.random() < 0.3 else {"w": rng.randint(0, 5), "i": i}
        out = S().dump({"layers": layers})
        self.assertEqual(len(out["layers"]), 7)

    def test_deep_recursion(self):
        def build(depth, rng):
            if depth == 0:
                return {f"leaf{i}": rng.randint(0, 9) for i in range(rng.randint(1, 3))}
            return {f"n{depth}_{i}": build(depth - 1, rng) for i in range(2)}

        inner = fields.Dict(values=fields.Int())
        for _ in range(2):
            inner = fields.Dict(keys=fields.Str(), values=inner)

        class S(Schema):
            tree = inner

        out = S().dump({"tree": build(2, _rng(113))})
        self.assertEqual(len(out["tree"]), 2)
