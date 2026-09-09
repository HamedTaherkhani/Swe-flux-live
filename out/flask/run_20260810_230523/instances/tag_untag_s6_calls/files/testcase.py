import json
import random
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from markupsafe import Markup

from flask.json.tag import JSONTag, TaggedJSONSerializer


class NestedDocumentTag(JSONTag):
    __slots__ = ()
    key = " qa"

    def check(self, value):
        return False

    def to_json(self, value):
        return value

    def to_python(self, value):
        return self.serializer.loads(value)


class TestTaggedJSONIndirectCalls(unittest.TestCase):
    def test_nested_generated_document_round_trip(self) -> None:
        rng = random.Random(904_271)
        serializer = TaggedJSONSerializer()
        serializer.register(NestedDocumentTag, index=0)

        record_ids = list(range(28))
        rng.shuffle(record_ids)
        epoch = datetime(2021, 3, 14, 9, 26, 53, tzinfo=timezone.utc)
        records = []

        for position, record_id in enumerate(record_ids):
            salt = rng.randrange(1_000, 90_000)
            selector = record_id % 7

            if selector == 0:
                payload = (record_id, salt, position * position)
            elif selector == 1:
                payload = bytes(
                    (record_id * 17 + salt + offset * 29) % 256
                    for offset in range(5 + position % 6)
                )
            elif selector == 2:
                payload = Markup(f"<em>{record_id:x}-{salt:x}</em>")
            elif selector == 3:
                payload = UUID(int=((salt << 72) ^ (record_id << 32) ^ position) + 1)
            elif selector == 4:
                payload = epoch + timedelta(
                    days=record_id * 11, seconds=salt + position
                )
            elif selector == 5:
                payload = {" t": (salt - record_id, position, record_id + salt)}
            else:
                payload = {
                    f"unknown_{record_id % 5}": [
                        (record_id, salt),
                        bytes((salt + step * record_id) % 256 for step in range(7)),
                    ]
                }

            records.append(
                {
                    "ordinal": position,
                    "token": (record_id * 131 + salt) % 65_521,
                    "payload": payload,
                    "audit": [record_id ^ salt, (record_id + 3) * (position + 5)],
                }
            )

        nested_document = serializer.dumps(records)
        envelope = json.dumps({NestedDocumentTag.key: nested_document})
        restored = serializer.loads(envelope)

        self.assertEqual(restored, records)
        self.assertEqual(
            sum(isinstance(item["payload"], tuple) for item in restored),
            sum(record_id % 7 == 0 for record_id in record_ids),
        )
        self.assertTrue(
            all(item["ordinal"] == position for position, item in enumerate(restored))
        )
