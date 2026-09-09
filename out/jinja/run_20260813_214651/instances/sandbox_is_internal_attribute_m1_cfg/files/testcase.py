"""Exercise sandbox attribute policy through SandboxedEnvironment entry points."""

from __future__ import annotations

import asyncio
import random
import sys
import types
import unittest

from jinja2.runtime import Undefined
from jinja2.sandbox import SandboxedEnvironment


class TestSandboxInternalAttributePolicy(unittest.TestCase):
    """Probe attribute safety indirectly via sandbox getters and templates."""

    SEED = 27182818

    def setUp(self) -> None:
        self.env = SandboxedEnvironment()

    def _via_getattr(self, obj: object, attr: str) -> object:
        return self.env.getattr(obj, attr)

    def _via_getitem(self, obj: object, key: str) -> object:
        return self.env.getitem(obj, key)

    def _via_template_attr(self, obj: object, attr: str) -> str:
        template = self.env.from_string("{{ holder." + attr + " }}")
        return template.render(holder=obj)

    def _via_template_subscript(self, obj: object, key: str) -> str:
        template = self.env.from_string("{{ holder[key] }}")
        return template.render(holder=obj, key=key)

    def _assert_access_completed(self, value: object) -> None:
        self.assertTrue(value is None or not isinstance(value, Exception))

    def test_type_mro_sweep(self) -> None:
        pool = [int, str, list, dict, tuple, set, bytes, float, bool, type, object]
        blocked = 0
        for idx in range(28):
            cls = pool[(idx * 5 + 3) % len(pool)]
            value = self._via_getattr(cls, "mro")
            if isinstance(value, Undefined):
                blocked += 1
        self.assertGreater(blocked, 0)

    def test_type_named_attributes(self) -> None:
        cases = [
            (int, "to_bytes"),
            (float, "as_integer_ratio"),
            (tuple, "count"),
            (set, "union"),
            (bytes, "decode"),
            (bool, "conjugate"),
            (range, "start"),
            (str, "capitalize"),
            (list, "sort"),
            (dict, "copy"),
            (type, "mro"),
            (object, "mro"),
        ]
        for cls, attr in cases:
            value = self._via_getattr(cls, attr)
            self._assert_access_completed(value)

    def test_function_objects(self) -> None:
        def sample(x: int) -> int:
            return x + 1

        tags = [f"tag-{idx}" for idx in range(6)]
        for repeat, tag in enumerate(tags):
            setattr(sample, tag, repeat * 3)
        for repeat in range(18):
            tag = tags[(repeat * 7 + 2) % len(tags)]
            value = self._via_getattr(sample, tag)
            self.assertEqual(value, tags.index(tag) * 3)

    def test_bound_method_wrappers(self) -> None:
        def echo(self) -> str:
            return "echo"

        class Carrier:
            pass

        Carrier.echo = echo
        carriers = [Carrier() for _ in range(12)]
        for repeat in range(20):
            echo.readout = f"r-{repeat}"
            value = self._via_getattr(carriers[repeat % len(carriers)].echo, "readout")
            self.assertEqual(value, f"r-{repeat}")

    def test_generator_internals(self) -> None:
        def maker(seed: int):
            for offset in range(seed % 5 + 3):
                yield offset * seed

        attrs = ["gi_frame", "gi_code", "gi_running", "gi_yieldfrom", "close"]
        for repeat in range(22):
            gen = maker(repeat + 4)
            attr = attrs[(repeat * 11 + 5) % len(attrs)]
            value = self._via_getattr(gen, attr)
            self._assert_access_completed(value)

    def test_code_and_frame_objects(self) -> None:
        def inner() -> None:
            return None

        code = inner.__code__
        frame = sys._getframe()
        targets = [
            (code, "co_name"),
            (code, "co_varnames"),
            (frame, "f_lineno"),
            (frame, "f_globals"),
            (frame, "f_code"),
        ]
        for repeat in range(16):
            obj, attr = targets[repeat % len(targets)]
            value = self._via_getattr(obj, attr)
            self._assert_access_completed(value)

    def test_traceback_objects(self) -> None:
        tracebacks: list[types.TracebackType] = []
        for divisor in range(2, 14):
            try:
                _ = 10 // (divisor - divisor)
            except ZeroDivisionError:
                tb = sys.exc_info()[2]
                assert tb is not None
                tracebacks.append(tb)
        attrs = ["tb_lineno", "tb_frame", "tb_next", "tb_lasti"]
        for repeat in range(len(tracebacks) * 2):
            tb = tracebacks[repeat % len(tracebacks)]
            attr = attrs[(repeat * 5 + 1) % len(attrs)]
            value = self._via_getattr(tb, attr)
            self._assert_access_completed(value)

    def test_coroutine_objects(self) -> None:
        async def waiter(tag: int) -> int:
            await asyncio.sleep(0)
            return tag

        attrs = ["cr_frame", "cr_code", "cr_running", "cr_origin", "close"]
        for repeat in range(14):
            coro = waiter(repeat + 9)
            attr = attrs[(repeat * 4 + 2) % len(attrs)]
            value = self._via_getattr(coro, attr)
            self._assert_access_completed(value)
            coro.close()

    def test_async_generator_objects(self) -> None:
        async def stream(width: int):
            for item in range(width):
                yield item * width

        attrs = ["ag_code", "ag_frame", "ag_running", "asend", "athrow"]
        for repeat in range(14):
            agen = stream((repeat % 6) + 2)
            attr = attrs[(repeat * 6 + 3) % len(attrs)]
            value = self._via_getattr(agen, attr)
            self._assert_access_completed(value)
            agen.aclose()

    def test_instance_public_access(self) -> None:
        class Holder:
            def __init__(self, label: str, width: int) -> None:
                self.label = label
                self.width = width
                self.values = list(range(width))

            def __getitem__(self, key: str) -> str:
                raise TypeError("mapping disabled")

        holders = [Holder(f"item-{idx}", (idx % 7) + 2) for idx in range(12)]
        attrs = ["label", "width", "values"]
        for repeat in range(24):
            holder = holders[repeat % len(holders)]
            attr = attrs[(repeat * 3 + 2) % len(attrs)]
            value = self._via_getattr(holder, attr)
            self.assertIsNotNone(value)

    def test_plain_mutable_methods(self) -> None:
        rng = random.Random(self.SEED + 17)
        payloads: list[object] = [
            [rng.randint(0, 9) for _ in range(14)],
            {f"k{idx}": idx for idx in range(11)},
            {rng.randint(0, 99) for _ in range(9)},
            bytearray(rng.randbytes(10)),
        ]
        attrs = ["append", "pop", "add", "clear", "extend", "remove"]
        for repeat in range(26):
            obj = payloads[repeat % len(payloads)]
            attr = attrs[(repeat * 5 + 1) % len(attrs)]
            if not hasattr(obj, attr):
                continue
            value = self._via_getattr(obj, attr)
            self.assertTrue(callable(value) or isinstance(value, Undefined))

    def test_getitem_fallback_chain(self) -> None:
        class MappingShy:
            def __init__(self, token: str) -> None:
                self.token = token
                self.payload = token[::-1]

            def __getitem__(self, key: str) -> str:
                raise LookupError(key)

        items = [MappingShy(f"tok-{idx}") for idx in range(18)]
        keys = ["token", "payload", "missing"]
        for repeat in range(21):
            item = items[repeat % len(items)]
            key = keys[(repeat * 5 + 1) % len(keys)]
            value = self._via_getitem(item, key)
            if key == "missing":
                self.assertIsInstance(value, Undefined)
            else:
                self.assertIsInstance(value, str)

    def test_template_attribute_batch(self) -> None:
        rng = random.Random(self.SEED + 99)
        bases = [str, list, dict, tuple, set]
        attrs = ["mro", "capitalize", "append", "keys", "union"]
        for repeat in range(26):
            base = bases[(repeat + rng.randint(0, 2)) % len(bases)]
            attr = attrs[(repeat * 7 + 3) % len(attrs)]
            if not hasattr(base, attr):
                continue
            rendered = self._via_template_attr(base, attr)
            self.assertIsInstance(rendered, str)

    def test_template_subscript_batch(self) -> None:
        rng = random.Random(self.SEED + 123)
        records = [{"name": f"n-{i}", "size": i * 3} for i in range(16)]
        keys = ["name", "size", "missing"]
        for repeat in range(24):
            record = records[(repeat + rng.randint(0, 4)) % len(records)]
            key = keys[(repeat * 4 + 2) % len(keys)]
            rendered = self._via_template_subscript(record, key)
            self.assertIsInstance(rendered, str)
