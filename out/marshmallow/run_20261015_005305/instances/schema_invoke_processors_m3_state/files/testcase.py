import random
import unittest

from marshmallow import (
    Schema,
    ValidationError,
    fields,
    post_dump,
    post_load,
    pre_dump,
    pre_load,
)


def _make_rows(seed, count):
    rng = random.Random(seed)
    rows = []
    for idx in range(count):
        qty = rng.randint(1, 9)
        price = rng.randint(2, 30)
        rows.append({"sku": f"s{rng.randint(10, 99)}", "qty": qty, "price": price})
        if idx % 2:
            rows[-1]["qty"] += rows[0]["qty"]
    return rows


class OrderLineSchema(Schema):
    sku = fields.Str()
    qty = fields.Int()
    price = fields.Int()

    @pre_dump
    def b_scale(self, obj, many, **kwargs):
        return {**obj, "price": obj["price"] * 2 - obj["qty"]}

    @post_dump
    def a_total(self, data, many, **kwargs):
        data["total"] = data["qty"] * data["price"]
        return data

    @post_dump(pass_collection=True)
    def wrap(self, data, many, **kwargs):
        if many:
            return {"n": len(data), "sum": sum(d["total"] for d in data)}
        return {"one": data["total"] % 7}


class LoaderSchema(Schema):
    code = fields.Str()
    level = fields.Int()

    @pre_load(pass_collection=True)
    def a_unwrap(self, data, many, **kwargs):
        if many:
            return sorted(data["rows"], key=lambda r: (-r["level"], r["code"]))
        return data

    @pre_load
    def b_fix(self, data, many, **kwargs):
        out = dict(data)
        out["code"] = out["code"].upper()[::-1]
        if out["level"] > 5:
            out["level"] = out["level"] - 5
        return out

    @post_load
    def c_rank(self, data, many, **kwargs):
        data["rank"] = len(data["code"]) * data["level"]
        return data

    @post_load(pass_collection=True)
    def d_summary(self, data, many, **kwargs):
        if many:
            return [{**d, "pos": i} for i, d in enumerate(reversed(data))]
        return data


class OriginalSchema(Schema):
    name = fields.Str()
    score = fields.Int()

    @post_dump(pass_original=True)
    def merge(self, data, original, many, **kwargs):
        data["delta"] = original["bonus"] - data["score"]
        return data

    @post_load(pass_original=True, pass_collection=True)
    def collect(self, data, original, many, **kwargs):
        if many:
            return {"names": "".join(d["name"][0] for d in data), "raw": len(original)}
        return (data["name"], original["score"] + 1)


class InPlaceSchema(Schema):
    val = fields.Int()

    @pre_load
    def z_last(self, data, many, **kwargs):
        data["val"] = data["val"] * 3
        return data

    @pre_load
    def m_mid(self, data, many, **kwargs):
        data["val"] = data["val"] + 4
        return data

    @pre_load
    def c_first(self, data, many, **kwargs):
        data["val"] = data["val"] - 1
        return data


class ChildSchema(InPlaceSchema):
    @pre_load
    def m_mid(self, data, many, **kwargs):
        data["val"] = data["val"] * data["val"]
        return data

    @post_load
    def finish(self, data, many, **kwargs):
        return {"val": data["val"] % 11}


class StrictSchema(Schema):
    tag = fields.Str()

    @pre_load
    def check(self, data, many, **kwargs):
        if len(data["tag"]) > 4:
            raise ValidationError("too long", "tag")
        return {"tag": data["tag"] * 2}


class StringifySchema(Schema):
    x = fields.Int()
    y = fields.Int()

    @post_dump
    def flatten(self, data, many, **kwargs):
        return f"{data['x']}:{data['y']}"

    @post_dump(pass_collection=True)
    def join(self, data, many, **kwargs):
        if many:
            return "|".join(data)
        return data


class TestInvokeProcessorsState(unittest.TestCase):
    def test_dump_single_order_line(self):
        row = _make_rows(3, 1)[0]
        out = OrderLineSchema().dump(row)
        self.assertEqual(set(out), {"one"})

    def test_dump_many_order_lines(self):
        rows = _make_rows(11, 4)
        out = OrderLineSchema(many=True).dump(rows)
        self.assertEqual(out["n"], len(rows))

    def test_dump_many_override_flag(self):
        rows = _make_rows(29, 3)
        out = OrderLineSchema().dump(rows, many=True)
        self.assertIsInstance(out["sum"], int)

    def test_load_single(self):
        rng = random.Random(5)
        payload = {"code": "ab" + str(rng.randint(3, 8)), "level": rng.randint(6, 9)}
        out = LoaderSchema().load(payload)
        self.assertIn("rank", out)

    def test_load_many_enveloped(self):
        rng = random.Random(17)
        rows = [
            {"code": chr(97 + rng.randint(0, 5)) * rng.randint(1, 3), "level": rng.randint(1, 8)}
            for _ in range(4)
        ]
        out = LoaderSchema(many=True).load({"rows": rows})
        self.assertEqual(len(out), 4)

    def test_dump_pass_original_many(self):
        objs = [{"name": n, "score": i * 3 + 1, "bonus": (i * 7) % 5} for i, n in enumerate(["ann", "bo", "cy"])]
        out = OriginalSchema(many=True).dump(objs)
        self.assertEqual(len(out), 3)

    def test_load_pass_original_collection(self):
        payload = [{"name": w, "score": len(w) * 2} for w in ("kiwi", "fig", "plum")]
        out = OriginalSchema(many=True).load(payload)
        self.assertEqual(out["raw"], 3)

    def test_load_pass_original_single(self):
        out = OriginalSchema().load({"name": "zed", "score": 2 ** 3})
        self.assertIsInstance(out, tuple)

    def test_inplace_chain(self):
        vals = [random.Random(41).randint(2, 6) for _ in range(1)]
        out = InPlaceSchema().load({"val": vals[0]})
        self.assertGreater(out["val"], 0)

    def test_inherited_override_many(self):
        payload = [{"val": v} for v in range(2, 5)]
        out = ChildSchema(many=True).load(payload)
        self.assertEqual(len(out), 3)

    def test_strict_rejects(self):
        StrictSchema().load({"tag": "ok"})
        with self.assertRaises(ValidationError):
            StrictSchema().load({"tag": "x" * 6})

    def test_stringify_many_and_single(self):
        pts = [{"x": i * i, "y": 10 - i} for i in range(3)]
        joined = StringifySchema(many=True).dump(pts)
        single = StringifySchema().dump(pts[-1])
        self.assertEqual(joined.count("|"), 2)
        self.assertIsInstance(single, str)


if __name__ == "__main__":
    unittest.main()
