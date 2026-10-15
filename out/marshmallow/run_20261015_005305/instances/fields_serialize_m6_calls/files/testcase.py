import datetime as dt
import decimal
import enum
import ipaddress
import random
import unittest
import uuid

from marshmallow import Schema, fields
from marshmallow.utils import missing


class Color(enum.Enum):
    RED = "r"
    GREEN = "g"
    BLUE = "b"


class PointSchema(Schema):
    x = fields.Integer()
    y = fields.Float(dump_default=0.5)
    label = fields.String(attribute="meta.label")
    when = fields.DateTime()


class TagSchema(Schema):
    name = fields.String()
    weight = fields.Integer()


class ReportSchema(Schema):
    total = fields.Method("compute_total")
    noop = fields.Method()

    def compute_total(self, obj):
        return sum(v for v in obj["values"] if v % 3)


class TestDirectFieldSerialize(unittest.TestCase):
    def test_01_integers_with_gaps_and_defaults(self):
        rng = random.Random(101)
        plain = fields.Integer()
        defaulted = fields.Integer(dump_default=lambda: -1)
        rows = []
        for i in range(17):
            row = {}
            if rng.random() < 0.6:
                row["n"] = rng.randint(-50, 50)
            if i % 4 == 1:
                row["n"] = None
            rows.append(row)
        out_plain = [plain.serialize("n", r) for r in rows]
        out_def = [defaulted.serialize("n", r) for r in rows]
        self.assertEqual(
            sum(1 for v in out_plain if v is missing),
            sum(1 for r in rows if "n" not in r),
        )
        self.assertFalse(any(v is missing for v in out_def))

    def test_02_dotted_string_attribute(self):
        rng = random.Random(202)
        field = fields.String(attribute="profile.nick")
        objs = []
        for i in range(13):
            if rng.random() < 0.3:
                objs.append({"profile": {}})
            else:
                objs.append({"profile": {"nick": "u" * (i % 5 + 1)}})
        out = [field.serialize("ignored", o) for o in objs]
        self.assertEqual(
            len([v for v in out if isinstance(v, str)]),
            len([o for o in objs if "nick" in o["profile"]]),
        )

    def test_03_list_of_floats(self):
        rng = random.Random(303)
        field = fields.List(fields.Float())
        objs = []
        for _ in range(6):
            k = rng.randint(0, 5)
            objs.append({"vals": None if k == 0 else [rng.random() for _ in range(k)]})
        out = [field.serialize("vals", o) for o in objs]
        self.assertEqual(sum(1 for v in out if v is None), sum(1 for o in objs if o["vals"] is None))

    def test_04_heterogeneous_tuple(self):
        rng = random.Random(404)
        field = fields.Tuple((fields.Integer(), fields.String(), fields.Boolean()))
        objs = [
            {"t": (rng.randint(0, 9), chr(97 + rng.randint(0, 25)), rng.random() < 0.5)}
            for _ in range(rng.randint(4, 8))
        ]
        out = [field.serialize("t", o) for o in objs]
        self.assertTrue(all(isinstance(v, tuple) and len(v) == 3 for v in out))

    def test_05_dict_of_lists(self):
        rng = random.Random(505)
        field = fields.Dict(keys=fields.String(), values=fields.List(fields.Integer()))
        mapping = {}
        for i in range(rng.randint(3, 6)):
            mapping[f"k{i}"] = [rng.randint(0, 99) for _ in range(rng.randint(0, 4))]
        out = field.serialize("m", {"m": mapping})
        bare = fields.Dict()
        out2 = bare.serialize("m", {"m": mapping})
        self.assertEqual(sorted(out), sorted(out2))

    def test_06_nested_many_points(self):
        rng = random.Random(606)
        field = fields.Nested(PointSchema, many=True)
        base = dt.datetime(2020, 1, 1)
        pts = []
        for i in range(rng.randint(3, 5)):
            p = {"x": rng.randint(0, 9), "meta": {"label": f"p{i}"}}
            if rng.random() < 0.5:
                p["y"] = rng.random()
            if i % 2 == 0:
                p["when"] = base + dt.timedelta(days=rng.randint(0, 30))
            pts.append(p)
        out = field.serialize("pts", {"pts": pts})
        self.assertEqual(len(out), len(pts))
        self.assertTrue(all("y" in d for d in out))

    def test_07_pluck_names(self):
        rng = random.Random(707)
        single = fields.Pluck(TagSchema, "name")
        many = fields.Pluck(TagSchema, "weight", many=True)
        tags = [{"name": f"t{rng.randint(0, 99)}", "weight": rng.randint(1, 5)} for _ in range(3)]
        out_single = single.serialize("tag", {"tag": tags[0]})
        out_many = many.serialize("tags", {"tags": tags})
        out_none = single.serialize("tag", {"tag": None})
        self.assertIsInstance(out_single, str)
        self.assertEqual(len(out_many), len(tags))
        self.assertIsNone(out_none)

    def test_08_method_fields(self):
        rng = random.Random(808)
        schema = ReportSchema()
        total = schema.fields["total"]
        noop = schema.fields["noop"]
        objs = [{"values": [rng.randint(0, 20) for _ in range(rng.randint(1, 6))]} for _ in range(4)]
        totals = [total.serialize("total", o) for o in objs]
        noops = [noop.serialize("noop", o) for o in objs[:2]]
        self.assertTrue(all(isinstance(t, int) for t in totals))
        self.assertTrue(all(n is missing for n in noops))

    def test_09_function_and_constant(self):
        rng = random.Random(909)
        func = fields.Function(lambda obj: len(obj["s"]) * 2)
        const = fields.Constant("fixed")
        objs = [{"s": "z" * rng.randint(0, 7)} for _ in range(5)]
        a = [func.serialize("whatever", o) for o in objs]
        b = [const.serialize("whatever", o) for o in objs[: rng.randint(2, 4)]]
        self.assertTrue(all(v % 2 == 0 for v in a))
        self.assertEqual(len(set(b)), 1)

    def test_10_enum_uuid_ip(self):
        rng = random.Random(1010)
        by_name = fields.Enum(Color)
        by_value = fields.Enum(Color, by_value=True)
        uid = fields.UUID()
        ip = fields.IP()
        colors = [rng.choice(list(Color)) for _ in range(7)]
        names = [by_name.serialize("c", {"c": c}) for c in colors]
        values = [by_value.serialize("c", {"c": c}) for c in colors[::2]]
        uids = [uid.serialize("u", {"u": uuid.UUID(int=rng.getrandbits(128))}) for _ in range(2)]
        ips = [ip.serialize("a", {"a": ipaddress.ip_address(rng.getrandbits(32))}) for _ in range(3)]
        self.assertEqual(len(names) + len(values), len(colors) + len(colors[::2]))
        self.assertTrue(all("-" in u for u in uids))
        self.assertTrue(all(i.count(".") == 3 for i in ips))

    def test_11_temporal_with_custom_accessor(self):
        rng = random.Random(1111)
        dtf = fields.DateTime(format="iso")
        datef = fields.Date()
        td = fields.TimeDelta()

        def accessor(obj, key, default):
            return obj.get(key.upper(), default)

        base = dt.datetime(2021, 6, 1, 12)
        objs = []
        for i in range(6):
            o = {}
            if rng.random() < 0.7:
                o["WHEN"] = base + dt.timedelta(hours=rng.randint(0, 100))
            if i % 3 == 0:
                o["SPAN"] = dt.timedelta(seconds=rng.randint(1, 9999))
            objs.append(o)
        whens = [dtf.serialize("when", o, accessor=accessor) for o in objs]
        days = [datef.serialize("when", o, accessor=accessor) for o in objs]
        spans = [td.serialize("span", o, accessor=accessor) for o in objs]
        self.assertEqual(
            sum(1 for w in whens if w is missing), sum(1 for d in days if d is missing)
        )
        self.assertTrue(any(isinstance(s, float) for s in spans))

    def test_12_decimals_urls_raw(self):
        rng = random.Random(1212)
        dec = fields.Decimal(places=2, as_string=True)
        url = fields.Url()
        raw = fields.Raw(dump_default="?")
        objs = []
        for i in range(8):
            o = {"d": decimal.Decimal(rng.randint(0, 10000)) / 100}
            if i % 2:
                o["u"] = f"http://h{i}.example.com/"
            if rng.random() < 0.5:
                o["r"] = [i]
            objs.append(o)
        decs = [dec.serialize("d", o) for o in objs]
        urls = [url.serialize("u", o) for o in objs]
        raws = [raw.serialize("r", o) for o in objs]
        self.assertTrue(all(isinstance(d, str) for d in decs))
        self.assertEqual(len(urls), len(raws))


if __name__ == "__main__":
    unittest.main()
