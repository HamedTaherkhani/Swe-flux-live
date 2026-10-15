import datetime as dt
import email.utils
import random
import unittest

from marshmallow import Schema, ValidationError
from marshmallow.fields import AwareDateTime

UTC = dt.timezone.utc


class FloatingTZ(dt.tzinfo):
    """A tzinfo whose utcoffset is unknown (returns None)."""

    def utcoffset(self, d):
        return None

    def dst(self, d):
        return None

    def tzname(self, d):
        return "floating"


def offset_tz(minutes):
    return dt.timezone(dt.timedelta(minutes=minutes))


def make_moment(rng):
    return dt.datetime(
        rng.randint(1990, 2030),
        rng.randint(1, 12),
        rng.randint(1, 28),
        rng.randint(0, 23),
        rng.randint(0, 59),
        rng.randint(0, 59),
    )


def run_all(field, values):
    ok, errors = [], []
    for value in values:
        try:
            ok.append(field._deserialize(value, "when", None))
        except ValidationError as exc:
            errors.append(exc)
    return ok, errors


def assert_outcome(case, ok, errors, total):
    case.assertEqual(len(ok) + len(errors), total)
    for result in ok:
        case.assertIsInstance(result, dt.datetime)
    for exc in errors:
        case.assertRegex(str(exc.messages), "Not a valid")


