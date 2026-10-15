import random
import unittest

from marshmallow import Schema, fields, validate


def _slot_field(kind):
    if kind == 0:
        return fields.Integer(validate=validate.Range(min=0, max=40))
    if kind == 1:
        return fields.String(validate=validate.Length(max=6))
    if kind == 2:
        return fields.Tuple((fields.Integer(), fields.Float(), fields.Boolean()))
    if kind == 3:
        return fields.List(fields.Tuple((fields.Integer(), fields.String())))
    return fields.Boolean()


def _slot_value(rng, kind, i):
    roll = rng.randrange(6)
    if kind == 0:
        return [i * 3, str(i * 4), "x" + str(i), i * 7 - 50, None, i][roll]
    if kind == 1:
        return ["ab" * (i % 5), i, "q" * i, None, "ok", "z"][roll]
    if kind == 2:
        n = rng.randrange(-5, 5)
        options = [
            [n, n / 2, True],
            (str(n), "1e" + str(n), "maybe"),
            [n, n],
            "abc",
            [n, "nan?", "yes"],
            (n, 2.5, 0),
        ]
        return options[roll]
    if kind == 3:
        size = 1 + rng.randrange(3)
        return [
            ((j + i) if (j + roll) % 3 else "n" + str(j), "s" * j)
            if (j * roll + i) % 4
            else [j]
            for j in range(size)
        ]
    return ["yes", 2, "0", "off", 1.0, "T"][roll]


def build(seed, width):
    rng = random.Random(seed)
    kinds = [rng.randrange(5) for _ in range(width)]
    values = [_slot_value(rng, kind, i) for i, kind in enumerate(kinds)]
    return kinds, values


class TupleRecordSchemaTest(unittest.TestCase):
    def test_load_record_with_mixed_slots(self):
        kinds, values = build(seed=2024, width=17)

        class RecordSchema(Schema):
            record = fields.Tuple(tuple(_slot_field(k) for k in kinds))

        schema = RecordSchema()
        with self.assertRaises(Exception) as ctx:
            schema.load({"record": values})
        messages = ctx.exception.messages
        self.assertIn("record", messages)
        self.assertGreater(len(messages["record"]), 2)
        self.assertLess(len(messages["record"]), len(kinds))
