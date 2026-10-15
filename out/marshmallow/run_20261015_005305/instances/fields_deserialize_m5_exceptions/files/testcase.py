import enum
import random
import unittest

from marshmallow import Schema, fields


class Color(enum.Enum):
    RED = "r"
    GREEN = "g"
    BLUE = "b"
    AMBER = "a"


class Level(enum.Enum):
    LOW = 1
    MID = 3
    HIGH = 5
    MAX = 8


class Mood(enum.Enum):
    CALM = 10
    TENSE = 20
    WILD = 30

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            for member in cls:
                if member.name.lower() == value.strip().lower():
                    return member
            return None
        if isinstance(value, float):
            scaled = {float(m.value) / 10: m for m in cls}
            return scaled[value]
        if isinstance(value, int) and value > 100:
            return value // 10
        return None


def _name_tokens(seed, count):
    rng = random.Random(seed)
    names = [m.name for m in Color]
    out = []
    for _ in range(count):
        roll = rng.random()
        name = rng.choice(names)
        if roll < 0.45:
            out.append(name)
        elif roll < 0.7:
            out.append(name.lower())
        elif roll < 0.85:
            out.append(rng.randint(0, 9))
        else:
            out.append(name[: rng.randint(1, len(name))])
    return out


def _level_values(seed, count):
    rng = random.Random(seed)
    return [rng.randint(0, 9) for _ in range(count)]


def _count_list_errors(errors, key):
    return len(errors.get(key, {}))


class TestEnumDeserializeExceptions(unittest.TestCase):
    def test_name_list_mixed(self):
        class S(Schema):
            colors = fields.List(fields.Enum(Color))

        tokens = _name_tokens(11, 24)
        errors = S().validate({"colors": tokens})
        good = sum(1 for t in tokens if isinstance(t, str) and t in Color.__members__)
        self.assertEqual(_count_list_errors(errors, "colors"), len(tokens) - good)

    def test_value_list_raw(self):
        class S(Schema):
            levels = fields.List(fields.Enum(Level, by_value=True))

        values = _level_values(5, 20)
        errors = S().validate({"levels": values})
        valid = {m.value for m in Level}
        bad = sum(1 for v in values if v not in valid)
        self.assertEqual(_count_list_errors(errors, "levels"), bad)

    def test_value_integer_field(self):
        class S(Schema):
            levels = fields.List(fields.Enum(Level, by_value=fields.Integer()))

        rng = random.Random(23)
        raw = []
        for i in range(18):
            n = rng.randint(0, 9)
            raw.append(str(n) if i % 3 == 0 else (f"x{n}" if i % 4 == 1 else n))
        errors = S().validate({"levels": raw})
        self.assertGreater(_count_list_errors(errors, "levels"), 0)
        self.assertLess(_count_list_errors(errors, "levels"), len(raw))

    def test_dict_enum_keys_and_values(self):
        class S(Schema):
            table = fields.Dict(
                keys=fields.Enum(Color), values=fields.Enum(Level, by_value=True)
            )

        keys = _name_tokens(31, 12)
        vals = _level_values(32, 12)
        table = {}
        for k, v in zip(keys, vals):
            table[k] = v
        errors = S().validate({"table": table})
        self.assertIn("table", errors)

    def test_tuple_triplets(self):
        class S(Schema):
            rows = fields.List(
                fields.Tuple(
                    (
                        fields.Enum(Color),
                        fields.Enum(Level, by_value=True),
                        fields.Enum(Mood, by_value=True),
                    )
                )
            )

        rng = random.Random(41)
        rows = []
        for i in range(8):
            rows.append(
                (
                    rng.choice(["RED", "BLUE", "blue", "TEAL"]),
                    rng.choice([1, 2, 5, 7]),
                    rng.choice(["calm", " Wild ", "sad", 20, 40]),
                )
            )
        errors = S().validate({"rows": rows})
        self.assertGreaterEqual(_count_list_errors(errors, "rows"), 1)

    def test_nested_many(self):
        class Inner(Schema):
            color = fields.Enum(Color)
            level = fields.Enum(Level, by_value=True, allow_none=True)

        class S(Schema):
            items = fields.Nested(Inner, many=True)

        rng = random.Random(55)
        items = []
        for i in range(14):
            item = {"color": rng.choice(["GREEN", "AMBER", "Amber", 3])}
            if i % 3:
                item["level"] = rng.choice([None, 3, 4, 8])
            items.append(item)
        errors = S().validate({"items": items})
        self.assertIn("items", errors)

    def test_members_passthrough_clean(self):
        class S(Schema):
            colors = fields.List(fields.Enum(Color))
            levels = fields.List(fields.Enum(Level, by_value=True))

        colors = [list(Color)[i % 4] if i % 2 else list(Color)[i % 4].name for i in range(10)]
        levels = [list(Level)[i % 4] if i % 3 else list(Level)[i % 4].value for i in range(10)]
        loaded = S().load({"colors": colors, "levels": levels})
        self.assertEqual(len(loaded["colors"]), 10)
        self.assertEqual(len(loaded["levels"]), 10)

    def test_missing_hook_recovers(self):
        class S(Schema):
            moods = fields.List(fields.Enum(Mood, by_value=True))

        words = ["calm", "TENSE", " wild", "Calm ", 10, 30, "tense"]
        loaded = S().load({"moods": words * 2})
        self.assertEqual(len(loaded["moods"]), 14)

    def test_missing_hook_bad_return(self):
        class S(Schema):
            moods = fields.List(fields.Enum(Mood, by_value=True))

        seq = ["calm", 15, "grumpy", 20, "WILD", 99, 250, "calm", 5]
        with self.assertRaises(Exception):
            S().load({"moods": seq})

    def test_missing_hook_float(self):
        class S(Schema):
            first = fields.Enum(Mood, by_value=True)
            second = fields.Enum(Mood, by_value=True)

        with self.assertRaises(Exception):
            S().load({"first": 3.0, "second": 2.5})

    def test_bytes_names(self):
        class S(Schema):
            colors = fields.List(fields.Enum(Color))

        raw = [b"RED", b"green", b"\xff\xfe", b"BLUE", "AMBER", b"\xc3", b"Blue"]
        errors = S().validate({"colors": raw})
        self.assertEqual(_count_list_errors(errors, "colors"), 4)

    def test_many_rows_partial(self):
        class S(Schema):
            color = fields.Enum(Color, required=True)
            level = fields.Enum(Level, by_value=True)
            mood = fields.Enum(Mood, by_value=fields.Integer(), allow_none=True)

        rng = random.Random(77)
        rows = []
        for i in range(10):
            row = {"color": rng.choice(["RED", "GREEN", "Green", 0])}
            if i % 2 == 0:
                row["level"] = rng.choice([1, 3, 6])
            row["mood"] = rng.choice([None, "20", "thirty", 30, 31])
            rows.append(row)
        errors = S(many=True).validate(rows)
        self.assertLessEqual(len(errors), len(rows))


if __name__ == "__main__":
    unittest.main()
