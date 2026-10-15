"""Deterministic scenarios that drive marshmallow schema serialization through
nested schemas, pre/post serialization hooks, collections and hook failures,
always entering through the public ``Schema.dumps`` entry point."""

import json
import random
import unittest

from marshmallow import Schema, ValidationError, fields, post_dump, pre_dump


class Obj:
    """Simple attribute bag."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TagSchema(Schema):
    """No hooks at all."""

    label = fields.Str()
    weight = fields.Int()


class PointSchema(Schema):
    """Only a pre-serialization hook."""

    x = fields.Int()
    y = fields.Int()

    @pre_dump
    def shift(self, obj, **kwargs):
        if getattr(obj, "x", 0) < 0:
            raise ValidationError("negative x")
        return Obj(x=obj.x + 1, y=obj.y * 2)


class StampSchema(Schema):
    """Only a post-serialization hook (per item)."""

    code = fields.Str()
    level = fields.Int()

    @post_dump
    def upper(self, data, **kwargs):
        data["code"] = data["code"].upper()
        return data


class EnvelopeSchema(Schema):
    """Both kinds of hooks, the post hook operating on the whole collection."""

    ident = fields.Int()
    note = fields.Str()

    @pre_dump(pass_collection=True)
    def prepare(self, data, many, **kwargs):
        return data

    @post_dump(pass_collection=True)
    def wrap(self, data, many, **kwargs):
        if many:
            return {"items": data, "n": len(data)}
        if data.get("note") == "boom":
            raise ValidationError("boom note")
        return data


class OrderSchema(Schema):
    """Container: no hooks of its own; fans out to nested schemas."""

    oid = fields.Int()
    origin = fields.Nested(PointSchema, allow_none=True)
    tags = fields.List(fields.Nested(TagSchema))
    stamps = fields.Nested(StampSchema, many=True)
    env = fields.Nested(EnvelopeSchema, allow_none=True)
    first_tag = fields.Pluck(TagSchema, "label", attribute="lead")


class AuditedOrderSchema(OrderSchema):
    """Container with its own pre and post hooks."""

    @pre_dump
    def ensure_lead(self, obj, **kwargs):
        if not hasattr(obj, "lead"):
            obj.lead = Obj(label="auto", weight=0)
        return obj

    @post_dump
    def count_tags(self, data, **kwargs):
        data["tag_count"] = len(data.get("tags") or [])
        return data


class RouteSchema(Schema):
    """Mapping of nested values plus a list of hooked points."""

    name = fields.Str()
    waypoints = fields.List(fields.Nested(PointSchema))
    legs = fields.Dict(keys=fields.Str(), values=fields.Nested(StampSchema))


def make_tags(rng, n):
    return [
        Obj(label="t%d" % rng.randint(0, 99), weight=rng.randint(1, 9))
        for _ in range(n)
    ]


def make_stamps(rng, n):
    return [
        Obj(code="c%d" % rng.randint(0, 50), level=rng.randint(0, 3))
        for _ in range(n)
    ]


def make_order(rng, oid, *, origin=True, env=True, lead=True, note="ok"):
    kwargs = dict(
        oid=oid,
        origin=Obj(x=rng.randint(0, 20), y=rng.randint(0, 20)) if origin else None,
        tags=make_tags(rng, rng.randint(0, 4)),
        stamps=make_stamps(rng, rng.randint(1, 3)),
        env=Obj(ident=oid * 3, note=note) if env else None,
    )
    if lead:
        kwargs["lead"] = Obj(label="lead%d" % oid, weight=1)
    return Obj(**kwargs)


class DumpFlowTest(unittest.TestCase):
    def test_flat_tags_single(self):
        out = json.loads(TagSchema().dumps(Obj(label="a", weight=3)))
        self.assertEqual(set(out), {"label", "weight"})

    def test_flat_tags_many(self):
        rng = random.Random(7011)
        tags = make_tags(rng, 7)
        out = json.loads(TagSchema(many=True).dumps(tags))
        self.assertEqual(len(out), len(tags))

    def test_points_explicit_many_flag(self):
        rng = random.Random(7012)
        pts = [Obj(x=rng.randint(0, 5), y=i) for i in range(5)]
        out = json.loads(PointSchema().dumps(pts, many=True))
        self.assertEqual([p["y"] for p in out], [2 * i for i in range(5)])

    def test_stamps_many_false_override(self):
        schema = StampSchema(many=True)
        out = json.loads(schema.dumps(Obj(code="zz", level=1), many=False))
        self.assertTrue(out["code"].isupper())

    def test_envelope_collection(self):
        envs = [Obj(ident=i, note="n%d" % (i % 3)) for i in range(4)]
        out = json.loads(EnvelopeSchema(many=True).dumps(envs))
        self.assertEqual(out["n"], len(envs))

    def test_envelope_boom_raises(self):
        with self.assertRaises(ValidationError):
            EnvelopeSchema().dumps(Obj(ident=1, note="boom"))

    def test_single_order(self):
        rng = random.Random(7021)
        order = make_order(rng, 1)
        out = json.loads(OrderSchema().dumps(order))
        self.assertEqual(out["first_tag"], "lead1")

    def test_order_without_optional_parts(self):
        rng = random.Random(7022)
        order = make_order(rng, 2, origin=False, env=False, lead=False)
        out = json.loads(OrderSchema().dumps(order))
        self.assertIsNone(out["origin"])
        self.assertNotIn("first_tag", out)

    def test_audited_orders_many(self):
        rng = random.Random(7023)
        orders = [
            make_order(rng, i, origin=i % 2 == 0, env=i % 3 != 0, lead=i % 2 == 1)
            for i in range(1, 6)
        ]
        out = json.loads(AuditedOrderSchema(many=True).dumps(orders))
        self.assertEqual(len(out), 5)
        self.assertTrue(all("tag_count" in o for o in out))

    def test_audited_order_nested_failure(self):
        rng = random.Random(7024)
        order = make_order(rng, 9, note="boom")
        with self.assertRaises(ValidationError):
            AuditedOrderSchema().dumps(order)

    def test_negative_point_raises(self):
        with self.assertRaises(ValidationError):
            PointSchema(many=True).dumps([Obj(x=1, y=1), Obj(x=-1, y=0)])

    def test_route_with_waypoints_and_legs(self):
        rng = random.Random(7031)
        n = rng.randint(3, 6)
        route = Obj(
            name="r",
            waypoints=[Obj(x=rng.randint(0, 9), y=rng.randint(0, 9)) for _ in range(n)],
            legs={
                "leg%d" % k: Obj(code="k%d" % k, level=k) for k in range(rng.randint(2, 4))
            },
        )
        out = json.loads(RouteSchema().dumps(route))
        self.assertEqual(len(out["waypoints"]), n)
        self.assertTrue(all(v["code"].isupper() for v in out["legs"].values()))

    def test_route_many_mixed(self):
        rng = random.Random(7032)
        routes = []
        for i in range(3):
            routes.append(
                Obj(
                    name="r%d" % i,
                    waypoints=[Obj(x=j, y=i) for j in range(rng.randint(0, 3))],
                    legs={"a%d" % j: Obj(code="q", level=j) for j in range(i)},
                )
            )
        out = json.loads(RouteSchema().dumps(routes, many=True))
        self.assertEqual([r["name"] for r in out], ["r0", "r1", "r2"])
