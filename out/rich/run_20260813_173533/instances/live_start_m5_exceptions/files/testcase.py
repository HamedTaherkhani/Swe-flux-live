import builtins
import hashlib
import unittest
from io import StringIO

from rich.console import Console
from rich.live import Live


def _digest(seed: int, label: str) -> bytes:
    return hashlib.sha256(f"live-start-m5-{seed}-{label}".encode()).digest()


def _exc_class_name(slot: int) -> str:
    names = (
        (86, 97, 108, 117, 101, 69, 114, 114, 111, 114),
        (84, 121, 112, 101, 69, 114, 114, 111, 114),
        (82, 117, 110, 116, 105, 109, 101, 69, 114, 114, 111, 114),
        (75, 101, 121, 69, 114, 114, 111, 114),
        (65, 116, 116, 114, 105, 98, 117, 116, 101, 69, 114, 114, 111, 114),
        (73, 110, 100, 101, 120, 69, 114, 114, 111, 114),
        (90, 101, 114, 111, 68, 105, 118, 105, 115, 105, 111, 110, 69, 114, 114, 111, 114),
    )
    return "".join(chr(code) for code in names[slot % len(names)])


def _make_exc(seed: int, index: int):
    digest = _digest(seed, f"err-{index}")
    slot = (digest[0] + index * 11 + digest[1]) % 7
    token = digest[2] + index * 3
    cls = getattr(builtins, _exc_class_name(slot))
    return cls(f"slot-{token}")


def _make_console(seed: int, label: str) -> Console:
    digest = _digest(seed, label)
    width = 72 + (digest[0] % 24)
    return Console(
        file=StringIO(),
        width=width,
        force_terminal=True,
        legacy_windows=False,
    )


class RenderCarrier:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pending = None
        self.swallow_slot = None

    def arm_raise(self, exc: BaseException) -> None:
        self.pending = exc
        self.swallow_slot = None

    def arm_swallow(self, exc: BaseException, slot: int) -> None:
        self.pending = exc
        self.swallow_slot = slot

    def clear(self) -> None:
        self.pending = None
        self.swallow_slot = None

    def __call__(self) -> str:
        if self.pending is not None:
            exc = self.pending
            self.pending = None
            if self.swallow_slot is not None:
                swallowed = getattr(builtins, _exc_class_name(self.swallow_slot))
                try:
                    raise exc
                except swallowed:
                    return self.text
            raise exc
        return self.text


def _attempt_start(live: Live, *, refresh: bool) -> bool:
    try:
        live.start(refresh=refresh)
    except Exception:
        return False
    return True


def _failure_checksum(seed: int, failures: int, successes: int) -> int:
    digest = _digest(seed, "checksum")
    return failures * 17 + successes * 5 + digest[0] + digest[1] * 3


