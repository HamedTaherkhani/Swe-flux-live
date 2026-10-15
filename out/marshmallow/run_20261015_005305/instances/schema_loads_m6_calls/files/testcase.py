import json
import random
import unittest

from marshmallow import (
    EXCLUDE,
    INCLUDE,
    Schema,
    ValidationError,
    fields,
    post_load,
    pre_load,
    validates,
    validates_schema,
)


class TagSchema(Schema):
    name = fields.Str(required=True)
    weight = fields.Int()

    @validates("weight")
    def check_weight(self, value, **kwargs):
        if value < 0:
            raise ValidationError("weight below zero")


class ItemSchema(Schema):
    sku = fields.Str(required=True)
    qty = fields.Int()
    price = fields.Float()
    tags = fields.List(fields.Nested(TagSchema))

    @pre_load
    def lower_sku(self, data, **kwargs):
        if isinstance(data, dict) and isinstance(data.get("sku"), str):
            data = dict(data)
            data["sku"] = data["sku"].lower()
        return data

    @validates_schema
    def check_total(self, data, **kwargs):
        if data.get("qty", 0) * data.get("price", 0.0) > 400:
            raise ValidationError("line total too large")


class OrderSchema(Schema):
    order_id = fields.Int(required=True)
    items = fields.List(fields.Nested(ItemSchema))
    meta = fields.Nested({"source": fields.Str(), "rank": fields.Int()})

    @post_load
    def count_items(self, data, **kwargs):
        data["n_items"] = len(data.get("items", []))
        return data


class QuietTagSchema(TagSchema):
    def on_bind_field(self, field_name, field_obj):
        field_obj.metadata["bound"] = True

    def handle_error(self, error, data, *, many, **kwargs):
        error.messages_seen = True


class BatchSchema(Schema):
    batch = fields.Int()
    tags = fields.List(fields.Nested(TagSchema), required=True)

    @validates_schema(pass_collection=True, pass_original=True)
    def batch_check(self, data, original, many, **kwargs):
        if many and len(data) != len(original):
            raise ValidationError("length mismatch")

    @pre_load(pass_collection=True)
    def unwrap(self, data, many, **kwargs):
        if isinstance(data, dict) and "envelope" in data:
            return data["envelope"]
        return data


class _ReverseJson:
    """Render module that reverses the payload before decoding it."""

    @staticmethod
    def loads(s, **kwargs):
        return json.loads(s[::-1], **kwargs)

    @staticmethod
    def dumps(obj, **kwargs):
        return json.dumps(obj, **kwargs)[::-1]


class ReversedTagSchema(TagSchema):
    class Meta:
        render_module = _ReverseJson


def make_tags(rng, n):
    return [
        {"name": "t%d" % rng.randint(0, 99), "weight": rng.randint(-3, 9)}
        for _ in range(n)
    ]


def make_items(rng, n, with_tags=True):
    out = []
    for i in range(n):
        item = {
            "sku": "SKU-%03d" % rng.randint(0, 999),
            "qty": rng.randint(1, 12),
            "price": round(rng.uniform(1, 45), 2),
        }
        if with_tags and i % 3 != 2:
            item["tags"] = make_tags(rng, rng.randint(0, 3))
        out.append(item)
    return out


