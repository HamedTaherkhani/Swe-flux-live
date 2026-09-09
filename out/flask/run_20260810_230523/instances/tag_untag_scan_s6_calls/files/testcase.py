import random
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from markupsafe import Markup

from flask.json.tag import TaggedJSONSerializer


class UntagScanCallTest(unittest.TestCase):
    def test_seeded_nested_tagged_values(self) -> None:
        rng = random.Random(0x5A17)
        origin = datetime(2031, 4, 7, 9, 13, tzinfo=timezone.utc)
        records = []

        for index in range(27):
            blob = rng.randbytes(3 + index % 8)
            stamp = origin + timedelta(minutes=rng.randrange(60000))
            identifier = UUID(int=rng.getrandbits(128))
            selector = (rng.randrange(37) + index) % 6

            if selector == 0:
                payload = (blob, stamp, identifier)
            elif selector == 1:
                payload = [Markup(f"<i>{index:x}</i>"), identifier, blob]
            elif selector == 2:
                payload = {" b": blob}
            elif selector == 3:
                payload = ({"inner": blob, "stamp": stamp}, Markup(str(index * index)))
            elif selector == 4:
                payload = stamp
            else:
                payload = Markup(f"<em>{identifier.hex[index % 20:index % 20 + 7]}</em>")

            records.append(
                {
                    f"item-{index:x}": payload,
                    "checksum": (sum(blob) ^ identifier.int) % 997,
                    "trail": [index, index % 5, {"raw": blob[::-1]}],
                }
            )

        source = {
            "records": records,
            "summary": (len(records), sum(entry["checksum"] for entry in records)),
        }
        serializer = TaggedJSONSerializer()
        encoded = serializer.tag(source)

        restored = serializer._untag_scan(encoded)

        self.assertEqual(restored, source)
        self.assertIsNot(restored, encoded)
