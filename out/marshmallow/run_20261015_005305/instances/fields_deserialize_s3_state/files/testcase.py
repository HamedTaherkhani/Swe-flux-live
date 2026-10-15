import random
import unittest

from marshmallow import Schema, ValidationError, fields, validate


def _make_key(rng, i):
    roll = rng.randrange(10)
    base = rng.randrange(1, 60)
    if roll == 0:
        return "k" + str(base)
    if roll == 1:
        return " " + str(base * 3) + " "
    if roll == 2:
        return str(base) + ".0"
    if roll == 3:
        return str(base) + ".5"
    return "0" * (i % 3) + str((base + i) % 75)


def _make_value(rng, i):
    roll = rng.randrange(10)
    n = rng.randrange(-20, 90)
    if roll == 0:
        return "v" + str(n)
    if roll == 1:
        return str(n)
    if roll == 2:
        return n * 0.5
    if roll == 3:
        return None
    return n + i


def _build_payload(seed, rows):
    rng = random.Random(seed)
    payload = []
    for r in range(rows):
        width = 3 + rng.randrange(4)
        row = {}
        for c in range(width):
            row[_make_key(rng, r * 7 + c)] = _make_value(rng, r + c)
        payload.append(row)
    return payload


class LedgerSchema(Schema):
    buckets = fields.List(
        fields.Dict(
            keys=fields.Integer(validate=validate.Range(min=1, max=70)),
            values=fields.Integer(validate=validate.Range(min=0)),
        )
    )


class MappingLoadTest(unittest.TestCase):
    def test_load_bucket_ledger(self):
        payload = _build_payload(seed=20240611, rows=8)
        with self.assertRaises(ValidationError) as ctx:
            LedgerSchema().load({"buckets": payload})
        err = ctx.exception
        self.assertIn("buckets", err.messages)
        self.assertEqual(len(err.valid_data["buckets"]), len(payload))
        self.assertTrue(all(isinstance(b, dict) for b in err.valid_data["buckets"]))
