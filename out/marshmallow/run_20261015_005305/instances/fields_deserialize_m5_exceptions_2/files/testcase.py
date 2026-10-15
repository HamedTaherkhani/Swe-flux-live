"""Deterministic Schema.load scenarios over list-valued fields with layered failures."""

import random
import unittest

from marshmallow import Schema, fields, validate


def _rng(seed):
    return random.Random(seed)


class _Cursor:
    """A hand-written iterator over a sequence that may break at a given position."""

    def __init__(self, items, break_at=None):
        self.items = items
        self.pos = 0
        self.break_at = break_at

    def __iter__(self):
        return self

    def __next__(self):
        if self.break_at is not None and self.pos == self.break_at:
            return self.items[len(self.items) + self.pos]
        if self.pos >= len(self.items):
            raise StopIteration
        item = self.items[self.pos]
        self.pos += 1
        return item


class _Bag:
    """An iterable container that is not a list, tuple or mapping."""

    def __init__(self, items, break_at=None):
        self.items = list(items)
        self.break_at = break_at

    def __iter__(self):
        return _Cursor(self.items, self.break_at)


def _load_outcome(schema, data):
    """Return (result, error) where exactly one is None."""
    try:
        return schema.load(data), None
    except Exception as exc:  # noqa: BLE001
        return None, exc


