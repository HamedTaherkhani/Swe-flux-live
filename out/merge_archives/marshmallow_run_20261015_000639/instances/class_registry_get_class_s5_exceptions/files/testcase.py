import random
import unittest

from marshmallow import class_registry
from marshmallow.class_registry import get_class


SYLLABLES = ["ka", "ro", "mi", "tu", "ze", "lo", "vi", "na"]
MODULES = ["qa_reg.alpha", "qa_reg.beta", "qa_reg.gamma", "qa_reg.delta"]


def _make_name(rng):
    return "".join(rng.choice(SYLLABLES) for _ in range(3)).capitalize() + "Schema"


class TestGetClassExceptions(unittest.TestCase):
    def test_lookup_storm(self):
        rng = random.Random(4127)

        # Build a pool of unique base names.
        names = []
        while len(names) < 14:
            candidate = _make_name(rng)
            if candidate not in names:
                names.append(candidate)

        # Register every name in 1..3 modules (sometimes the same module twice).
        homes = {}
        for name in names:
            picks = [rng.choice(MODULES) for _ in range(rng.randint(1, 3))]
            for mod in picks:
                cls = type(name, (), {"__module__": mod})
                class_registry.register(name, cls)
            homes[name] = picks

        # Build lookup queries programmatically.
        queries = []
        for step in range(45):
            name = names[(step * 5 + rng.randint(0, 3)) % len(names)]
            roll = rng.random()
            if roll < 0.45:
                key = name
            elif roll < 0.65:
                key = f"{rng.choice(homes[name])}.{name}"
            elif roll < 0.82:
                key = name[: rng.randint(4, len(name) - 1)]
            else:
                key = f"{rng.choice(MODULES)}.{name}"
            queries.append((key, rng.random() < 0.35))

        ok = 0
        failed = 0
        for key, want_all in queries:
            try:
                result = get_class(key, all=want_all)
            except Exception:  # noqa: BLE001
                failed += 1
            else:
                ok += 1
                if isinstance(result, list):
                    self.assertGreater(len(result), 1)
                else:
                    self.assertTrue(isinstance(result, type))

        self.assertEqual(ok + failed, len(queries))
        self.assertGreater(ok, 0)
        self.assertGreater(failed, 0)
