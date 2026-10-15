"""Schema-level validators driven through Schema.load / Schema.validate."""

import random
import unittest

from marshmallow import Schema, ValidationError, fields, validates_schema


def make_rows(seed, n):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        row = {
            "id": i + rng.randint(0, 3),
            "quantity": rng.randint(0, 12),
            "price": round(rng.uniform(0.5, 40.0), 2),
        }
        if rng.random() < 0.6:
            row["note"] = rng.choice(["ok", "rush", "", "gift", "x"])
        rows.append(row)
    return rows


class LineSchema(Schema):
    id = fields.Int(required=True)
    qty = fields.Int(data_key="quantity", required=True)
    price = fields.Float(required=True)
    note = fields.Str()

    @validates_schema(pass_original=True)
    def check_qty(self, data, original, **kwargs):
        if original.get("quantity", 0) > 9:
            raise ValidationError("too many", "qty")

    @validates_schema
    def check_total(self, data, **kwargs):
        if data["qty"] * data["price"] > 250:
            raise ValidationError("total too high")

    @validates_schema(skip_on_field_errors=False)
    def check_note(self, data, **kwargs):
        note = data.get("note")
        if note is None:
            return
        if note == "":
            raise ValidationError("empty note", "note")
        if note == "rush" and data.get("qty", 0) < 3:
            raise ValidationError("rush needs qty", "rushed")

    @validates_schema(pass_collection=True)
    def check_batch(self, data, many, **kwargs):
        if many and len(data) % 4 == 1:
            raise ValidationError({"batch": ["odd batch"]})


class StrictIdSchema(Schema):
    id = fields.Int(required=True)
    code = fields.Str(data_key="sku")
    label = fields.Str()

    @validates_schema(pass_original=True, skip_on_field_errors=False)
    def check_code(self, data, original, **kwargs):
        code = data.get("code")
        if code is None:
            raise ValidationError("no code", "label")
        if code.startswith("z"):
            raise ValidationError("bad prefix", "code")
        if len(original) > 2:
            raise ValidationError("extra keys", "id")

    @validates_schema
    def boom(self, data, **kwargs):
        if data.get("id") == 13:
            raise TypeError("unlucky")


class TestRunValidatorCFG(unittest.TestCase):
    def test_many_seed_3(self):
        rows = make_rows(3, 17)
        with self.assertRaises(ValidationError) as ctx:
            LineSchema(many=True).load(rows)
        self.assertIsInstance(ctx.exception.messages, dict)

    def test_many_seed_11(self):
        rows = make_rows(11, 24)
        errors = LineSchema(many=True).validate(rows)
        self.assertIsInstance(errors, dict)

    def test_single_clean(self):
        result = LineSchema().load({"id": 1, "quantity": 2, "price": 3.5})
        self.assertEqual(result["qty"], 2)

    def test_single_rush(self):
        errors = LineSchema().validate(
            {"id": 4, "quantity": 1, "price": 9.0, "note": "rush"}
        )
        self.assertTrue(errors)

    def test_field_error_skips(self):
        rows = make_rows(5, 9)
        for idx in range(0, len(rows), 3):
            rows[idx]["price"] = "n/a"
        errors = LineSchema(many=True).validate(rows)
        self.assertTrue(errors)

    def test_exclude_note(self):
        rows = make_rows(21, 13)
        errors = LineSchema(many=True, exclude=("note",)).validate(rows)
        self.assertIsInstance(errors, dict)

    def test_only_subset(self):
        rows = [
            {"id": k, "quantity": (k * 7) % 13, "price": float(k * 3 % 29) + 1}
            for k in range(1, 20)
        ]
        errors = LineSchema(many=True, only=("id", "qty", "price")).validate(rows)
        self.assertIsInstance(errors, dict)

    def test_partial_load(self):
        rows = make_rows(42, 6)
        for row in rows:
            row.pop("price")
        with self.assertRaises(KeyError):
            LineSchema(many=True, partial=True).load(rows)

    def test_strict_codes(self):
        rows = []
        for k in range(15):
            row = {"id": k + 20}
            if k % 3:
                row["sku"] = ("z" if k % 5 == 0 else "a") + str(k)
            if k % 4 == 0:
                row["label"] = "L" + str(k)
            rows.append(row)
        errors = StrictIdSchema(many=True).validate(rows)
        self.assertTrue(errors)

    def test_strict_exclude_label(self):
        rows = []
        for k in range(10):
            row = {"id": k * 2}
            if k % 4:
                row["sku"] = "b" * (k % 3)
            rows.append(row)
        errors = StrictIdSchema(many=True, exclude=("label",)).validate(rows)
        self.assertIsInstance(errors, dict)

    def test_strict_boom(self):
        rows = [{"id": k, "sku": "c" + str(k)} for k in range(10, 16)]
        with self.assertRaises(TypeError):
            StrictIdSchema(many=True).load(rows)

    def test_strict_single_bad(self):
        errors = StrictIdSchema().validate({"id": "zz", "sku": "zed", "label": "q"})
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
