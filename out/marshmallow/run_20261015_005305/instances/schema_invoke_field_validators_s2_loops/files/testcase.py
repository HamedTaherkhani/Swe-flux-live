import random
import unittest

from marshmallow import EXCLUDE, Schema, ValidationError, fields, pre_load, validates


def _build_schema_class(rng):
    names = [f"k{i:02d}" for i in range(9)]
    attrs = {}
    for i, name in enumerate(names):
        if i % 3 == 0:
            attrs[name] = fields.Integer(dump_only=(i == 6))
        elif i % 3 == 1:
            attrs[name] = fields.String(data_key=name.upper())
        else:
            attrs[name] = fields.Float()

    def make_validator(tag):
        def _validator(self, value, data_key):
            self.seen.append((tag, data_key))
            if isinstance(value, (int, float)) and int(value) % 4 == 0:
                raise ValidationError("bad")
            if isinstance(value, str) and len(value) % 5 == 0:
                raise ValidationError("bad")
            return value

        return _validator

    for v in range(5):
        picked = sorted(rng.sample(names, rng.randint(1, 4)))
        attrs[f"check_{v}"] = validates(*picked)(make_validator(v))

    def drop_some(self, data, many, **kwargs):
        kept = []
        for idx, row in enumerate(data):
            score = sum(len(str(x)) for x in row.values()) + idx
            if score % 3 != 1:
                kept.append(row)
        return kept

    attrs["drop_some"] = pre_load(pass_collection=True)(drop_some)
    return type("GeneratedSchema", (Schema,), attrs), names


class InvokeFieldValidatorsLoopTest(unittest.TestCase):
    def test_load_many_with_exclusions(self):
        rng = random.Random(20241015)
        schema_cls, names = _build_schema_class(rng)
        excluded = tuple(n for n in names if rng.random() < 0.3)
        schema = schema_cls(exclude=excluded, many=True, unknown=EXCLUDE)
        schema.seen = []

        rows = []
        for _ in range(27):
            row = {}
            for i, name in enumerate(names):
                if rng.random() < 0.2:
                    continue
                if i % 3 == 0:
                    row[name] = rng.choice([rng.randint(0, 40), "oops"])
                elif i % 3 == 1:
                    row[name.upper()] = "x" * rng.randint(1, 9)
                else:
                    row[name] = round(rng.uniform(0, 30), 2)
            rows.append(row)

        with self.assertRaises(ValidationError) as ctx:
            schema.load(rows)
        self.assertIsInstance(ctx.exception.messages, dict)
        self.assertTrue(schema.seen)
        self.assertLess(len(ctx.exception.valid_data), len(rows))


if __name__ == "__main__":
    unittest.main()
