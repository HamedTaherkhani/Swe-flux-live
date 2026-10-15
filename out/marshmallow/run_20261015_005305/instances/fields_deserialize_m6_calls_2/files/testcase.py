import datetime as dt
import random
import unittest

from marshmallow import Schema, ValidationError, fields

UTC = dt.timezone.utc
PLUS3 = dt.timezone(dt.timedelta(hours=3))
MINUS5 = dt.timezone(dt.timedelta(hours=-5))


def _base(rng):
    return dt.datetime(2020, 1, 1) + dt.timedelta(
        days=rng.randrange(0, 900), seconds=rng.randrange(0, 86400)
    )


class TestTemporalDeserializeCalls(unittest.TestCase):
    def test_list_of_iso_datetimes(self):
        rng = random.Random(11)

        class S(Schema):
            stamps = fields.List(fields.DateTime())

        values = []
        for i in range(17):
            d = _base(rng)
            if i % 4 == 0:
                d = d.replace(tzinfo=PLUS3)
            values.append(d.isoformat())
        out = S().load({"stamps": values})
        self.assertEqual(len(out["stamps"]), len(values))

    def test_naive_with_conversion_timezone(self):
        rng = random.Random(23)

        class S(Schema):
            when = fields.List(fields.NaiveDateTime(timezone=UTC))

        values = []
        for i in range(13):
            d = _base(rng)
            if rng.random() < 0.5:
                d = d.replace(tzinfo=MINUS5)
            values.append(d.isoformat())
        out = S().load({"when": values})
        self.assertTrue(all(v.tzinfo is None for v in out["when"]))

    def test_naive_without_timezone_rejects_aware(self):
        rng = random.Random(5)

        class S(Schema):
            when = fields.List(fields.NaiveDateTime())

        values = []
        for _ in range(11):
            d = _base(rng)
            if rng.random() < 0.4:
                d = d.replace(tzinfo=PLUS3)
            values.append(d.isoformat())
        try:
            S().load({"when": values})
        except ValidationError as err:
            self.assertIn("when", err.messages)

    def test_aware_with_default_timezone(self):
        rng = random.Random(31)

        class S(Schema):
            seen = fields.List(fields.AwareDateTime(default_timezone=PLUS3))
            first = fields.AwareDateTime(default_timezone=UTC)

        values = []
        for _ in range(9):
            d = _base(rng)
            if rng.random() < 0.3:
                d = d.replace(tzinfo=UTC)
            values.append(d.isoformat())
        out = S().load({"seen": values, "first": values[0]})
        self.assertTrue(all(v.tzinfo is not None for v in out["seen"]))

    def test_aware_rejects_naive_many(self):
        rng = random.Random(47)

        class S(Schema):
            at = fields.AwareDateTime()

        rows = []
        for _ in range(8):
            d = _base(rng)
            if rng.random() < 0.5:
                d = d.replace(tzinfo=MINUS5)
            rows.append({"at": d.isoformat()})
        errors = S(many=True).validate(rows)
        self.assertIsInstance(errors, dict)

    def test_custom_strptime_format(self):
        rng = random.Random(59)
        fmt = "%d/%m/%Y %H:%M"

        class S(Schema):
            moments = fields.List(fields.DateTime(format=fmt))

        values = []
        for i in range(14):
            d = _base(rng)
            if i % 5 == 3:
                values.append(d.isoformat())  # wrong layout -> ValueError
            else:
                values.append(d.strftime(fmt))
        errors = S().validate({"moments": values})
        self.assertIn("moments", errors)

    def test_meta_formats(self):
        rng = random.Random(61)

        class S(Schema):
            class Meta:
                dateformat = "%Y.%m.%d"
                timeformat = "%H-%M-%S"

            day = fields.Date()
            tick = fields.Time()
            days = fields.List(fields.Date())
            ticks = fields.List(fields.Time(format="iso"))

        days = [_base(rng).date() for _ in range(rng.randrange(6, 10))]
        ticks = [_base(rng).time().replace(microsecond=0) for _ in range(5)]
        payload = {
            "day": days[0].strftime("%Y.%m.%d"),
            "tick": ticks[0].strftime("%H-%M-%S"),
            "days": [d.strftime("%Y.%m.%d") for d in days],
            "ticks": [t.isoformat() for t in ticks],
        }
        out = S().load(payload)
        self.assertEqual(out["days"], days)

    def test_timestamps_and_passthrough(self):
        rng = random.Random(73)

        class S(Schema):
            ts = fields.List(fields.DateTime(format="timestamp"))
            ms = fields.List(fields.DateTime(format="timestamp_ms"))

        ts, ms = [], []
        for i in range(12):
            d = _base(rng).replace(tzinfo=UTC)
            if i % 3 == 0:
                ts.append(d)  # already a datetime: returned unchanged
            elif i % 3 == 1:
                ts.append(int(d.timestamp()))
            else:
                ts.append(-rng.randrange(1, 100))  # negative -> invalid
            ms.append(d.timestamp() * 1000 if i % 4 else "x%d" % i)
        errors = S().validate({"ts": ts, "ms": ms})
        self.assertEqual(sorted(errors), ["ms", "ts"])

    def test_tuple_rows(self):
        rng = random.Random(83)

        class S(Schema):
            row = fields.Tuple((fields.Date(), fields.Time(), fields.DateTime("rfc")))

        rows = []
        for i in range(7):
            d = _base(rng).replace(tzinfo=UTC)
            rfc = d.strftime("%a, %d %b %Y %H:%M:%S +0000")
            if i == 4:
                rfc = 12345  # not a string
            rows.append({"row": [d.date().isoformat(), d.time().isoformat(), rfc]})
        errors = S(many=True).validate(rows)
        self.assertEqual(list(errors), [4])

    def test_dict_of_dates(self):
        rng = random.Random(97)

        class S(Schema):
            calendar = fields.Dict(keys=fields.String(), values=fields.Date())

        cal = {}
        for i in range(rng.randrange(15, 20)):
            d = _base(rng).date()
            cal["k%02d" % i] = d if i % 6 == 0 else d.isoformat()
        out = S().load({"calendar": cal})
        self.assertEqual(len(out["calendar"]), len(cal))

    def test_dump_then_reload(self):
        rng = random.Random(101)

        class S(Schema):
            start = fields.DateTime()
            end = fields.Date()
            at = fields.Time()

        objs = []
        for _ in range(6):
            d = _base(rng)
            objs.append({"start": d, "end": d.date(), "at": d.time()})
        schema = S(many=True)
        dumped = schema.dump(objs)
        reloaded = schema.load(dumped)
        self.assertEqual(len(reloaded), len(objs))

    def test_nested_mixed_types(self):
        rng = random.Random(113)

        class Inner(Schema):
            on = fields.Date()
            at = fields.NaiveDateTime(timezone=PLUS3)

        class Outer(Schema):
            items = fields.List(fields.Nested(Inner))

        items = []
        for i in range(10):
            d = _base(rng)
            on = d.date().isoformat() if i % 4 else d.year * 10000
            at = d.replace(tzinfo=UTC).isoformat() if i % 3 == 0 else d.isoformat()
            items.append({"on": on, "at": at})
        errors = Outer().validate({"items": items})
        self.assertIn("items", errors)


if __name__ == "__main__":
    unittest.main()
