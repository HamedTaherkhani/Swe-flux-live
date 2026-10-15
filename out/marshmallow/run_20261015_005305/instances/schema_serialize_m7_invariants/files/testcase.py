"""Deterministic serialization scenarios for order/catalog schemas.

Every scenario enters through the public ``Schema.dump`` / ``Schema.dumps``
API; nested schemas, list fields, defaults and data keys are all exercised."""

import json
import random
import unittest

from marshmallow import Schema, fields


class Bag:
    """Attribute bag used as a plain object to serialize."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ItemSchema(Schema):
    sku = fields.String()
    qty = fields.Integer()
    price = fields.Float(data_key="unitPrice")
    note = fields.String(dump_default=None)
    tags = fields.List(fields.String(), dump_default=list)


class OrderSchema(Schema):
    id = fields.Integer()
    customer = fields.String(data_key="customerName")
    items = fields.Nested(ItemSchema, many=True, dump_default=None)
    status = fields.String(dump_default="pending")
    total = fields.Function(
        lambda o: round(
            sum(
                (i["qty"] if isinstance(i, dict) else i.qty)
                * (i["price"] if isinstance(i, dict) else i.price)
                for i in (o["items"] if isinstance(o, dict) else o.items) or []
            ),
            2,
        )
    )
    secret = fields.String(load_only=True)


class NodeSchema(Schema):
    name = fields.String()
    weight = fields.Integer(data_key="w")
    children = fields.Nested(lambda: NodeSchema(), many=True, dump_default=None)


def make_item(rng, idx, as_dict=False, drop_optional=False):
    data = {
        "sku": f"S{rng.randint(100, 999)}-{idx}",
        "qty": rng.randint(1, 9),
        "price": round(rng.uniform(1, 50), 2),
    }
    if not drop_optional:
        data["note"] = rng.choice(["fragile", None, "gift", None])
        data["tags"] = [rng.choice("abc") * (k + 1) for k in range(rng.randint(0, 3))]
    return data if as_dict else Bag(**data)


def make_order(rng, oid, n_items, as_dict=False, drop_optional=False):
    items = [
        make_item(rng, k, as_dict=as_dict or k % 2 == 1, drop_optional=drop_optional and k % 3 == 0)
        for k in range(n_items)
    ]
    data = {"id": oid, "customer": rng.choice(["ann", "bo", None, "cy"]), "items": items}
    if rng.random() < 0.5:
        data["status"] = rng.choice(["paid", "shipped"])
    return data if as_dict else Bag(**data)


def make_tree(rng, depth, fanout):
    node = {"name": f"n{depth}-{rng.randint(0, 99)}", "weight": rng.randint(-5, 5)}
    if depth > 0:
        node["children"] = [make_tree(rng, depth - 1, fanout) for _ in range(fanout)]
    return node


class SerializeInvariantTest(unittest.TestCase):
    def test_01_single_order_objects(self):
        rng = random.Random(11)
        out = OrderSchema().dump(make_order(rng, 1, 4))
        self.assertEqual(len(out["items"]), 4)
        self.assertNotIn("secret", out)

    def test_02_many_orders(self):
        rng = random.Random(22)
        orders = [make_order(rng, i, i % 3 + 1) for i in range(3)]
        out = OrderSchema().dump(orders, many=True)
        self.assertEqual([len(o["items"]) for o in out], [1, 2, 3])

    def test_03_dumps_dict_order(self):
        rng = random.Random(33)
        text = OrderSchema().dumps(make_order(rng, 7, 3, as_dict=True))
        self.assertIn("customerName", json.loads(text))

    def test_04_only_subset_with_nested_only(self):
        rng = random.Random(44)
        schema = OrderSchema(only=("id", "items.sku", "items.price"))
        out = schema.dump(make_order(rng, 9, 5))
        self.assertEqual(sorted(out), ["id", "items"])

    def test_05_exclude_fields(self):
        rng = random.Random(55)
        schema = OrderSchema(exclude=("total", "customer"))
        out = schema.dump(make_order(rng, 10, 2, drop_optional=True))
        self.assertNotIn("total", out)

    def test_06_empty_items(self):
        rng = random.Random(66)
        order = make_order(rng, 12, 0)
        out = OrderSchema().dump(order)
        self.assertEqual(out["total"], 0)

    def test_07_items_none(self):
        order = Bag(id=13, customer="dee", items=None)
        out = OrderSchema().dump(order)
        self.assertIsNone(out["items"])

    def test_08_dropped_optionals(self):
        rng = random.Random(88)
        order = make_order(rng, 14, 4, as_dict=True, drop_optional=True)
        out = OrderSchema().dump(order)
        self.assertEqual(len(out["items"]), 4)

    def test_09_item_schema_many_directly(self):
        rng = random.Random(99)
        items = [make_item(rng, k, as_dict=k % 2 == 0, drop_optional=k % 4 == 3) for k in range(6)]
        out = ItemSchema(many=True).dump(items)
        self.assertEqual(len(out), 6)

    def test_10_tree(self):
        rng = random.Random(10)
        out = NodeSchema().dump(make_tree(rng, 2, 2))
        self.assertEqual(len(out["children"]), 2)

    def test_11_dumps_many_items(self):
        rng = random.Random(111)
        items = [make_item(rng, k) for k in range(3)]
        text = ItemSchema().dumps(items, many=True)
        self.assertEqual(len(json.loads(text)), 3)

    def test_12_leaf_tree_and_only(self):
        rng = random.Random(12)
        out = NodeSchema(only=("name", "children")).dump(make_tree(rng, 1, 3))
        self.assertNotIn("w", out)


if __name__ == "__main__":
    unittest.main()
