import json
import os
import random
import unittest
from unittest.mock import patch

from flask.config import Config


class TestConfigFromPrefixedEnvLoops(unittest.TestCase):
    def test_generated_nested_environment(self) -> None:
        rng = random.Random(48019)
        prefix = "DYNAMICCFG"
        environ: dict[str, str] = {}

        for index in range(57):
            depth = 2 + rng.randrange(5)
            path = [f"SECTION_{index % 9}", f"NODE_{index:03d}"]
            path.extend(
                f"LEVEL_{level}_{rng.randrange(97):02d}" for level in range(depth - 2)
            )
            path.append(f"VALUE_{(index * 23 + rng.randrange(101)) % 211:03d}")
            key = f"{prefix}_" + "__".join(path)

            selector = (index + rng.randrange(13)) % 4
            if selector == 0:
                value = json.dumps(
                    {
                        "slot": (index * 17 + rng.randrange(31)) % 103,
                        "enabled": index % 3 == 0,
                    }
                )
            elif selector == 1:
                value = json.dumps(
                    [(index + offset * offset) % 29 for offset in range(index % 6)]
                )
            elif selector == 2:
                value = f"unquoted-{index}-{rng.randrange(1000)}"
            else:
                value = json.dumps((index * 37 + rng.randrange(43)) % 257)

            environ[key] = value

        for index in range(14):
            environ[f"{prefix}_DIRECT_{index:02d}"] = json.dumps(
                (index * index + rng.randrange(71)) % 149
            )

        for index in range(23):
            environ[f"UNRELATED_{index:02d}_{rng.randrange(1000):03d}"] = str(
                rng.randrange(10000)
            )

        config = Config(".")
        with patch.dict(os.environ, environ, clear=True):
            loaded = config.from_prefixed_env(prefix)

        self.assertTrue(loaded)
        self.assertTrue(all(key.startswith(("SECTION_", "DIRECT_")) for key in config))
        self.assertTrue(any(isinstance(value, dict) for value in config.values()))
        self.assertTrue(any(not isinstance(value, dict) for value in config.values()))
