import random
import unittest
from typing import Any

from fastapi import FastAPI
from starlette.middleware import Middleware


class GeneratedMiddleware:
    constructed = 0
    fingerprint = 0

    def __init__(self, app: Any, *, marker: int, switch: bool) -> None:
        self.app = app
        self.marker = marker
        self.switch = switch
        type(self).constructed += 1
        type(self).fingerprint = (
            type(self).fingerprint * 131 + marker * 17 + int(switch)
        ) % 1_000_003

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self.app(scope, receive, send)


class TestBuildMiddlewareStackLoops(unittest.TestCase):
    def test_generated_middleware_populations(self) -> None:
        rng = random.Random(0xB17D5)
        app = FastAPI(debug=bool(rng.getrandbits(1)))
        default_handlers = dict(app.exception_handlers)
        GeneratedMiddleware.constructed = 0
        GeneratedMiddleware.fingerprint = 0
        total_user_middleware = 0

        async def generated_handler(request: Any, exc: Exception) -> None:
            del request, exc

        invocation_total = len("middleware") + len("stack") - 2
        for invocation_index in range(invocation_total):
            population = (
                len(default_handlers) * len("layers")
                + (rng.randrange(10_000) ^ (invocation_index * 97)) % 41
            )
            markers = [
                (rng.randrange(1_000_000) + position * (invocation_index + 3))
                % 999_983
                for position in range(population)
            ]
            app.user_middleware = [
                Middleware(
                    GeneratedMiddleware,
                    marker=marker,
                    switch=bool((marker ^ position ^ invocation_index) & 1),
                )
                for position, marker in enumerate(markers)
            ]
            total_user_middleware += len(app.user_middleware)

            extra_handler_count = (
                sum(marker % 13 for marker in markers[:7]) + invocation_index
            ) % 19
            generated_handlers = {
                ord("K") * len("handlers")
                + position * 2
                + (invocation_index % 2): generated_handler
                for position in range(extra_handler_count)
            }
            app.exception_handlers = {**default_handlers, **generated_handlers}
            if sum(markers) % 3 == 0:
                app.exception_handlers[Exception] = generated_handler

            stack = app.build_middleware_stack()
            current = stack
            observed_layers = 0
            while current is not app.router:
                self.assertTrue(callable(current))
                current = current.app
                observed_layers += 1
            self.assertEqual(
                observed_layers - len(app.user_middleware),
                len(default_handlers),
            )

        self.assertEqual(GeneratedMiddleware.constructed, total_user_middleware)
        self.assertNotEqual(GeneratedMiddleware.fingerprint, 0)