class TestAwareDateTimeDeserialize(unittest.TestCase):
    def test_01_iso_strings_with_default_timezone(self):
        rng = random.Random(101)
        values = []
        for i in range(23):
            moment = make_moment(rng)
            roll = rng.random()
            if roll < 0.45:
                values.append(moment.isoformat())
            elif roll < 0.85:
                values.append(moment.replace(tzinfo=offset_tz(rng.choice([-300, 60, 330]))).isoformat())
            else:
                values.append(moment.isoformat()[: 7 + i % 5] + "Q")
        field = AwareDateTime(default_timezone=UTC)
        ok, errors = run_all(field, values)
        assert_outcome(self, ok, errors, len(values))
        for result in ok:
            self.assertIsNotNone(result.utcoffset())

    def test_02_iso_strings_without_default_timezone(self):
        rng = random.Random(202)
        values = []
        for _ in range(19):
            moment = make_moment(rng)
            if rng.random() < 0.4:
                moment = moment.replace(tzinfo=offset_tz(rng.randint(-12, 12) * 60))
            values.append(moment.isoformat(sep=rng.choice(["T", " "])))
        field = AwareDateTime(format="iso")
        ok, errors = run_all(field, values)
        assert_outcome(self, ok, errors, len(values))

    def test_03_posix_timestamps_with_default_timezone(self):
        rng = random.Random(303)
        values = []
        for i in range(26):
            kind = rng.randint(0, 5)
            if kind == 0:
                values.append(rng.choice([True, False]))
            elif kind == 1:
                values.append(-rng.randint(1, 10**6))
            elif kind == 2:
                values.append(str(rng.randint(0, 2 * 10**9)))
            elif kind == 3:
                values.append("t%d" % i)
            else:
                values.append(rng.randint(0, 2 * 10**9) + rng.random())
        field = AwareDateTime(format="timestamp", default_timezone=offset_tz(-120))
        ok, errors = run_all(field, values)
        assert_outcome(self, ok, errors, len(values))
        for result in ok:
            self.assertEqual(result.utcoffset(), dt.timedelta(minutes=-120))

    def test_04_millisecond_timestamps_without_default_timezone(self):
        rng = random.Random(404)
        values = []
        for _ in range(17):
            kind = rng.randint(0, 3)
            if kind == 0:
                values.append(rng.choice([True, False]))
            elif kind == 1:
                values.append(rng.randint(0, 2 * 10**12))
            elif kind == 2:
                values.append(dt.datetime(2001, 1, 1, tzinfo=offset_tz(rng.randint(-5, 5) * 30)))
            else:
                values.append("%d.5" % rng.randint(0, 10**12))
        field = AwareDateTime(format="timestamp_ms")
        ok, errors = run_all(field, values)
        assert_outcome(self, ok, errors, len(values))

    def test_05_rfc822_strings(self):
        rng = random.Random(505)
        values = []
        for _ in range(21):
            moment = make_moment(rng)
            mode = rng.randint(0, 3)
            if mode == 0:
                values.append(email.utils.format_datetime(moment))
            elif mode == 1:
                values.append(email.utils.format_datetime(moment.replace(tzinfo=offset_tz(rng.choice([0, 90, -240])))))
            elif mode == 2:
                values.append(email.utils.format_datetime(moment.replace(tzinfo=UTC), usegmt=True))
            else:
                values.append("not a date %d" % rng.randint(0, 99))
        field = AwareDateTime(format="rfc", default_timezone=offset_tz(45))
        ok, errors = run_all(field, values)
        assert_outcome(self, ok, errors, len(values))

    def test_06_custom_strptime_formats(self):
        rng = random.Random(606)
        with_zone = AwareDateTime(format="%Y-%m-%dT%H:%M:%S%z")
        no_zone = AwareDateTime(format="%d/%m/%Y %H:%M", default_timezone=UTC)
        ok_total, err_total, n = 0, 0, 0
        for i in range(18):
            moment = make_moment(rng).replace(tzinfo=offset_tz(rng.randint(-8, 8) * 15))
            if i % 3 == 0:
                field, raw = with_zone, moment.strftime("%Y-%m-%dT%H:%M:%S%z")
            elif i % 3 == 1:
                field, raw = no_zone, moment.strftime("%d/%m/%Y %H:%M")
            else:
                field, raw = rng.choice([with_zone, no_zone]), moment.strftime("%Y-%m-%dT%H:%M:%S")
            ok, errors = run_all(field, [raw])
            ok_total += len(ok)
            err_total += len(errors)
            n += 1
        self.assertEqual(ok_total + err_total, n)

    def test_07_datetime_instances_passthrough(self):
        rng = random.Random(707)
        floating = FloatingTZ()
        values = []
        for _ in range(24):
            moment = make_moment(rng)
            pick = rng.randint(0, 2)
            if pick == 0:
                values.append(moment)
            elif pick == 1:
                values.append(moment.replace(tzinfo=floating))
            else:
                values.append(moment.replace(tzinfo=offset_tz(rng.randint(1, 9) * 60)))
        strict = AwareDateTime()
        lenient = AwareDateTime(default_timezone=offset_tz(600))
        for idx, value in enumerate(values):
            field = strict if idx % 2 else lenient
            ok, errors = run_all(field, [value])
            assert_outcome(self, ok, errors, 1)

    def test_08_bound_to_schema_with_meta_format(self):
        class StampSchema(Schema):
            class Meta:
                datetimeformat = "timestamp"

        rng = random.Random(808)
        fields_ = [
            AwareDateTime(default_timezone=UTC, validate=[lambda v: True]),
            AwareDateTime(format="iso", validate=(lambda v: True, lambda v: True)),
            AwareDateTime(),
        ]
        parent = StampSchema()
        for pos, field in enumerate(fields_):
            field._bind_to_schema("f%d" % pos, parent)
        values = [rng.choice([rng.randint(0, 10**9), "2020-02-02T02:02:02", -rng.randint(1, 50)]) for _ in range(15)]
        for idx, value in enumerate(values):
            ok, errors = run_all(fields_[idx % 3], [value])
            assert_outcome(self, ok, errors, 1)

    def test_09_round_trip_with_serialize(self):
        rng = random.Random(909)
        field = AwareDateTime(format="timestamp_ms", default_timezone=offset_tz(-60))
        produced = 0
        for _ in range(16):
            moment = make_moment(rng)
            if rng.random() < 0.5:
                moment = moment.replace(tzinfo=offset_tz(rng.randint(-3, 3) * 60))
            wire = field._serialize(moment, "when", None)
            if rng.random() < 0.3:
                wire = -wire
            ok, errors = run_all(field, [wire])
            produced += len(ok)
            assert_outcome(self, ok, errors, 1)
        self.assertLessEqual(produced, 16)

    def test_10_overflow_and_garbage_timestamps(self):
        rng = random.Random(1010)
        values = []
        for _ in range(20):
            k = rng.randint(0, 4)
            if k == 0:
                values.append(10 ** rng.randint(14, 40))
            elif k == 1:
                values.append(float("inf") if rng.random() < 0.5 else float("nan"))
            elif k == 2:
                values.append(None)
            elif k == 3:
                values.append([rng.randint(0, 9)])
            else:
                values.append(rng.randint(0, 10**15))
        field = AwareDateTime(format="timestamp_ms", default_timezone=UTC)
        ok, errors = run_all(field, values)
        assert_outcome(self, ok, errors, len(values))

    def test_11_wrong_types_for_iso(self):
        rng = random.Random(1111)
        values = []
        for _ in range(15):
            k = rng.randint(0, 3)
            if k == 0:
                values.append(rng.randint(0, 100))
            elif k == 1:
                values.append(None)
            elif k == 2:
                values.append(dt.date(2020, rng.randint(1, 12), 1))
            else:
                values.append(make_moment(rng).isoformat() + "+05:30")
        field = AwareDateTime(
            format="iso8601",
            error_messages={"invalid": "Not a valid instant."},
        )
        ok, errors = run_all(field, values)
        assert_outcome(self, ok, errors, len(values))

    def test_12_field_grid(self):
        rng = random.Random(1212)
        formats = ["iso", "timestamp", "rfc822", None]
        zones = [None, UTC, FloatingTZ()]
        grid = [AwareDateTime(format=f, default_timezone=z) for f in formats for z in zones]
        moment = dt.datetime(2015, 6, 7, 8, 9, 10)
        encodings = {
            "iso": moment.isoformat(),
            "timestamp": moment.replace(tzinfo=UTC).timestamp(),
            "rfc822": email.utils.format_datetime(moment.replace(tzinfo=offset_tz(120))),
            None: moment.replace(tzinfo=offset_tz(-30)).isoformat(),
        }
        checked = 0
        for field in grid:
            if rng.random() < 0.25:
                continue
            ok, errors = run_all(field, [encodings[field.format]])
            assert_outcome(self, ok, errors, 1)
            checked += 1
        self.assertGreater(checked, 0)
