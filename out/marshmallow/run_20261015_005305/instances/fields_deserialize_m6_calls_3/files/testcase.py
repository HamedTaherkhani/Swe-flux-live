"""Deterministic direct calls of NaiveDateTime._deserialize across many formats."""

import datetime as dt
import random
import unittest

from marshmallow import ValidationError
from marshmallow.fields import NaiveDateTime

BASE = dt.datetime(2001, 3, 4, 5, 6, 7)


def _drive(field, values):
    """Feed every value to the field's _deserialize; return (results, n_errors)."""
    results, errors = [], 0
    for i, value in enumerate(values):
        try:
            results.append(field._deserialize(value, f"a{i}", {"a": value}))
        except ValidationError:
            errors += 1
    return results, errors


def _check(testcase, results, errors, values):
    testcase.assertEqual(len(results) + errors, len(values))
    for r in results:
        testcase.assertIsInstance(r, dt.datetime)
        testcase.assertIsNone(r.tzinfo)


class TestNaiveDateTimeDeserialize(unittest.TestCase):
    def test_iso_mixed_offsets_no_timezone(self):
        rng = random.Random(1072)
        values = []
        for k in range(17):
            moment = BASE + dt.timedelta(hours=rng.randint(0, 5000), seconds=k)
            if rng.random() < 0.4:
                off = dt.timezone(dt.timedelta(hours=rng.randint(-9, 9)))
                moment = moment.replace(tzinfo=off)
            values.append(moment.isoformat())
        field = NaiveDateTime()
        results, errors = _drive(field, values)
        _check(self, results, errors, values)
        self.assertGreater(errors, 0)

    def test_iso_mixed_offsets_with_timezone(self):
        rng = random.Random(1169)
        tz = dt.timezone(dt.timedelta(hours=3))
        values = []
        for k in range(16):
            moment = BASE + dt.timedelta(days=rng.randint(0, 900), minutes=k * 7)
            if k % 3 != 1:
                off = dt.timezone(dt.timedelta(minutes=30 * rng.randint(-20, 20)))
                moment = moment.replace(tzinfo=off)
            text = moment.isoformat()
            if rng.random() < 0.2:
                text = text.replace("T", "?")
            values.append(text)
        field = NaiveDateTime(format="iso", timezone=tz)
        results, errors = _drive(field, values)
        _check(self, results, errors, values)

    def test_timestamp_seconds(self):
        rng = random.Random(1266)
        values = []
        for k in range(18):
            r = rng.random()
            if r < 0.15:
                values.append(-rng.randint(1, 10**6))
            elif r < 0.25:
                values.append(k % 2 == 0)
            elif r < 0.35:
                values.append(f"x{k}")
            else:
                values.append(rng.randint(0, 2 * 10**9) + rng.random())
        field = NaiveDateTime(format="timestamp", timezone=dt.timezone.utc)
        results, errors = _drive(field, values)
        _check(self, results, errors, values)

    def test_timestamp_milliseconds(self):
        rng = random.Random(1363)
        values = []
        for k in range(15):
            r = rng.random()
            if r < 0.2:
                values.append(bool(k % 2))
            elif r < 0.35:
                values.append(str(-rng.randint(1000, 10**9)))
            else:
                values.append(str(rng.randint(0, 2 * 10**12)))
        field = NaiveDateTime(format="timestamp_ms")
        results, errors = _drive(field, values)
        _check(self, results, errors, values)

    def test_custom_strptime_format(self):
        rng = random.Random(1460)
        fmt = "%Y-%m-%d %H:%M"
        values = []
        for k in range(16):
            moment = BASE + dt.timedelta(minutes=rng.randint(0, 10**6))
            text = moment.strftime(fmt)
            if rng.random() < 0.3:
                text = text + ":00"
            values.append(text)
        field = NaiveDateTime(format=fmt)
        results, errors = _drive(field, values)
        _check(self, results, errors, values)

    def test_custom_format_with_offset(self):
        rng = random.Random(1557)
        fmt = "%d/%m/%Y %H:%M:%S %z"
        tz = dt.timezone(dt.timedelta(hours=-4))
        values = []
        for k in range(15):
            off = dt.timezone(dt.timedelta(minutes=15 * rng.randint(-40, 40)))
            moment = (BASE + dt.timedelta(seconds=rng.randint(0, 10**8))).replace(
                tzinfo=off
            )
            values.append(moment.strftime(fmt))
        field = NaiveDateTime(format=fmt, timezone=tz if rng.random() < 0.5 else None)
        results, errors = _drive(field, values)
        _check(self, results, errors, values)

    def test_rfc_format(self):
        rng = random.Random(1654)
        values = []
        for k in range(14):
            moment = BASE + dt.timedelta(hours=rng.randint(0, 9000))
            if k % 4 == 0:
                values.append(moment.strftime("%a, %d %b %Y %H:%M:%S -0000"))
            elif k % 4 == 1:
                values.append(moment.strftime("%a, %d %b %Y %H:%M:%S +0200"))
            elif k % 4 == 2:
                values.append(moment.strftime("%a, %d %b %Y %H:%M:%S GMT"))
            else:
                values.append("not-a-date-%d" % rng.randint(0, 99))
        field = NaiveDateTime(format="rfc")
        results, errors = _drive(field, values)
        _check(self, results, errors, values)

    def test_datetime_objects_passthrough(self):
        rng = random.Random(1751)
        values = []
        for k in range(20):
            moment = BASE + dt.timedelta(seconds=rng.randint(0, 10**7))
            if rng.random() < 0.5:
                moment = moment.replace(
                    tzinfo=dt.timezone(dt.timedelta(hours=rng.randint(-5, 5)))
                )
            values.append(moment)
        field = NaiveDateTime(timezone=dt.timezone(dt.timedelta(hours=1)))
        results, errors = _drive(field, values)
        _check(self, results, errors, values)
        self.assertEqual(errors, 0)

    def test_round_trip_timestamp(self):
        rng = random.Random(1848)
        field = NaiveDateTime(format="timestamp")
        seeds = [rng.randint(10**8, 10**9) for _ in range(12)]
        results, errors = _drive(field, seeds)
        _check(self, results, errors, seeds)
        back = [field._serialize(r, "a", None) for r in results if r.second % 2]
        for b in back:
            self.assertIsInstance(b, float)

    def test_round_trip_ms_chain(self):
        rng = random.Random(1945)
        field = NaiveDateTime(format="timestamp_ms")
        value = rng.randint(10**11, 10**12)
        produced = []
        for _ in range(13):
            got = field._deserialize(value, "a", {})
            produced.append(got)
            ms = field._serialize(got, "a", None)
            value = int(ms) + (rng.randint(1, 10**9) if got.minute % 3 else -(10**13))
            if value < 0:
                with self.assertRaises(ValidationError):
                    field._deserialize(value, "a", {})
                value = -value // 7
        self.assertTrue(all(p.tzinfo is None for p in produced))

    def test_garbage_and_types(self):
        rng = random.Random(2042)
        pool = [None, 3.5, [], {}, b"2020-01-01", "2020-13-01", "2020-02-30T00:00"]
        values = [pool[rng.randrange(len(pool))] for _ in range(14)]
        values.append(dt.date(2020, 1, 1).isoformat())
        field = NaiveDateTime()
        results, errors = _drive(field, values)
        _check(self, results, errors, values)
        self.assertGreater(errors, 0)

    def test_format_switching(self):
        rng = random.Random(2139)
        field = NaiveDateTime(timezone=dt.timezone.utc)
        formats = [None, "iso", "timestamp", "timestamp_ms", "%Y%m%d%H%M%S"]
        total = 0
        for k in range(20):
            field.format = formats[rng.randrange(len(formats))]
            moment = BASE + dt.timedelta(seconds=rng.randint(0, 10**8))
            if field.format in (None, "iso"):
                value = moment.replace(tzinfo=dt.timezone.utc).isoformat()
            elif field.format == "timestamp":
                value = moment.replace(tzinfo=dt.timezone.utc).timestamp()
            elif field.format == "timestamp_ms":
                value = moment.replace(tzinfo=dt.timezone.utc).timestamp() * 1000
            else:
                value = moment.strftime(field.format)
            got = field._deserialize(value, "a", {})
            self.assertIsNone(got.tzinfo)
            total += 1
        self.assertTrue(total)
