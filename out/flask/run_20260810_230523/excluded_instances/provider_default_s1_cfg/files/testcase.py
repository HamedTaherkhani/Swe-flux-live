import dataclasses
import datetime
import decimal
import random
import unittest
import uuid

from flask.json.provider import _default


@dataclasses.dataclass
class Payload:
    label: str
    weight: int


class RecursiveHTML:
    def __init__(self, child):
        self.child = child

    def __html__(self):
        return _default(self.child)


class MarkupLike:
    def __init__(self, value):
        self.value = value

    def __html__(self):
        return self.value[::-1]


class Unsupported:
    pass


def make_supported(index):
    selector = (index * index + index * 3 + 1) % 4
    if selector == 0:
        return datetime.date(1990 + index, index % 12 + 1, index % 25 + 1)
    if selector == 1:
        return decimal.Decimal(index * index) / decimal.Decimal(index + 1)
    if selector == 2:
        return uuid.UUID(int=(index + 1) ** 5)
    return Payload(f"p-{index * index}", index**3 - index)


class TestProviderDefault(unittest.TestCase):
    def test_dynamic_extent_path(self):
        rng = random.Random(8675309)
        pre_values = [make_supported(i) for i in range(8)]
        pre_results = [_default(value) for value in pre_values]

        tokens = [rng.getrandbits(9) for _ in range(28)]
        depth = 18 + sum(((token ^ (token >> 3)) & 1) for token in tokens)
        node = Payload(
            "-".join(str(token % 23) for token in tokens),
            sum((position + 1) * token for position, token in enumerate(tokens)),
        )
        for _ in range(depth):
            node = RecursiveHTML(node)

        nested_result = _default(node)

        post_values = [
            Unsupported() if i % 6 == 0 else MarkupLike(str((i + 3) ** 4))
            for i in range(30)
        ]
        successful_post = []
        failures = 0
        for value in post_values:
            try:
                successful_post.append(_default(value))
            except TypeError:
                failures += 1

        self.assertTrue(all(result is not None for result in pre_results))
        self.assertIsInstance(nested_result, str)
        self.assertGreater(len(nested_result), len(tokens))
        self.assertEqual(failures + len(successful_post), len(post_values))
        self.assertGreater(failures, 0)

