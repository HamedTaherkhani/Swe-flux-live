import random
import unittest

from marshmallow import EXCLUDE, Schema, ValidationError, fields, validate, validates_schema


class InnerSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    code = fields.Int(validate=validate.Range(min=0, max=50))
    tag = fields.Str(validate=validate.Length(max=4))


class RecordSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    num = fields.Int(validate=validate.Range(min=0, max=100))
    name = fields.Str(validate=validate.Length(min=3))
    child = fields.Nested(InnerSchema)

    @validates_schema(pass_collection=True, skip_on_field_errors=False)
    def check_collection(self, data, **kwargs):
        flagged = {}
        for idx, item in enumerate(data):
            if idx % 4 == 1:
                flagged[idx] = {"name": "collection-level complaint"}
            elif idx % 5 == 3:
                flagged[idx] = {"child": ["collection child issue"]}
        if flagged:
            raise ValidationError(flagged)

    @validates_schema(skip_on_field_errors=False, pass_original=True)
    def check_item(self, data, original_data, **kwargs):
        mode = original_data["mode"]
        if mode == 0:
            raise ValidationError("item-level list", field_name="name")
        if mode == 1:
            raise ValidationError({"name": "item string", "num": {"deep": ["x"]}})
        if mode == 2:
            raise ValidationError(["child problem"], field_name="child")
        if mode == 3:
            raise ValidationError({"child": {"tag": "bad tag"}, "name": ["again"]})
        if mode == 4:
            raise ValidationError({})
        if mode == 5:
            raise ValidationError("whole record looks wrong")

    @validates_schema(skip_on_field_errors=False, pass_original=True)
    def check_item_again(self, data, original_data, **kwargs):
        if original_data["mode"] in (1, 3, 5):
            raise ValidationError({"name": ["second pass"], "_schema": "also bad"})


def build_records(seed, count):
    rng = random.Random(seed)
    records = []
    for i in range(count):
        num = rng.choice([rng.randint(-20, 130), "nope", rng.randint(0, 100)])
        name = rng.choice(["ab", "abcdef", 7, "xyz" * rng.randint(0, 2)])
        child = rng.choice(
            [
                {"code": rng.randint(-10, 70), "tag": rng.choice(["ok", "toolong"])},
                "not-a-dict",
                {"code": "zz"},
            ]
        )
        records.append(
            {"num": num, "name": name, "child": child, "mode": (i * 7 + rng.randint(0, 3)) % 7}
        )
    return records


class MergeErrorsDataFlowTest(unittest.TestCase):
    def test_load_many_collects_errors(self):
        records = build_records(seed=20240607, count=18)
        with self.assertRaises(ValidationError) as ctx:
            RecordSchema(many=True).load(records)
        messages = ctx.exception.messages
        self.assertIsInstance(messages, dict)
        self.assertTrue(all(isinstance(k, int) for k in messages))
        self.assertGreater(len(messages), 10)
