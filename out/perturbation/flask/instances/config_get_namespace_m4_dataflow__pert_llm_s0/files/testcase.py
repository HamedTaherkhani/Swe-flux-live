import random
import unittest

from flask.config import Config


class TestConfigNamespaceDataFlow(unittest.TestCase):
    def test_seeded_namespace_matrix(self):
        rng = random.Random(0xDEADBEEF)
        namespace = "".join(chr(code) for code in (83, 69, 67, 84, 79, 82, 95, 88))
        entries = {}

        for index in range(500):
            stem = "".join(
                chr(65 + ((index * 13 + offset * 11 + rng.randrange(26)) % 26))
                for offset in range(15 + index % 25)
            )
            prefix = namespace if (rng.getrandbits(6) ^ index) % 3 else stem[:4] + "_"
            suffix = f"{stem}_{(index * index * 3 + rng.randrange(2000)) % 5003:04d}"
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
