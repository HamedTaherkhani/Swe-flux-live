import datetime as dt
import enum
import random
import unittest
import uuid

from marshmallow import EXCLUDE, Schema, ValidationError, fields, validate


class Color(enum.Enum):
    RED = 1
    GREEN = 2
    BLUE = 3
    AMBER = 4


class Size(enum.Enum):
    S = "small"
    M = "medium"
    L = "large"


class PointSchema(Schema):
    x = fields.Integer()
    y = fields.Float()


class TagSchema(Schema):
    label = fields.String()
    weight = fields.Integer(load_default=1)


class ItemSchema(Schema):
    sku = fields.String(required=True)
    qty = fields.Integer()
    tags = fields.List(fields.Nested(TagSchema))
    color = fields.Enum(Color)


def _rng(seed):
    return random.Random(seed)


def _strip_blank(value):
    if isinstance(value, str) and not value.strip():
        return None
    return value


class TestIndirectDeserialize(unittest.TestCase):
    def test_01_list_of_mixed_ints(self):
        class S(Schema):
            values = fields.List(fields.Integer())

        rng = _rng(11)
        data = []
        for i in range(23):
            r = rng.random()
            if r < 0.2:
                data.append(str(rng.randint(-50, 50)))
            elif r < 0.3:
                data.append("n%d" % i)
            else:
                data.append(rng.randint(0, 999))
        with self.assertRaises(ValidationError) as ctx:
            S().load({"values": data})
        bad = ctx.exception.messages["values"]
        self.assertTrue(all(isinstance(k, int) for k in bad))
        self.assertGreater(len(bad), 0)

    def test_02_nested_list_of_lists(self):
        class S(Schema):
            grid = fields.List(fields.List(fields.Float(allow_none=True)))

        rng = _rng(22)
        grid = []
        for r in range(rng.randint(4, 6)):
            row = []
            for c in range(rng.randint(2, 5)):
                row.append(None if (r * c) % 4 == 3 else round(rng.uniform(-5, 5), 2))
            grid.append(row)
        out = S().load({"grid": grid})
        self.assertEqual(len(out["grid"]), len(grid))

    def test_03_tuple_of_typed_values(self):
        class S(Schema):
            records = fields.List(
                fields.Tuple(
                    (fields.String(), fields.Integer(), fields.Boolean(), fields.Date())
                )
            )

        rng = _rng(33)
        base = dt.date(2020, 1, 1)
        records = []
        for i in range(rng.randint(5, 8)):
            day = base + dt.timedelta(days=rng.randint(0, 400))
            flag = rng.choice(["yes", "no", 1, 0, "maybe"])
            records.append(("rec%02d" % i, i * 7, flag, day.isoformat()))
        try:
            out = S().load({"records": records})
            self.assertTrue(out["records"])
        except ValidationError as err:
            self.assertIn("records", err.messages)

    def test_04_dict_with_key_and_value_fields(self):
        class S(Schema):
            scores = fields.Dict(
                keys=fields.String(validate=validate.Length(min=3)),
                values=fields.List(fields.Integer()),
            )

        rng = _rng(44)
        scores = {}
        for i in range(rng.randint(5, 7)):
            key = "k" * (1 + i % 4) + str(i)
            scores[key] = [rng.randint(0, 9) for _ in range(rng.randint(0, 3))]
        try:
            S().load({"scores": scores})
        except ValidationError as err:
            self.assertIn("scores", err.messages)

    def test_05_nested_many_items(self):
        class S(Schema):
            items = fields.Nested(ItemSchema, many=True)

        rng = _rng(55)
        items = []
        for i in range(rng.randint(3, 5)):
            tags = [
                {"label": "t%d" % j} if j % 2 else {"label": "t%d" % j, "weight": j}
                for j in range(rng.randint(0, 3))
            ]
            items.append(
                {
                    "sku": "SKU-%d" % (100 + i),
                    "qty": rng.randint(1, 20),
                    "tags": tags,
                    "color": rng.choice(["RED", "GREEN", "BLUE", "AMBER"]),
                }
            )
        out = S().load({"items": items})
        self.assertEqual(len(out["items"]), len(items))

    def test_06_enum_by_name_and_value(self):
        class S(Schema):
            by_name = fields.List(fields.Enum(Color))
            by_raw = fields.List(fields.Enum(Size, by_value=True))
            by_field = fields.List(fields.Enum(Color, by_value=fields.Integer))

        rng = _rng(66)
        names = [rng.choice(["RED", "GREEN", "BLUE", "PINK"]) for _ in range(6)]
        raws = [rng.choice(["small", "medium", "large", Size.M]) for _ in range(5)]
        ints = [rng.choice([1, 2, 3, 4, "2"]) for _ in range(5)]
        try:
            S().load({"by_name": names, "by_raw": raws, "by_field": ints})
        except ValidationError as err:
            self.assertTrue(set(err.messages) <= {"by_name", "by_raw", "by_field"})

    def test_07_datetimes_naive_and_aware(self):
        utc = dt.timezone.utc
        plus2 = dt.timezone(dt.timedelta(hours=2))

        class S(Schema):
            naive = fields.List(fields.NaiveDateTime(timezone=utc))
            aware = fields.List(fields.AwareDateTime(default_timezone=plus2))
            strict = fields.List(fields.NaiveDateTime())

        rng = _rng(77)
        base = dt.datetime(2021, 6, 1, 12, 0, 0)
        naive, aware, strict = [], [], []
        for i in range(6):
            moment = base + dt.timedelta(hours=rng.randint(0, 500))
            tz = plus2 if i % 2 else None
            naive.append(moment.replace(tzinfo=tz).isoformat())
            aware.append(moment.replace(tzinfo=None if i % 3 else utc).isoformat())
        for i in range(4):
            strict.append((base + dt.timedelta(days=i)).replace(tzinfo=utc if i == 2 else None).isoformat())
        with self.assertRaises(ValidationError) as ctx:
            S().load({"naive": naive, "aware": aware, "strict": strict})
        self.assertEqual(set(ctx.exception.messages), {"strict"})

    def test_08_pre_load_blank_to_none(self):
        class S(Schema):
            notes = fields.List(
                fields.String(pre_load=_strip_blank, allow_none=True,
                              post_load=str.upper)
            )
            plain = fields.List(fields.String(pre_load=[_strip_blank, _strip_blank]))

        rng = _rng(88)
        notes = [rng.choice(["a", " ", "bc", "", "def"]) for _ in range(9)]
        plain = [rng.choice(["x", "  ", "yz"]) for _ in range(5)]
        try:
            S().load({"notes": notes, "plain": plain})
        except ValidationError as err:
            self.assertIn("plain", err.messages)

    def test_09_pluck_and_missing_defaults(self):
        class S(Schema):
            authors = fields.Pluck(TagSchema, "label", many=True)
            main = fields.Pluck(PointSchema, "x")
            extra = fields.Integer(load_default=lambda: 5)
            opt = fields.String()

        rng = _rng(99)
        authors = ["auth%d" % rng.randint(0, 99) for _ in range(rng.randint(3, 6))]
        out = S().load({"authors": authors, "main": rng.randint(1, 9)})
        self.assertEqual(len(out["authors"]), len(authors))
        self.assertNotIn("opt", out)

    def test_10_uuid_decimal_ip_raw(self):
        class S(Schema):
            ids = fields.List(fields.UUID())
            prices = fields.List(fields.Decimal(places=2))
            hosts = fields.List(fields.IP())
            blob = fields.Raw()

        rng = _rng(1010)
        ids = [str(uuid.UUID(int=rng.getrandbits(128))) for _ in range(4)]
        ids.append("not-a-uuid")
        prices = [str(rng.randint(0, 9999) / 100) for _ in range(5)]
        hosts = ["10.0.%d.%d" % (rng.randint(0, 9), rng.randint(0, 255)) for _ in range(3)]
        hosts.append("::1")
        with self.assertRaises(ValidationError) as ctx:
            S().load({"ids": ids, "prices": prices, "hosts": hosts, "blob": {"a": 1}})
        self.assertIn("ids", ctx.exception.messages)

    def test_11_partial_and_unknown(self):
        class S(Schema):
            class Meta:
                unknown = EXCLUDE

            point = fields.Nested(PointSchema)
            points = fields.List(fields.Nested(PointSchema))
            label = fields.String(required=True)
            when = fields.Time()

        rng = _rng(1111)
        pts = [{"x": rng.randint(0, 9), "y": rng.random()} for _ in range(4)]
        out = S().load(
            {"point": {"x": 3}, "points": pts, "junk": 1, "when": "10:20:30"},
            partial=("label", "point.y"),
        )
        self.assertEqual(len(out["points"]), len(pts))

    def test_12_mapping_without_value_field(self):
        class S(Schema):
            bag = fields.Dict()
            keyed = fields.Dict(keys=fields.String())
            nums = fields.Dict(values=fields.Float(validate=validate.Range(0, 0.5)))
            tags = fields.Tuple((fields.Email(), fields.Url()))

        rng = _rng(1212)
        bag = {"b%d" % i: rng.randint(0, 5) for i in range(4)}
        keyed = {"q%d" % i: i for i in range(rng.randint(3, 5))}
        nums = {"n%d" % i: str(rng.random()) for i in range(3)}
        try:
            out = S().load(
                {"bag": bag, "keyed": keyed, "nums": nums,
                 "tags": ["dev@example.com", "https://example.com/x"]}
            )
            self.assertEqual(set(out), {"bag", "keyed", "nums", "tags"})
        except ValidationError as err:
            self.assertEqual(set(err.messages), {"nums"})
