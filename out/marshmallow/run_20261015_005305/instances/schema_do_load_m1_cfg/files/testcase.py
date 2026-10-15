"""Deterministic scenarios that drive marshmallow schema loading through
nested schemas, hooks and validation errors via the public load/loads/validate
entry points."""

import json
import random
import unittest

from marshmallow import (
    EXCLUDE,
    INCLUDE,
    RAISE,
    Schema,
    ValidationError,
    fields,
    post_load,
    pre_load,
    validate,
    validates_schema,
)


class TagSchema(Schema):
    """Plain schema: no hooks at all."""

    label = fields.Str(required=True, validate=validate.Length(min=2))
    weight = fields.Int(load_default=1)


class ItemSchema(Schema):
    """Schema with a pre_load hook that can reject the raw input."""

    sku = fields.Str(required=True)
    qty = fields.Int(required=True, validate=validate.Range(min=1))
    tags = fields.List(fields.Nested(TagSchema), load_default=list)

    @pre_load
    def normalize(self, data, **kwargs):
        if not isinstance(data, dict):
            raise ValidationError("item must be an object")
        if data.get("sku", "").startswith("X"):
            raise ValidationError("forbidden sku prefix", "sku")
        out = dict(data)
        if "quantity" in out:
            out["qty"] = out.pop("quantity")
        return out


class AddressSchema(Schema):
    """Schema with a schema-level validator only."""

    city = fields.Str(required=True)
    zip_code = fields.Str(required=True, data_key="zip")

    @validates_schema
    def check_zip(self, data, **kwargs):
        if not data["zip_code"].isdigit():
            raise ValidationError("zip must be numeric", "zip_code")


class OrderSchema(Schema):
    """Schema with pre_load, validates_schema and post_load hooks."""

    order_id = fields.Int(required=True)
    items = fields.List(fields.Nested(ItemSchema), required=True)
    ship_to = fields.Nested(AddressSchema, allow_none=True)
    note = fields.Str()

    @pre_load
    def strip_meta(self, data, **kwargs):
        return {k: v for k, v in data.items() if not k.startswith("_")}

    @validates_schema
    def check_total(self, data, **kwargs):
        total = sum(it["qty"] for it in data["items"])
        if total > 50:
            raise ValidationError("too many units")

    @post_load
    def finalize(self, data, **kwargs):
        if data["order_id"] % 7 == 0:
            raise ValidationError("unlucky order id", "order_id")
        data["units"] = sum(it["qty"] for it in data["items"])
        return data


class BatchSchema(Schema):
    """Top-level wrapper with nested many=True orders and a plain tag list."""

    batch = fields.Str(required=True)
    orders = fields.Nested(OrderSchema, many=True)
    labels = fields.Nested(TagSchema, many=True, load_default=list)


def make_item(rng, idx, bad_every=0):
    sku = ("X" if bad_every and idx % bad_every == 0 else "S") + str(rng.randint(100, 999))
    key = "quantity" if idx % 3 == 0 else "qty"
    item = {"sku": sku, key: rng.randint(0, 6)}
    ntags = rng.randint(0, 3)
    if ntags:
        item["tags"] = [
            {"label": rng.choice(["a", "red", "blue", "ok"]), "weight": rng.randint(1, 4)}
            for _ in range(ntags)
        ]
    return item


def make_order(rng, oid, nitems, bad_every=0, with_addr=True):
    order = {
        "order_id": oid,
        "items": [make_item(rng, i, bad_every) for i in range(nitems)],
        "_trace": rng.random(),
    }
    if with_addr:
        order["ship_to"] = {
            "city": rng.choice(["Oslo", "Lima", "Pune"]),
            "zip": rng.choice(["1000", "20A0", "3300"]),
        }
    return order


