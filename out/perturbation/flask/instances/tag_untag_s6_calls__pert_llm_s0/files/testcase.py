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
        rng = random.Random(2_593_847)
        serializer = TaggedJSONSerializer()
        serializer.register(NestedDocumentTag, index=0)

        record_ids = list(range(140))
        rng.shuffle(record_ids)
        epoch = datetime(2017, 11, 8, 6, 41, 29, tzinfo=timezone.utc)
        records = []

        for position, record_id in enumerate(record_ids):
            salt = rng.randrange(512, 250_000)
            selector = record_id % 7

            if selector == 0:
                payload = (record_id, salt, position * position, position ^ salt)
            elif selector == 1:
                payload = bytes(
                    (record_id * 29 + salt + offset * 43) % 256
                    for offset in range(5 + position % 14)
                )
            elif selector == 2:
                payload = Markup(
                    f"<strong>{record_id:05x}-{salt:07x}-{position}</strong>"
                )
            elif selector == 3:
                payload = UUID(
                    int=((salt << 56) ^ (record_id << 36) ^ (position << 12)) + 13
                )
            elif selector == 4:
                payload = epoch + timedelta(
                    days=record_id * 17, seconds=salt + position * 5
                )
            elif selector == 5:
                payload = {
                    " t": (
                        salt - record_id,
                        position,
                        record_id + salt,
                        position ^ record_id,
                    )
                }
            else:
                payload = {
                    f"unknown_{record_id % 13}": [
                        (record_id, salt, position % 23),
                        bytes(
                            (salt + step * record_id + position) % 256
                            for step in range(18)
                        ),
                        (salt ^ position, record_id * 5 + salt),
                    ]
                }

            records.append(
                {
                    "ordinal": position,
                    "token": (record_id * 223 + salt) % 262_139,
                    "payload": payload,
                    "audit": [
                        record_id ^ salt,
                        (record_id + 9) * (position + 13),
                        salt % (record_id + 3),
                    ],
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
