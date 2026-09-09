import random
import unittest

from sqlglot import exp
from sqlglot.dialects.dialect import map_date_part


class _SettingFragment(str):
    def __new__(cls, value, behavior):
        instance = super().__new__(cls, value)
        instance.behavior = behavior
        return instance

    def split(self, separator=None, maxsplit=-1):
        if separator != "=":
            return super().split(separator, maxsplit)
        if self.behavior == "empty":
            return []
        if self.behavior == "mapping":
            return {"setting": "enabled"}
        if self.behavior == "decode":
            return bytes([max(range(240, 256))]).decode("ascii")
        if self.behavior == "divide":
            return len(self) // (len(self) - len(self))
        if self.behavior == "numeric":
            return int(self[-1:])
        if self.behavior == "exhaust":
            return next(iter(()))
        if self.behavior == "swallow":
            try:
                assert len(self) < 0
            except Exception:
                pass
        return super().split(separator, maxsplit)


class _DialectText(str):
    def __new__(cls, value, behavior):
        instance = super().__new__(cls, value)
        instance.behavior = behavior
        return instance

    def split(self, separator=None, maxsplit=-1):
        if separator != ",":
            return super().split(separator, maxsplit)
        if self.behavior == "none":
            return None
        if self.behavior == "atom":
            return [object()]
        return [
            "duckdb",
            _SettingFragment(
                (
                    "version=x"
                    if self.behavior == "numeric"
                    else "normalization_strategy=case_sensitive"
                ),
                self.behavior,
            ),
        ]


class TestDialectLookupExceptions(unittest.TestCase):
    def _part(self, seed):
        rng = random.Random(seed)
        return exp.var("".join(rng.choice("yearmonthday") for _ in range(9)))

    def _failures(self, dialects, seed):
        failures = 0
        part = self._part(seed)
        for dialect in dialects:
            try:
                map_date_part(part.copy(), dialect)
            except BaseException as error:
                self.assertIsInstance(error, Exception)
                self.assertTrue(str(error))
                failures += 1
        self.assertEqual(failures, len(dialects))

    def test_unknown_generated_names(self):
        rng = random.Random(7301)
        dialects = [
            "missing_" + "".join(rng.choice("qvxz") for _ in range(8))
            for _ in range(17 + rng.randrange(5))
        ]
        self._failures(dialects, 101)

    def test_non_text_inputs(self):
        rng = random.Random(7302)
        factories = (list, dict, set, tuple)
        dialects = [
            factories[index % len(factories)]([rng.randrange(1000)])
            if factories[index % len(factories)] is not dict
            else {"dialect": rng.randrange(1000)}
            for index in range(16 + rng.randrange(6))
        ]
        self._failures(dialects, 102)

    def test_invalid_normalization_settings(self):
        rng = random.Random(7303)
        dialects = [
            f"duckdb, normalization_strategy=mode_{rng.randrange(10_000)}"
            for _ in range(18 + rng.randrange(5))
        ]
        self._failures(dialects, 103)

    def test_invalid_version_components(self):
        rng = random.Random(7304)
        dialects = [
            f"duckdb, version={rng.randrange(2, 9)}."
            + "".join(rng.choice("klmnop") for _ in range(4))
            for _ in range(19 + rng.randrange(5))
        ]
        self._failures(dialects, 104)

    def test_unsupported_generated_settings(self):
        rng = random.Random(7305)
        dialects = [
            f"duckdb, option_{rng.randrange(10_000)}={rng.randrange(2)}"
            for _ in range(20 + rng.randrange(5))
        ]
        self._failures(dialects, 105)

    def test_split_returns_no_sequence(self):
        rng = random.Random(7306)
        dialects = [
            _DialectText(f"duckdb,{rng.randrange(10_000)}", "none")
            for _ in range(15 + rng.randrange(5))
        ]
        self._failures(dialects, 106)

    def test_split_returns_non_text_name(self):
        rng = random.Random(7307)
        dialects = [
            _DialectText(f"duckdb,{rng.randrange(10_000)}", "atom")
            for _ in range(16 + rng.randrange(5))
        ]
        self._failures(dialects, 107)

    def test_empty_setting_pairs(self):
        rng = random.Random(7308)
        dialects = [
            _DialectText(f"duckdb,{rng.randrange(10_000)}", "empty")
            for _ in range(17 + rng.randrange(5))
        ]
        self._failures(dialects, 108)

    def test_mapping_setting_pairs(self):
        rng = random.Random(7309)
        dialects = [
            _DialectText(f"duckdb,{rng.randrange(10_000)}", "mapping")
            for _ in range(18 + rng.randrange(5))
        ]
        self._failures(dialects, 109)

    def test_non_ascii_setting_fragments(self):
        rng = random.Random(7310)
        dialects = [
            _DialectText(f"duckdb,{rng.randrange(10_000)}", "decode")
            for _ in range(19 + rng.randrange(5))
        ]
        self._failures(dialects, 110)

    def test_arithmetic_setting_fragments(self):
        rng = random.Random(7311)
        dialects = [
            _DialectText(f"duckdb,{rng.randrange(10_000)}", "divide")
            for _ in range(20 + rng.randrange(5))
        ]
        self._failures(dialects, 111)

    def test_numeric_setting_fragments(self):
        rng = random.Random(7314)
        dialects = [
            _DialectText(f"duckdb,{rng.randrange(10_000)}", "numeric")
            for _ in range(15 + rng.randrange(5))
        ]
        self._failures(dialects, 114)

    def test_exhausted_setting_fragments(self):
        rng = random.Random(7312)
        dialects = [
            _DialectText(f"duckdb,{rng.randrange(10_000)}", "exhaust")
            for _ in range(21 + rng.randrange(5))
        ]
        self._failures(dialects, 112)

    def test_handled_fragment_errors_complete_safely(self):
        rng = random.Random(7313)
        dialects = [
            _DialectText(f"duckdb,{rng.randrange(10_000)}", "swallow")
            for _ in range(22 + rng.randrange(5))
        ]
        outputs = [map_date_part(self._part(113), dialect) for dialect in dialects]
        self.assertEqual(len(outputs), len(dialects))
        self.assertTrue(all(isinstance(output, exp.Expression) for output in outputs))
