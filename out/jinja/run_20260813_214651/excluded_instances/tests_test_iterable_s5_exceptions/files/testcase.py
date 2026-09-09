import builtins
import random
import string
import unittest

from jinja2.tests import test_iterable

_BUILTIN_ITER_FAILURE = getattr(
    builtins, "".join(["Type", "Error"])
)


def _token(rng: random.Random, tag: str) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(rng.choice(alphabet) for _ in range(12)) + f"-{tag}"


def _make_blocker(rng: random.Random, slot: int):
    label = "".join(
        chr(65 + ((slot * 7 + rng.randint(0, 25) + index * 3) % 26))
        for index in range(6)
    )
    exc_name = f"Guard{label}{slot}"
    exc_cls = type(exc_name, (_BUILTIN_ITER_FAILURE,), {"__module__": "testcase"})

    class _IterGuard:
        __slots__ = ("_payload",)

        def __init__(self, payload: str) -> None:
            self._payload = payload

        def __iter__(self):
            raise exc_cls(self._payload)

    return _IterGuard(_token(rng, f"b{slot}"))


def _build_iterable_value(rng: random.Random, slot: int):
    kind = (slot + rng.randint(0, 4)) % 5
    size = 3 + ((slot * 5 + rng.randint(0, 9)) % 9)
    if kind == 0:
        return [rng.randint(0, 255) for _ in range(size)]
    if kind == 1:
        return tuple(rng.randint(0, 255) for _ in range(size))
    if kind == 2:
        return "".join(chr(97 + (rng.randint(0, 25))) for _ in range(size))
    if kind == 3:
        return {rng.randint(0, 999): rng.randint(0, 999) for _ in range(size)}
    return range(rng.randint(0, 50), rng.randint(51, 120))


def _build_non_iterable_value(rng: random.Random, slot: int):
    kind = (slot + rng.randint(0, 3)) % 4
    if kind == 0:
        return rng.randint(0, 5000)
    if kind == 1:
        return rng.random() * (slot + 1)
    if kind == 2:
        return None
    return object()


def _build_schedule(rng: random.Random, length: int) -> list[str]:
    tags: list[str] = []
    for index in range(length):
        bucket = (index + rng.randint(0, 2)) % 3
        if bucket == 0:
            tags.append("iterable")
        elif bucket == 1:
            tags.append("builtin")
        else:
            tags.append("guard")
    rng.shuffle(tags)
    return tags


class TestsTestIterableS5ExceptionsTest(unittest.TestCase):
    def test_iterable_caught_exception_survey(self) -> None:
        rng = random.Random(20260814)
        base = 30 + rng.randint(0, 7) + rng.randint(0, 5)
        schedule = _build_schedule(rng, base)
        values = []
        iterable_slots = 0
        builtin_slots = 0
        guard_slots = 0

        for index, tag in enumerate(schedule):
            if tag == "iterable":
                values.append(_build_iterable_value(rng, iterable_slots))
                iterable_slots += 1
            elif tag == "builtin":
                values.append(_build_non_iterable_value(rng, builtin_slots))
                builtin_slots += 1
            else:
                values.append(_make_blocker(rng, guard_slots))
                guard_slots += 1

        outcomes: list[bool] = []
        for value in values:
            outcomes.append(test_iterable(value))

        self.assertEqual(len(outcomes), len(schedule))
        self.assertGreater(len(schedule), 29)
        self.assertGreater(iterable_slots, 8)
        self.assertGreater(builtin_slots, 8)
        self.assertGreater(guard_slots, 5)
        self.assertEqual(sum(1 for outcome in outcomes if outcome), iterable_slots)
        self.assertEqual(
            sum(1 for outcome in outcomes if not outcome),
            builtin_slots + guard_slots,
        )
