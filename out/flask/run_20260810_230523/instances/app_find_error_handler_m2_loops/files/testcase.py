import random
import unittest

from flask import Flask


class TestFindErrorHandlerNestedLoops(unittest.TestCase):
    def test_generated_handler_searches(self) -> None:
        rng = random.Random(918273)
        app = Flask(__name__)

        exception_types: list[type[Exception]] = [
            type("GeneratedErrorRoot", (Exception,), {})
        ]
        for index in range(1, 21):
            exception_types.append(
                type(f"GeneratedError{index}", (exception_types[-1],), {})
            )

        unrelated_error = type("UnrelatedGeneratedError", (Exception,), {})
        orphan_error = type("OrphanGeneratedError", (Exception,), {})
        scope_names = [f"generated_scope_{index:02d}" for index in range(13)]

        def make_handler(marker: int):
            def handler(error: Exception) -> tuple[int, str]:
                return marker, type(error).__name__

            return handler

        for scope_index, scope_name in enumerate((*scope_names, None)):
            handler_map = app.error_handler_spec[scope_name][None]
            handler_map[unrelated_error] = make_handler(-(scope_index + 1))
            ancestor_index = (
                scope_index * scope_index
                + 5 * scope_index
                + rng.randrange(len(exception_types))
            ) % len(exception_types)
            handler_map[exception_types[ancestor_index]] = make_handler(
                scope_index * 37 + ancestor_index
            )

        outcomes = []
        for call_index in range(73):
            depth = (
                call_index * call_index
                + 11 * call_index
                + rng.randrange(len(exception_types))
            ) % len(exception_types)
            width = 2 + (
                call_index * 7 + rng.randrange(len(scope_names))
            ) % 8
            start = rng.randrange(len(scope_names))
            stride = 1 + rng.randrange(len(scope_names) - 1)
            blueprints = [
                scope_names[
                    (start + offset * stride + rng.randrange(3))
                    % len(scope_names)
                ]
                for offset in range(width)
            ]

            if call_index % len(scope_names) == 0:
                error = orphan_error(f"orphan-{call_index}")
            else:
                error = exception_types[depth](f"generated-{call_index}-{depth}")
            outcomes.append(app._find_error_handler(error, blueprints))

        resolved = [handler for handler in outcomes if handler is not None]
        unresolved = [handler for handler in outcomes if handler is None]
        self.assertTrue(resolved)
        self.assertTrue(unresolved)
        self.assertTrue(all(callable(handler) for handler in resolved))

        samples = [
            handler(exception_types[index % len(exception_types)]())
            for index, handler in enumerate(resolved)
        ]
        self.assertTrue(all(isinstance(sample[0], int) for sample in samples))
        self.assertTrue(all(sample[1].startswith("GeneratedError") for sample in samples))
