import random
import string
import unittest
from collections import deque
from decimal import Decimal
from pathlib import PurePosixPath

from fastapi.encoders import jsonable_encoder


class TestJsonableEncoderControlFlow(unittest.TestCase):
    @staticmethod
    def _token(rng: random.Random, width: int) -> str:
        alphabet = string.ascii_lowercase
        return "".join(rng.choice(alphabet) for _ in range(width))

    def test_programmatic_nested_payload_uses_varied_paths(self) -> None:
        rng = random.Random(982_451_653)
        records: dict[str, object] = {}

        for index in range(41):
            internal_prefix = "_sa_" if index % 9 == 4 else "field_"
            key = f"{internal_prefix}{index:x}_{self._token(rng, 7 + index % 5)}"
            selector = (index * index + rng.randrange(19)) % 8
            if selector == 0:
                value: object = None
            elif selector == 1:
                value = sum(rng.randrange(3, 97) for _ in range(5 + index % 4))
            elif selector == 2:
                value = self._token(rng, 9 + index % 8)
            elif selector == 3:
                value = [
                    (rng.randrange(1, 500) * (position + 3)) % 997
                    for position in range(4 + index % 5)
                ]
            elif selector == 4:
                value = {
                    f"nested_{position}_{self._token(rng, 4)}": rng.randrange(10, 800)
                    for position in range(3 + index % 4)
                }
            elif selector == 5:
                value = Decimal(f"{rng.randrange(20, 900)}.{rng.randrange(100, 999)}")
            elif selector == 6:
                value = PurePosixPath(
                    *[self._token(rng, 4 + position) for position in range(2, 5)]
                )
            else:
                value = deque(
                    self._token(rng, 5 + position) for position in range(3 + index % 3)
                )
            records[key] = value

        keys = list(records)
        include = {
            key
            for position, key in enumerate(keys)
            if (position * 7 + len(key)) % 11 not in {1, 6}
        }
        exclude = {
            key
            for position, key in enumerate(keys)
            if (position * 5 + len(key)) % 17 == 3
        }

        leading_value = sum(ord(character) for character in self._token(rng, 13))
        trailing_values = tuple(
            rng.randrange(100, 10_000) for _ in range(12 + leading_value % 7)
        )
        payload = [leading_value, records, trailing_values]

        encoded = jsonable_encoder(
            payload,
            include=include,
            exclude=exclude,
            exclude_none=True,
            sqlalchemy_safe=True,
        )

        self.assertEqual(len(encoded), len(payload))
        self.assertEqual(encoded[0], leading_value)
        self.assertIsInstance(encoded[1], dict)
        self.assertGreater(len(encoded[1]), len(records) // 4)
        self.assertTrue(all(value is not None for value in encoded[1].values()))
        self.assertTrue(all(not str(key).startswith("_sa") for key in encoded[1]))
        self.assertIsInstance(encoded[2], list)
