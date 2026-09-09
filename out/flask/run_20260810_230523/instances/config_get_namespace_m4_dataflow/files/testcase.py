import random
import unittest

from flask.config import Config


class TestConfigNamespaceDataFlow(unittest.TestCase):
    def test_seeded_namespace_matrix(self):
        rng = random.Random(0xC0FFEE)
        namespace = "".join(chr(code) for code in (83, 69, 67, 84, 79, 82, 95))
        entries = {}

        for index in range(53):
            stem = "".join(
                chr(65 + ((index * 11 + offset * 7 + rng.randrange(26)) % 26))
                for offset in range(5 + index % 6)
            )
            prefix = namespace if (rng.getrandbits(5) ^ index) % 3 else stem[:3] + "_"
            suffix = f"{stem}_{(index * index + rng.randrange(1000)) % 997:03d}"
            entries[prefix + suffix] = {
                "index": index,
                "weight": sum((position + 1) * ord(char) for position, char in enumerate(stem)),
            }

        config = Config(".", entries)
        options = [
            (bool(mask & 1), bool(mask & 2))
            for mask in range(4)
        ]
        results = [
            config.get_namespace(
                namespace,
                lowercase=lowercase,
                trim_namespace=trim_namespace,
            )
            for lowercase, trim_namespace in options
        ]

        self.assertEqual(len(results), len(options))
        self.assertTrue(all(results))
        self.assertEqual(len({len(result) for result in results}), 1)
        self.assertGreater(
            sum(len(key) for result in results for key in result),
            len(entries),
        )
