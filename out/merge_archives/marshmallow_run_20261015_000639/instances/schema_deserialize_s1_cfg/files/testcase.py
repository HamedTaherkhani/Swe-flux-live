import random
import unittest

from marshmallow import INCLUDE, RAISE, Schema, fields


class PersonSchema(Schema):
    first = fields.Str(required=True)
    age = fields.Int()
    email = fields.Email(data_key="mail")

    class Meta:
        unknown = RAISE


class RecordSchema(Schema):
    ident = fields.Int(required=True, data_key="id")
    label = fields.Str(attribute="name")
    score = fields.Float()
    tags = fields.List(fields.Str())
    owner = fields.Nested(PersonSchema)
    members = fields.List(fields.Nested(PersonSchema))
    note = fields.Str(load_default="n/a")

    class Meta:
        unknown = INCLUDE


def _person(rng, pid):
    p = {}
    if rng.random() < 0.8:
        p["first"] = "p%d" % pid
    if rng.random() < 0.5:
        p["age"] = rng.choice([pid, str(pid), "x%d" % pid])
    if rng.random() < 0.4:
        p["mail"] = "u%d@ex.org" % pid if pid % 3 else "bad%d" % pid
    if rng.random() < 0.25:
        p["extra%d" % (pid % 4)] = pid
    return p


def build_records(seed, count):
    rng = random.Random(seed)
    records = []
    pid = 0
    for i in range(count):
        rec = {}
        if rng.random() < 0.85:
            rec["id"] = rng.choice([i, str(i * 7), "id-%d" % i])
        if rng.random() < 0.6:
            rec["label"] = "L%d" % (i * 3)
        if rng.random() < 0.5:
            rec["score"] = rng.randint(0, 100) / 4
        if rng.random() < 0.5:
            rec["tags"] = ["t%d" % k for k in range(rng.randint(0, 3))]
        if rng.random() < 0.7:
            pid += 1
            rec["owner"] = _person(rng, pid)
        if rng.random() < 0.6:
            members = []
            for _ in range(rng.randint(1, 3)):
                pid += 1
                members.append(_person(rng, pid))
            rec["members"] = members
        if rng.random() < 0.3:
            rec["note"] = "note%d" % i
        for k in range(rng.randint(0, 2)):
            rec["x_%d_%d" % (i, k)] = i + k
        records.append(rec)
    return records


class RecordValidateTest(unittest.TestCase):
    def test_validate_many_partial(self):
        records = build_records(seed=20241015, count=8)
        partial = ("score", "note", "owner.age", "members.mail", "members.first")
        errors = RecordSchema().validate(records, many=True, partial=partial)
        self.assertIsInstance(errors, dict)
        self.assertTrue(errors)
        self.assertTrue(all(isinstance(k, int) for k in errors))
        self.assertTrue(set(errors) <= set(range(len(records))))


if __name__ == "__main__":
    unittest.main()
