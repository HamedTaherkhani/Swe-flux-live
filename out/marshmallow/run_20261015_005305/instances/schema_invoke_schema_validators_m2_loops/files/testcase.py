import random
import unittest

from marshmallow import (
    EXCLUDE,
    Schema,
    ValidationError,
    fields,
    pre_load,
    validates_schema,
)


def make_rows(seed, count, bad_every=0):
    rng = random.Random(seed)
    rows = []
    for i in range(count):
        qty = rng.randint(1, 40)
        if bad_every and (i + 1) % bad_every == 0:
            qty = "not-a-number"
        rows.append({"sku": f"S{rng.randint(100, 999)}", "qty": qty})
    return rows


class ItemSchema(Schema):
    sku = fields.String(required=True)
    qty = fields.Integer(required=True)

    @validates_schema
    def check_qty(self, data, **kwargs):
        if data["qty"] % 7 == 0:
            raise ValidationError("qty multiple of seven", "qty")

    @validates_schema(pass_original=True, skip_on_field_errors=False)
    def check_original(self, data, original_data, **kwargs):
        if len(original_data) != len(data):
            raise ValidationError("shape changed")


class CollectionItemSchema(ItemSchema):
    @validates_schema(pass_collection=True)
    def check_collection(self, data, many, **kwargs):
        if many and len(data) > 30:
            raise ValidationError("too many rows")


class StrictItemSchema(CollectionItemSchema):
    @validates_schema(skip_on_field_errors=True)
    def check_sku(self, data, **kwargs):
        if not data["sku"].startswith("S"):
            raise ValidationError("bad sku", "sku")


class OrderSchema(Schema):
    order_id = fields.Integer(required=True)
    lines = fields.Nested(ItemSchema, many=True)
    gift = fields.Nested(ItemSchema)

    @validates_schema
    def check_order(self, data, **kwargs):
        if data["order_id"] < 0:
            raise ValidationError("negative id")


class PreloadFailingSchema(ItemSchema):
    @pre_load(pass_collection=True)
    def reject_large(self, data, many, **kwargs):
        if many and len(data) > 10:
            raise ValidationError("rejected in pre_load")
        return data


class InvokeSchemaValidatorsLoopTest(unittest.TestCase):
    def test_single_item_load(self):
        result = ItemSchema().load({"sku": "S123", "qty": 5})
        self.assertEqual(result["qty"], 5)

    def test_many_clean_rows(self):
        rows = make_rows(11, 18)
        errors = ItemSchema(many=True).validate(rows)
        self.assertIsInstance(errors, dict)

    def test_many_rows_with_field_errors(self):
        rows = make_rows(22, 21, bad_every=5)
        errors = ItemSchema(many=True).validate(rows)
        self.assertTrue(errors)

    def test_collection_schema_many(self):
        rows = make_rows(33, 16)
        errors = CollectionItemSchema().validate(rows, many=True)
        self.assertIsInstance(errors, dict)

    def test_strict_schema_many_mixed(self):
        rows = make_rows(44, 13, bad_every=4)
        errors = StrictItemSchema(many=True).validate(rows)
        self.assertTrue(errors)

    def test_strict_schema_many_clean(self):
        rows = make_rows(55, 2 * 9 + 1)
        errors = StrictItemSchema(many=True).validate(rows)
        self.assertIsInstance(errors, dict)

    def test_nested_order(self):
        payload = {
            "order_id": 7,
            "lines": make_rows(66, 14),
            "gift": {"sku": "S500", "qty": 3},
        }
        errors = OrderSchema().validate(payload)
        self.assertIsInstance(errors, dict)

    def test_many_orders_nested(self):
        orders = [
            {"order_id": n, "lines": make_rows(70 + n, n + 2)} for n in range(5)
        ]
        errors = OrderSchema(many=True).validate(orders)
        self.assertIsInstance(errors, dict)

    def test_preload_rejects(self):
        rows = make_rows(88, 12)
        with self.assertRaises(ValidationError):
            PreloadFailingSchema(many=True).load(rows)

    def test_preload_accepts(self):
        rows = make_rows(99, 9)
        errors = PreloadFailingSchema(many=True).validate(rows)
        self.assertIsInstance(errors, dict)

    def test_unknown_excluded_many(self):
        rows = [dict(r, extra=i) for i, r in enumerate(make_rows(101, 17))]
        errors = StrictItemSchema(many=True, unknown=EXCLUDE).validate(rows)
        self.assertIsInstance(errors, dict)

    def test_many_large_collection(self):
        rows = make_rows(123, 33, bad_every=11)
        errors = CollectionItemSchema(many=True).validate(rows)
        self.assertTrue(errors)