class TestDoLoadPaths(unittest.TestCase):
    def test_01_plain_tags_many(self):
        rng = random.Random(11)
        data = [{"label": "t" * rng.randint(1, 4)} for _ in range(6)]
        data.insert(rng.randint(0, 6), {"label": "t" * (len(data) % 2)})
        with self.assertRaises(ValidationError) as cm:
            TagSchema(many=True).load(data)
        self.assertIsInstance(cm.exception.messages, dict)

    def test_02_plain_tags_valid_loads(self):
        rng = random.Random(12)
        data = [{"label": "ab" + str(rng.randint(0, 9)), "weight": i} for i in range(5)]
        out = TagSchema().loads(json.dumps(data), many=True)
        self.assertEqual(len(out), 5)

    def test_03_item_pre_load_reject_non_dict(self):
        with self.assertRaises(ValidationError):
            ItemSchema().load(["not", "a", "dict"])

    def test_04_items_mixed(self):
        rng = random.Random(4)
        items = [make_item(rng, i, bad_every=4) for i in range(9)]
        schema = ItemSchema(many=True)
        results = []
        for it in items:
            try:
                results.append(schema.load(it, many=False))
            except ValidationError:
                results.append(None)
        self.assertEqual(len(results), 9)

    def test_05_address_validate(self):
        rng = random.Random(5)
        addrs = [{"city": "C" + str(i), "zip": rng.choice(["12", "1b", "77"])} for i in range(7)]
        errs = [AddressSchema().validate(a) for a in addrs]
        self.assertEqual(len(errs), 7)

    def test_06_single_order(self):
        rng = random.Random(6)
        order = make_order(rng, 10, 4)
        try:
            OrderSchema().load(order)
        except ValidationError as err:
            self.assertTrue(err.messages)

    def test_07_order_unlucky_postload(self):
        rng = random.Random(7)
        order = make_order(rng, 14, 2, with_addr=False)
        for it in order["items"]:
            it["qty" if "qty" in it else "quantity"] = 2
            it.pop("tags", None)
        with self.assertRaises(ValidationError):
            OrderSchema().load(order)

    def test_08_order_validate_skips_postload(self):
        rng = random.Random(8)
        order = make_order(rng, 21, 3, with_addr=False)
        for it in order["items"]:
            it["qty" if "qty" in it else "quantity"] = 3
        errors = OrderSchema().validate(order)
        self.assertIsInstance(errors, dict)

    def test_09_batch_loads(self):
        rng = random.Random(9)
        payload = {
            "batch": "B9",
            "orders": [make_order(rng, 30 + k, 2 + k % 3, bad_every=5) for k in range(4)],
            "labels": [{"label": "zz"}, {"label": "q"}],
        }
        try:
            BatchSchema().loads(json.dumps(payload))
        except ValidationError as err:
            self.assertIn("orders", err.messages)

    def test_10_batch_unknown_raise(self):
        rng = random.Random(10)
        payload = {
            "batch": "B10",
            "orders": [make_order(rng, 40 + k, 1) for k in range(3)],
            "extra": 1,
        }
        with self.assertRaises(ValidationError):
            BatchSchema(unknown=RAISE).load(payload)

    def test_11_big_order_too_many_units(self):
        rng = random.Random(1111)
        order = make_order(rng, 50, 13)
        for it in order["items"]:
            key = "qty" if "qty" in it else "quantity"
            it[key] = max(it[key], 1) + 3
        try:
            OrderSchema(unknown=EXCLUDE).load(order)
        except ValidationError as err:
            self.assertTrue(err.messages)

    def test_12_batch_include_partial(self):
        rng = random.Random(12)
        payload = {
            "batch": "B12",
            "orders": [
                {"order_id": 60 + k, "items": [make_item(rng, j) for j in range(k + 1)]}
                for k in range(3)
            ],
            "flag": True,
        }
        try:
            out = BatchSchema(unknown=INCLUDE).load(payload, partial=True)
            self.assertIn("flag", out)
        except ValidationError as err:
            self.assertTrue(err.messages)

    def test_13_clean_orders_one_by_one(self):
        rng = random.Random(1313)
        schema = OrderSchema()
        outcomes = []
        for _ in range(8):
            oid = rng.randint(1, 60)
            order = {
                "order_id": oid,
                "items": [
                    {"sku": "S" + str(rng.randint(10, 99)), "qty": rng.randint(1, 4)}
                    for _ in range(rng.randint(1, 3))
                ],
            }
            try:
                outcomes.append(schema.load(order)["units"] > 0)
            except ValidationError as err:
                outcomes.append("order_id" in err.messages)
        self.assertEqual(len(outcomes), 8)


if __name__ == "__main__":
    unittest.main()
