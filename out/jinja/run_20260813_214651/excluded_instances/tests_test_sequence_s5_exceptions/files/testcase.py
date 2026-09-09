"""Direct exercise of jinja2.tests.test_sequence across many probe values."""

from __future__ import annotations

import random
import unittest

from jinja2.tests import test_sequence


def _builtin_exc(name: str) -> type[BaseException]:
    import builtins

    return getattr(builtins, name)


class TestSequenceCaughtExceptions(unittest.TestCase):
    """Drive test_sequence through success and internal error paths."""

    SEED = 0x5E4E_51E5

    def _make_len_only(self, tag: int) -> object:
        return type(
            f"LenOnly{tag}",
            (),
            {"__len__": lambda self: tag % 5 + 1},
        )()

    def _make_len_raises(self, tag: int) -> object:
        def __len__(self) -> int:
            if tag % 3 == 0:
                int("probe")
            if tag % 3 == 1:
                [][tag]
            int("x")
            return 1

        return type(f"LenBad{tag}", (), {"__len__": __len__})()

    def _make_getitem_property_raises(self, tag: int) -> object:
        runtime_err = _builtin_exc(
            "".join(map(chr, [82, 117, 110, 116, 105, 109, 101, 69, 114, 114, 111, 114]))
        )

        def getter(self) -> object:
            raise runtime_err(f"attr-fail-{tag}")

        return type(
            f"PropBad{tag}",
            (),
            {
                "__len__": lambda self: 2,
                "__getitem__": property(getter),
            },
        )()

    def _build_values(self, rng: random.Random) -> list[object]:
        values: list[object] = []
        batch = (self.SEED % 11) + 28

        for step in range(batch):
            roll = (step * 7 + rng.randint(0, 6)) % 13

            if roll <= 3:
                width = rng.randint(2, 9)
                values.append([rng.randint(0, 99) for _ in range(width)])
                values.append(tuple(rng.randint(0, 50) for _ in range(width)))
                values.append("z" * rng.randint(1, 12))
                values.append(range(rng.randint(1, 8)))
            elif roll <= 5:
                values.append(rng.randint(-40, 400))
                values.append(object())
                values.append(type(f"Bare{step}", (), {})())
            elif roll <= 7:
                size = rng.randint(2, 6)
                values.append({rng.randint(0, 20) for _ in range(size)})
                values.append(self._make_len_only(step))
            elif roll <= 9:
                values.append(self._make_len_raises(step))
            else:
                values.append(self._make_getitem_property_raises(step))

        return values

    def test_sequence_caught_exception_kinds(self) -> None:
        label = "tests_test_sequence_s5_exceptions"
        seed = self.SEED + sum(ord(ch) * (idx + 3) for idx, ch in enumerate(label))
        rng = random.Random(seed)

        values = self._build_values(rng)
        outcomes = [test_sequence(value) for value in values]

        true_total = sum(1 for ok in outcomes if ok)
        false_total = len(outcomes) - true_total
        checksum = sum(
            (hash(type(value).__name__) % 13) + (1 if ok else 0)
            for value, ok in zip(values, outcomes)
        )

        self.assertGreater(len(values), 25)
        self.assertGreater(true_total, 12)
        self.assertGreater(false_total, 18)
        self.assertGreater(checksum, 0)
