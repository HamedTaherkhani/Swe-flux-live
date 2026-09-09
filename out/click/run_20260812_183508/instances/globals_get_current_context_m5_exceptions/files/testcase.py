import math
from types import SimpleNamespace
import unittest

import click
import click.globals as runtime_globals
from click.globals import resolve_color_default


@click.pass_context
def contextual_probe(context):
    return context.color


class GeneratedStack:
    def __init__(self, codes, fallback):
        self.codes = tuple(codes)
        self.fallback = fallback
        self.cursor = 0

    def __getitem__(self, key):
        code = self.codes[self.cursor % len(self.codes)]
        self.cursor += 1

        if code == 0:
            return (key + 2) // (key + 1)
        if code == 1:
            return {}[key]
        if code == 2:
            return bytes([255]).decode(
                bytes([97, 115, 99, 105, 105]).decode()
            )
        if code == 3:
            return int("not-a-number-" + str(self.cursor))
        if code == 4:
            return [][key]
        if code == 5:
            return getattr(object(), "generated_" + str(self.cursor))
        if code == 6:
            return math.exp(900 + self.cursor)
        if code == 7:
            return next(iter(()))
        if code == 8:
            return len(self.cursor)
        if code == 9:
            return eval("unbound_" + str(self.cursor))
        if code == 10:
            return __import__("absent_generated_" + str(self.cursor))
        if code == 11:
            return self.fallback
        if code == 12:
            try:
                bytes([255]).decode("ascii")
            except Exception:
                return self.fallback
        if code == 13:
            assert key + 1
        if code == 14:
            return memoryview(b"")[key]

        first = {key: self.cursor}
        first.pop(key)
        return first.pop(key)


class TestGeneratedContextObservations(unittest.TestCase):
    def setUp(self):
        self._drop_stack()

    def tearDown(self):
        self._drop_stack()

    def _drop_stack(self):
        if hasattr(runtime_globals._local, "stack"):
            del runtime_globals._local.stack

    def _install_generated_stack(self, codes):
        fallback = SimpleNamespace(color=bool(sum(codes) % 2))
        runtime_globals._local.stack = GeneratedStack(codes, fallback)
        return fallback

    def _exercise_resolution(self, codes):
        fallback = self._install_generated_stack(codes)
        completed = []
        failed = 0
        for color_hint in (None for _ in codes):
            try:
                completed.append(resolve_color_default(color_hint))
            except Exception:
                failed += 1
        self.assertEqual(len(completed) + failed, len(codes))
        return fallback, completed, failed

    def _exercise_decorator(self, codes):
        self._install_generated_stack(codes)
        completed = []
        failed = 0
        for _ in codes:
            try:
                completed.append(contextual_probe())
            except Exception:
                failed += 1
        self.assertEqual(len(completed) + failed, len(codes))
        return completed, failed

    def test_resolver_without_thread_state(self):
        attempts = sum(range(7)) - len(range(4))
        values = [resolve_color_default() for _ in range(attempts)]
        self.assertTrue(values)
        self.assertTrue(all(value is None for value in values))

    def test_resolver_with_depleted_native_stack(self):
        runtime_globals._local.stack = []
        values = [
            resolve_color_default(None)
            for _ in range(len(tuple(range(3, 19))))
        ]
        self.assertTrue(values)
        self.assertFalse(any(value is not None for value in values))

    def test_decorator_without_thread_state(self):
        attempts = len({value * value for value in range(1, 10)})
        for _ in range(attempts):
            with self.assertRaises(Exception):
                contextual_probe()

    def test_decorator_with_depleted_native_stack(self):
        runtime_globals._local.stack = list(range(2, 2))
        attempts = sum(1 for value in range(39) if value % 3 == 1)
        for _ in range(attempts):
            with self.assertRaises(Exception):
                contextual_probe()

    def test_resolver_with_arithmetic_and_conversion_failures(self):
        width = sum(range(9)) - len(range(5))
        codes = [(index * index + index) % 4 for index in range(width)]
        _, completed, failed = self._exercise_resolution(codes)
        self.assertFalse(completed)
        self.assertGreater(failed, 0)

    def test_resolver_with_absorbed_lookup_failures(self):
        width = sum(range(8))
        choices = (4, 5, 14)
        codes = [
            choices[(index * 5 + index // 3) % len(choices)]
            for index in range(width)
        ]
        _, completed, failed = self._exercise_resolution(codes)
        self.assertEqual(failed, 0)
        self.assertTrue(all(value is None for value in completed))

    def test_resolver_with_propagated_runtime_failures(self):
        width = sum(range(10)) - len(range(4))
        choices = tuple(range(6, 11)) + (13, 15)
        codes = [
            choices[(index * 7 + index // 2) % len(choices)]
            for index in range(width)
        ]
        _, completed, failed = self._exercise_resolution(codes)
        self.assertFalse(completed)
        self.assertGreater(failed, 0)

    def test_resolver_with_valid_generated_context(self):
        width = sum(range(7)) + len(range(2))
        codes = [11 + (index - index) for index in range(width)]
        fallback, completed, failed = self._exercise_resolution(codes)
        self.assertEqual(failed, 0)
        self.assertTrue(all(value is fallback.color for value in completed))

    def test_resolver_with_callee_local_recovery(self):
        width = sum(range(8)) + len(range(2))
        codes = [11 + (index % 2) for index in range(width)]
        fallback, completed, failed = self._exercise_resolution(codes)
        self.assertEqual(failed, 0)
        self.assertTrue(all(value == fallback.color for value in completed))

    def test_resolver_across_repeated_context_scopes(self):
        command = click.Command("generated-scope")
        context = click.Context(command, color=True)
        iterations = len(tuple(range(4, 20)))
        for index in range(iterations):
            with context.scope(cleanup=bool(index % 2)):
                self.assertIs(resolve_color_default(), context.color)
                self.assertIs(resolve_color_default(None), context.color)
        self.assertIsNone(resolve_color_default())

    def test_decorator_with_generated_mixed_stack(self):
        width = sum(range(8)) - len(range(3))
        choices = (0, 2, 4, 5, 6, 8, 11, 12, 14)
        codes = [
            choices[(index * index + 3 * index) % len(choices)]
            for index in range(width)
        ]
        completed, failed = self._exercise_decorator(codes)
        self.assertEqual(len(completed) + failed, len(codes))
        self.assertTrue(completed)
        self.assertGreater(failed, 0)

    def test_decorator_inside_then_outside_scope(self):
        command = click.Command("decorated-scope")
        context = click.Context(command, color=False)
        width = sum(1 for value in range(54) if value % 3 == 0)
        with context.scope(cleanup=False):
            values = [contextual_probe() for _ in range(width)]
        self.assertTrue(all(value is context.color for value in values))
        attempts = len(tuple(range(2, 8)))
        for _ in range(attempts):
            with self.assertRaises(Exception):
                contextual_probe()