class ListLoadScenarios(unittest.TestCase):
    def test_clean_integer_batches(self):
        S = Schema.from_dict({"nums": fields.List(fields.Integer())})
        rng = _rng(3)
        rows = [{"nums": [str(rng.randint(0, 999)) for _ in range(rng.randint(4, 9))]} for _ in range(4)]
        out = S(many=True).load(rows)
        self.assertEqual(len(out), 4)
        self.assertTrue(all(isinstance(v, int) for r in out for v in r["nums"]))

    def test_mixed_integer_strings(self):
        S = Schema.from_dict({"nums": fields.List(fields.Integer())})
        rng = _rng(17)
        rows = []
        for _ in range(3):
            vals = []
            for _ in range(rng.randint(6, 10)):
                roll = rng.random()
                if roll < 0.55:
                    vals.append(str(rng.randint(-50, 50)))
                elif roll < 0.8:
                    vals.append("x" + str(rng.randint(0, 9)))
                else:
                    vals.append(rng.choice([True, 2.5, None, "7"]))
            rows.append({"nums": vals})
        res, err = _load_outcome(S(many=True), rows)
        self.assertIsNone(res)
        self.assertIsNotNone(err)
        self.assertGreaterEqual(len(err.messages), 1)

    def test_not_a_list_shapes(self):
        S = Schema.from_dict({"tags": fields.List(fields.String(), allow_none=True)})
        candidates = ["abc", {"a": 1}, 42, None, ("t", "u"), b"raw", ["ok"], {"k"}, 3.5]
        rows = [{"tags": c} for c in candidates]
        res, err = _load_outcome(S(many=True), rows)
        self.assertIsNone(res)
        self.assertEqual(len(err.messages), len(candidates) - 4)

    def test_nested_integer_matrix(self):
        S = Schema.from_dict({"grid": fields.List(fields.List(fields.Integer(validate=validate.Range(0, 20))))})
        rng = _rng(29)
        grid = []
        for r in range(7):
            if r % 3 == 2:
                grid.append(None if r == 2 else "row")
                continue
            grid.append([rng.randint(-3, 24) for _ in range(rng.randint(2, 5))])
        res, err = _load_outcome(S(), {"grid": grid})
        self.assertIsNone(res)
        self.assertIn("grid", err.messages)

    def test_nested_schema_items(self):
        class Item(Schema):
            sku = fields.String(required=True)
            qty = fields.Integer(validate=validate.Range(min=1))

        S = Schema.from_dict({"items": fields.List(fields.Nested(Item))})
        rng = _rng(41)
        items = []
        for i in range(8):
            entry = {"qty": rng.randint(-1, 4)}
            if i % 4 != 1:
                entry["sku"] = "s%d" % i
            items.append(entry if i != 6 else ["bad"])
        res, err = _load_outcome(S(), {"items": items})
        self.assertIsNone(res)
        self.assertGreater(len(err.messages["items"]), 2)

    def test_dict_of_lists(self):
        S = Schema.from_dict({"buckets": fields.Dict(keys=fields.String(), values=fields.List(fields.Float()))})
        rng = _rng(53)
        buckets = {}
        for k in range(6):
            vals = [rng.choice([rng.random(), "nan?", "1e3", "n/a"]) for _ in range(rng.randint(1, 4))]
            buckets["b%d" % k] = vals if k != 4 else "flat"
        res, err = _load_outcome(S(), {"buckets": buckets})
        self.assertIsNone(res)
        self.assertIn("buckets", err.messages)

    def test_tuple_of_lists(self):
        S = Schema.from_dict(
            {"pair": fields.Tuple((fields.List(fields.Integer()), fields.List(fields.Boolean())))}
        )
        rng = _rng(67)
        rows = []
        for i in range(4):
            ints = [rng.choice(["1", "2", "q", 4]) for _ in range(3 + i)]
            bools = [rng.choice(["yes", "no", "maybe", 1, 7]) for _ in range(2 + i)]
            rows.append({"pair": (ints, bools)})
        res, err = _load_outcome(S(many=True), rows)
        self.assertIsNone(res)
        self.assertGreaterEqual(len(err.messages), 1)

    def test_function_division(self):
        S = Schema.from_dict({"ratios": fields.List(fields.Function(deserialize=lambda v: 360 // v))})
        rng = _rng(79)
        seq = [rng.randint(1, 12) for _ in range(9)]
        seq[seq[0] % 9] = seq[1] - seq[1]
        res, err = _load_outcome(S(), {"ratios": seq})
        self.assertIsNone(res)
        self.assertIsInstance(err, ArithmeticError)

    def test_function_lookup_nested(self):
        table = {"a": 1, "b": 2, "c": 3, "d": 4}
        S = Schema.from_dict(
            {"codes": fields.List(fields.List(fields.Function(deserialize=lambda k: table[k])))}
        )
        rng = _rng(83)
        letters = "abcd"
        codes = [[rng.choice(letters) for _ in range(3)] for _ in range(3)]
        codes.insert(2, [1, "b"])
        codes.append(["a", "z", "b"])
        res, err = _load_outcome(S(), {"codes": codes})
        self.assertIsNone(res)
        self.assertIsInstance(err, LookupError)

    def test_custom_iterables(self):
        S = Schema.from_dict({"vals": fields.List(fields.Integer())})
        rng = _rng(97)
        rows = []
        for i in range(5):
            items = [str(rng.randint(0, 9)) if rng.random() < 0.8 else "?" for _ in range(2 + i)]
            rows.append({"vals": _Bag(items)})
        res, err = _load_outcome(S(many=True), rows)
        self.assertIsNone(res)
        self.assertLess(len(err.messages), 5)

    def test_iterator_breaks_midway(self):
        S = Schema.from_dict({"vals": fields.List(fields.Integer())})
        items = ["1", "two", "3", "4", "five", "6"]
        res, err = _load_outcome(S(), {"vals": _Bag(items, break_at=len(items) - 2)})
        self.assertIsNone(res)
        self.assertIsInstance(err, LookupError)

    def test_decimal_amounts(self):
        S = Schema.from_dict({"amounts": fields.List(fields.Decimal(places=2))})
        rng = _rng(101)
        amounts = []
        for _ in range(12):
            roll = rng.random()
            if roll < 0.5:
                amounts.append("%d.%02d" % (rng.randint(0, 99), rng.randint(0, 99)))
            elif roll < 0.75:
                amounts.append("12,5")
            elif roll < 0.9:
                amounts.append("Infinity")
            else:
                amounts.append(rng.randint(0, 5))
        res, err = _load_outcome(S(), {"amounts": amounts})
        self.assertIsNone(res)
        self.assertIn("amounts", err.messages)


if __name__ == "__main__":
    unittest.main()
