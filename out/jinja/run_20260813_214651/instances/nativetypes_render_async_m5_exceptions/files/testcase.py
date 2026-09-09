"""Direct exercise of NativeTemplate.render_async across async native rendering paths."""

from __future__ import annotations

import asyncio
import random
import unittest

from jinja2.nativetypes import NativeEnvironment


class TestNativeRenderAsyncExceptionAggregation(unittest.TestCase):
    """Drive NativeTemplate.render_async through success and failure scenarios."""

    SEED = 88314421

    def setUp(self) -> None:
        self.async_env = NativeEnvironment(enable_async=True)
        self.sync_env = NativeEnvironment()

    def _run(self, coro) -> object:
        return asyncio.run(coro)

    async def _render_async(self, env: NativeEnvironment, source: str, **kwargs: object) -> object:
        template = env.from_string(source)
        return await template.render_async(**kwargs)

    def test_sync_env_runtime_rejection(self) -> None:
        rng = random.Random(self.SEED + 1)
        template = self.sync_env.from_string("{{ 1 }}")
        failures = 0
        for repeat in range(16):
            rng.randint(0, 9)
            with self.assertRaises(Exception):
                self._run(template.render_async())
            failures += 1
        self.assertEqual(failures, 16)

    def test_safe_integer_literals(self) -> None:
        rng = random.Random(self.SEED + 2)
        template = self.async_env.from_string("{{ n }}")
        successes = 0
        for repeat in range(22):
            value = rng.randint(-40, 40)
            result = self._run(template.render_async(n=value))
            if result == value:
                successes += 1
        self.assertGreater(successes, 18)

    def test_safe_list_literals(self) -> None:
        rng = random.Random(self.SEED + 3)
        template = self.async_env.from_string("{{ items }}")
        successes = 0
        for repeat in range(20):
            span = rng.randint(3, 8)
            items = [repeat + idx for idx in range(span)]
            result = self._run(template.render_async(items=items))
            if result == items:
                successes += 1
        self.assertGreater(successes, 16)

    def test_safe_unparsed_string_outputs(self) -> None:
        rng = random.Random(self.SEED + 4)
        template = self.async_env.from_string("{{ label }}-{{ code }}")
        successes = 0
        for repeat in range(18):
            label = f"tag-{repeat}"
            code = rng.randint(10, 99)
            result = self._run(template.render_async(label=label, code=code))
            if isinstance(result, str) and label in result:
                successes += 1
        self.assertGreater(successes, 14)

    def test_undefined_attribute_batch(self) -> None:
        rng = random.Random(self.SEED + 5)
        template = self.async_env.from_string("{{ ghost.slot }}")
        failures = 0
        for repeat in range(24):
            rng.randint(0, 5)
            with self.assertRaises(Exception):
                self._run(template.render_async())
            failures += 1
        self.assertEqual(failures, 24)

    def test_undefined_math_batch(self) -> None:
        rng = random.Random(self.SEED + 6)
        template = self.async_env.from_string("{{ 3 + missing }}")
        failures = 0
        for repeat in range(20):
            rng.randint(0, 7)
            with self.assertRaises(Exception):
                self._run(template.render_async())
            failures += 1
        self.assertEqual(failures, 20)

    def test_zero_division_batch(self) -> None:
        rng = random.Random(self.SEED + 7)
        template = self.async_env.from_string("{{ 7 / denom }}")
        failures = 0
        for repeat in range(22):
            denom = rng.choice([0, 0, 0, 0, 1, 2])
            if denom == 0:
                with self.assertRaises(Exception):
                    self._run(template.render_async(denom=denom))
                failures += 1
            else:
                result = self._run(template.render_async(denom=denom))
                self.assertIsInstance(result, (int, float))
        self.assertGreaterEqual(failures, 12)

    def test_type_error_batch(self) -> None:
        rng = random.Random(self.SEED + 8)
        template = self.async_env.from_string("{{ 'prefix' + token }}")
        failures = 0
        for repeat in range(18):
            token = rng.choice([1, 2.5, [], {"k": repeat}])
            with self.assertRaises(Exception):
                self._run(template.render_async(token=token))
            failures += 1
        self.assertEqual(failures, 18)

    def test_value_error_filter_batch(self) -> None:
        def reject_token(value: object) -> object:
            return int(str(value))

        env = NativeEnvironment(enable_async=True)
        env.filters["reject_token"] = reject_token
        template = env.from_string("{{ raw|reject_token }}")
        rng = random.Random(self.SEED + 9)
        failures = 0
        for repeat in range(20):
            raw = f"bad-{repeat}-{rng.randint(0, 6)}"
            with self.assertRaises(Exception):
                self._run(template.render_async(raw=raw))
            failures += 1
        self.assertEqual(failures, 20)

    def test_oserror_test_batch(self) -> None:
        import ctypes

        from jinja2.utils import pass_environment

        @pass_environment
        def broken_test(env: NativeEnvironment, value: object) -> bool:
            marker = str(value)
            if marker.startswith("fail"):
                ctypes.CDLL(f"/nonexistent_lib_{marker}")
            return False

        env = NativeEnvironment(enable_async=True)
        env.tests["broken_test"] = broken_test
        template = env.from_string("{{ token is broken_test }}")
        rng = random.Random(self.SEED + 10)
        failures = 0
        for repeat in range(16):
            token = f"fail-{repeat}-{rng.randint(0, 5)}"
            with self.assertRaises(Exception):
                self._run(template.render_async(token=token))
            failures += 1
        self.assertEqual(failures, 16)

    def test_async_filter_failure_batch(self) -> None:
        import codecs

        async def boom_filter(value: object) -> object:
            if isinstance(value, int) and value % 3 == 0:
                codecs.lookup(f"codec-{value}-missing")
            return value

        boom_filter.jinja_async_variant = True
        env = NativeEnvironment(enable_async=True)
        env.filters["boom"] = boom_filter
        template = env.from_string("{{ n|boom }}")
        rng = random.Random(self.SEED + 11)
        failures = 0
        for repeat in range(18):
            n = rng.randint(0, 17)
            if n % 3 == 0:
                with self.assertRaises(Exception):
                    self._run(template.render_async(n=n))
                failures += 1
            else:
                result = self._run(template.render_async(n=n))
                self.assertEqual(result, n)
        self.assertGreater(failures, 4)

    def test_macro_runtime_errors(self) -> None:
        source = (
            "{% macro probe(x) %}{{ x / pivot }}{% endmacro %}"
            "{{ probe(offset) }}"
        )
        template = self.async_env.from_string(source)
        rng = random.Random(self.SEED + 12)
        failures = 0
        for repeat in range(14):
            pivot = rng.choice([0, 0, 1, 2, 3])
            offset = rng.randint(1, 9)
            if pivot == 0:
                with self.assertRaises(Exception):
                    self._run(template.render_async(pivot=pivot, offset=offset))
                failures += 1
            else:
                result = self._run(template.render_async(pivot=pivot, offset=offset))
                self.assertIsInstance(result, (int, float))
        self.assertGreaterEqual(failures, 4)

    def test_chained_failure_sweep(self) -> None:
        rng = random.Random(self.SEED + 13)
        templates = [
            "{{ lost.attr }}",
            "{{ 9 / zero }}",
            "{{ 'x' + num }}",
        ]
        failures = 0
        for repeat in range(21):
            source = templates[repeat % len(templates)]
            template = self.async_env.from_string(source)
            with self.assertRaises(Exception):
                if "lost" in source:
                    self._run(template.render_async())
                elif "zero" in source:
                    self._run(template.render_async(zero=0))
                else:
                    self._run(template.render_async(num=repeat))
            failures += 1
        self.assertEqual(failures, 21)