class LiveStartExceptionsTest(unittest.TestCase):
    def test_terminal_baseline_many_starts(self) -> None:
        seed = 1103
        digest = _digest(seed, "baseline")
        iterations = 18 + (digest[0] % 6)
        successes = 0
        for index in range(iterations):
            console = _make_console(seed, f"base-{index}")
            live = Live(
                f"wave-{index}",
                console=console,
                auto_refresh=False,
            )
            if _attempt_start(live, refresh=False):
                successes += 1
                live.stop()
        self.assertEqual(successes, iterations)
        self.assertGreater(_failure_checksum(seed, 0, successes), 120)

    def test_refresh_success_batch(self) -> None:
        seed = 1207
        digest = _digest(seed, "refresh-ok")
        iterations = 16 + (digest[1] % 5)
        successes = 0
        for index in range(iterations):
            console = _make_console(seed, f"rok-{index}")
            carrier = RenderCarrier(f"render-{index}")
            live = Live(console=console, auto_refresh=False, get_renderable=carrier)
            if _attempt_start(live, refresh=True):
                successes += 1
                live.stop()
        self.assertEqual(successes, iterations)
        self.assertGreater(_failure_checksum(seed, 0, successes), 110)

    def test_double_start_guard(self) -> None:
        seed = 1301
        digest = _digest(seed, "double")
        iterations = 10 + (digest[2] % 4)
        guard_hits = 0
        for index in range(iterations):
            console = _make_console(seed, f"dbl-{index}")
            live = Live(f"guard-{index}", console=console, auto_refresh=False)
            self.assertTrue(_attempt_start(live, refresh=False))
            if _attempt_start(live, refresh=True):
                guard_hits += 1
            live.stop()
        self.assertEqual(guard_hits, iterations)
        self.assertGreater(_failure_checksum(seed, 0, guard_hits), 90)

    def test_nested_live_stack(self) -> None:
        seed = 1409
        digest = _digest(seed, "nested")
        iterations = 8 + (digest[3] % 5)
        nested_starts = 0
        for index in range(iterations):
            console = _make_console(seed, f"nest-{index}")
            outer = Live(f"outer-{index}", console=console, auto_refresh=False)
            self.assertTrue(_attempt_start(outer, refresh=False))
            inner = Live(f"inner-{index}", console=console, auto_refresh=False)
            if _attempt_start(inner, refresh=False):
                nested_starts += 1
                inner.stop()
            outer.stop()
        self.assertEqual(nested_starts, iterations)
        self.assertGreater(_failure_checksum(seed, 0, nested_starts), 70)

    def test_seeded_value_error_cascade(self) -> None:
        seed = 1507
        digest = _digest(seed, "value-wave")
        iterations = 20 + (digest[4] % 8)
        failures = 0
        for index in range(iterations):
            if (digest[index % len(digest)] + index) % 3 == 0:
                continue
            console = _make_console(seed, f"val-{index}")
            carrier = RenderCarrier(f"v-{index}")
            live = Live(console=console, auto_refresh=False, get_renderable=carrier)
            cls = getattr(builtins, _exc_class_name(0))
            carrier.arm_raise(cls(f"v-{seed}-{index}"))
            if not _attempt_start(live, refresh=True):
                failures += 1
        self.assertGreater(failures, 12)
        self.assertGreater(_failure_checksum(seed, failures, 0), 250)

    def test_seeded_type_error_cascade(self) -> None:
        seed = 1601
        digest = _digest(seed, "type-wave")
        iterations = 17 + (digest[5] % 6)
        failures = 0
        for index in range(iterations):
            if index % 5 == 0:
                continue
            console = _make_console(seed, f"typ-{index}")
            carrier = RenderCarrier(f"t-{index}")
            live = Live(console=console, auto_refresh=False, get_renderable=carrier)
            cls = getattr(builtins, _exc_class_name(1))
            carrier.arm_raise(cls(f"t-{seed}-{index}"))
            if not _attempt_start(live, refresh=True):
                failures += 1
        self.assertGreater(failures, 10)
        self.assertGreater(_failure_checksum(seed, failures, 0), 200)

    def test_mixed_palette_wave_a(self) -> None:
        seed = 1703
        digest = _digest(seed, "mix-a")
        iterations = 22 + (digest[6] % 5)
        failures = 0
        for index in range(iterations):
            console = _make_console(seed, f"mixa-{index}")
            carrier = RenderCarrier(f"m-{index}")
            live = Live(console=console, auto_refresh=False, get_renderable=carrier)
            carrier.arm_raise(_make_exc(seed, index))
            if not _attempt_start(live, refresh=True):
                failures += 1
        self.assertEqual(failures, iterations)
        self.assertGreater(_failure_checksum(seed, failures, 0), 320)

    def test_mixed_palette_wave_b(self) -> None:
        seed = 1801
        digest = _digest(seed, "mix-b")
        iterations = 19 + (digest[7] % 7)
        failures = 0
        for index in range(iterations):
            if (digest[(index * 2) % len(digest)] % 4) == 0:
                continue
            console = _make_console(seed, f"mixb-{index}")
            carrier = RenderCarrier(f"b-{index}")
            live = Live(console=console, auto_refresh=False, get_renderable=carrier)
            carrier.arm_raise(_make_exc(seed + 3, index + 5))
            if not _attempt_start(live, refresh=True):
                failures += 1
        self.assertGreater(failures, 12)
        self.assertGreater(_failure_checksum(seed, failures, 0), 230)

    def test_swallowed_value_error_runs(self) -> None:
        seed = 1907
        digest = _digest(seed, "swallow")
        iterations = 15 + (digest[8] % 6)
        swallowed = 0
        successes = 0
        for index in range(iterations):
            console = _make_console(seed, f"sw-{index}")
            carrier = RenderCarrier(f"s-{index}")
            live = Live(console=console, auto_refresh=False, get_renderable=carrier)
            if index % 2 == 0:
                cls = getattr(builtins, _exc_class_name(0))
                carrier.arm_swallow(cls(f"hidden-{index}"), slot=0)
                swallowed += 1
            else:
                cls = getattr(builtins, _exc_class_name(2))
                carrier.arm_raise(cls(f"surfaced-{index}"))
            if _attempt_start(live, refresh=True):
                successes += 1
                live.stop()
        self.assertEqual(swallowed, (iterations + 1) // 2)
        self.assertGreater(successes, swallowed // 2)
        self.assertGreater(_failure_checksum(seed, swallowed, successes), 180)

    def test_key_error_and_attribute_wave(self) -> None:
        seed = 2003
        digest = _digest(seed, "key-attr")
        iterations = 21 + (digest[9] % 4)
        failures = 0
        for index in range(iterations):
            console = _make_console(seed, f"ka-{index}")
            carrier = RenderCarrier(f"k-{index}")
            live = Live(console=console, auto_refresh=False, get_renderable=carrier)
            slot = 3 if index % 2 == 0 else 4
            digest_slot = _digest(seed, f"ka-slot-{index}")
            token = digest_slot[0] + index
            cls = getattr(builtins, _exc_class_name(slot))
            carrier.arm_raise(cls(f"k-{token}"))
            if not _attempt_start(live, refresh=True):
                failures += 1
        self.assertEqual(failures, iterations)
        self.assertGreater(_failure_checksum(seed, failures, 0), 300)

    def test_index_runtime_zero_wave(self) -> None:
        seed = 2111
        digest = _digest(seed, "irz")
        iterations = 24 + (digest[10] % 5)
        failures = 0
        for index in range(iterations):
            if index % 7 == 0:
                continue
            console = _make_console(seed, f"irz-{index}")
            carrier = RenderCarrier(f"z-{index}")
            live = Live(console=console, auto_refresh=False, get_renderable=carrier)
            branch = (digest[index % len(digest)] + index) % 3
            slot_map = (5, 2, 6)
            cls = getattr(builtins, _exc_class_name(slot_map[branch]))
            carrier.arm_raise(cls(f"z-{index}"))
            if not _attempt_start(live, refresh=True):
                failures += 1
        self.assertGreater(failures, 15)
        self.assertGreater(_failure_checksum(seed, failures, 0), 280)

    def test_screen_mode_refresh_failures(self) -> None:
        seed = 2207
        digest = _digest(seed, "screen")
        iterations = 14 + (digest[11] % 5)
        failures = 0
        for index in range(iterations):
            console = _make_console(seed, f"scr-{index}")
            carrier = RenderCarrier(f"screen-{index}")
            live = Live(
                console=console,
                auto_refresh=False,
                get_renderable=carrier,
                screen=True,
            )
            if index % 3 != 0:
                carrier.arm_raise(_make_exc(seed + 11, index))
            else:
                carrier.clear()
            if not _attempt_start(live, refresh=True):
                failures += 1
            elif live.is_started:
                live.stop()
        expected_failures = iterations - (iterations // 3)
        self.assertEqual(failures, expected_failures)
        self.assertGreater(_failure_checksum(seed, failures, iterations - failures), 210)