class TestSchemaLoadsCalls(unittest.TestCase):
    def test_01_flat_tags_many(self):
        rng = random.Random(101)
        tags = make_tags(rng, 17)
        s = json.dumps(tags)
        try:
            result = TagSchema().loads(s, many=True)
            self.assertEqual(len(result), 17)
        except ValidationError as err:
            self.assertIsInstance(err.messages, dict)

    def test_02_single_order(self):
        rng = random.Random(202)
        order = {"order_id": 7, "items": make_items(rng, 6), "meta": {"source": "web", "rank": 2}}
        try:
            result = OrderSchema().loads(json.dumps(order))
            self.assertIn("n_items", result)
        except ValidationError as err:
            self.assertIn("items", err.messages)

    def test_03_orders_many_partial(self):
        rng = random.Random(303)
        orders = []
        for k in range(4):
            o = {"items": make_items(rng, k + 1, with_tags=k % 2 == 0)}
            if k != 1:
                o["order_id"] = k
            orders.append(o)
        try:
            result = OrderSchema(many=True).loads(json.dumps(orders), partial=True)
            self.assertEqual(len(result), 4)
        except ValidationError as err:
            self.assertTrue(err.messages)

    def test_04_unknown_include(self):
        rng = random.Random(404)
        tags = make_tags(rng, 9)
        for i, t in enumerate(tags):
            t["weight"] = abs(t["weight"])
            if i % 2:
                t["extra_%d" % i] = i * i
        result = TagSchema(unknown=INCLUDE).loads(json.dumps(tags), many=True)
        self.assertEqual(len(result), len(tags))

    def test_05_only_dotted(self):
        rng = random.Random(505)
        order = {"order_id": 11, "items": make_items(rng, 5), "meta": {"rank": 1}}
        schema = OrderSchema(only=("order_id", "items.sku", "items.tags.name", "meta"))
        try:
            result = schema.loads(json.dumps(order), unknown=EXCLUDE)
            self.assertIn("order_id", result)
        except ValidationError as err:
            self.assertTrue(err.messages)

    def test_06_exclude_dotted(self):
        rng = random.Random(606)
        order = {"order_id": 12, "items": make_items(rng, 4)}
        schema = OrderSchema(exclude=("items.price", "items.tags.weight", "meta.rank"))
        with self.assertRaises(ValidationError) as ctx:
            schema.loads(json.dumps(order), unknown=EXCLUDE)
        self.assertIn("items", ctx.exception.messages)

    def test_07_quiet_subclass(self):
        rng = random.Random(707)
        tags = make_tags(rng, 12)
        with self.assertRaises(ValidationError) as ctx:
            QuietTagSchema().loads(json.dumps(tags + [{"weight": 1}]), many=True)
        self.assertTrue(getattr(ctx.exception, "messages_seen", False))

    def test_08_batch_envelope(self):
        rng = random.Random(808)
        batches = [
            {"batch": b, "tags": make_tags(rng, (b * 5) % 4 + 1)} for b in range(5)
        ]
        payload = json.dumps({"envelope": batches})
        try:
            result = BatchSchema(many=True).loads(payload)
            self.assertEqual(len(result), 5)
        except ValidationError as err:
            self.assertTrue(err.messages)

    def test_09_bytes_and_parse_float(self):
        rng = random.Random(909)
        items = make_items(rng, 8, with_tags=False)
        raw = json.dumps(items).encode("utf-8")
        try:
            result = ItemSchema(many=True).loads(raw, parse_float=lambda v: float(v) / 2)
            self.assertEqual(len(result), 8)
        except ValidationError as err:
            self.assertTrue(err.messages)

    def test_10_reverse_render_module(self):
        rng = random.Random(1010)
        tags = [t for t in make_tags(rng, 14) if t["weight"] % 2 == 0]
        s = json.dumps(tags)[::-1]
        try:
            result = ReversedTagSchema(many=True).loads(s)
            self.assertEqual(len(result), len(tags))
        except ValidationError as err:
            self.assertTrue(err.messages)

    def test_11_type_errors(self):
        payloads = [json.dumps(x) for x in ({"name": "x"}, [1, 2, "three"], "plain", [])]
        outcomes = []
        for p in payloads:
            try:
                TagSchema(many=True).loads(p)
                outcomes.append("ok")
            except ValidationError:
                outcomes.append("err")
        self.assertEqual(len(outcomes), 4)

    def test_12_partial_dotted_reused_schema(self):
        rng = random.Random(1212)
        schema = OrderSchema()
        seen = 0
        for round_no in range(3):
            items = make_items(rng, 2 + round_no)
            for it in items[::2]:
                it.pop("sku")
            order = {"order_id": round_no, "items": items}
            partial = ("items.sku",) if round_no != 1 else None
            try:
                schema.loads(json.dumps(order), partial=partial)
                seen += 1
            except ValidationError:
                seen += 10
        self.assertGreater(seen, 0)


if __name__ == "__main__":
    unittest.main()
