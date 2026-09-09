import asyncio
import random
import unittest

from fastapi import FastAPI
from starlette.requests import Request


def generated_path(kind, index):
    token = "".join(chr(97 + ((index * 7 + offset * 11) % 26)) for offset in range(6))
    return f"/{kind}-{token}-{index:x}"


class TestApplicationSetupControlFlow(unittest.TestCase):
    def test_generated_setup_matrix_and_handlers(self):
        rng = random.Random(0x5E7A9)
        modes = [index % 5 for index in range(27)]
        rng.shuffle(modes)

        route_counts = []
        response_kinds = set()
        direct_calls = 0

        for index, mode in enumerate(modes):
            app = FastAPI(
                title=generated_path("title", index),
                openapi_url=None,
                docs_url=None,
                redoc_url=None,
                swagger_ui_oauth2_redirect_url=None,
            )

            app.openapi_url = generated_path("schema", index) if mode else None
            app.docs_url = generated_path("docs", index) if mode >= 2 else None
            app.swagger_ui_oauth2_redirect_url = (
                generated_path("oauth", index) if mode >= 3 else None
            )
            app.redoc_url = generated_path("redoc", index) if mode >= 4 else None

            server_count = 19 + ((index * 13 + mode * 7) % 17)
            servers = [
                {"url": generated_path("server", index * server_count + offset)}
                for offset in range(server_count)
            ]
            app.openapi = lambda servers=servers: {"servers": list(servers)}

            app.router.routes.clear()
            app.setup()
            direct_calls += 1
            route_counts.append(len(app.router.routes))

            root_paths = [
                generated_path("root", index * len(modes) + offset)
                for offset in range(3)
            ]
            for route_index, route in enumerate(app.router.routes):
                request = Request(
                    {
                        "type": "http",
                        "method": "GET",
                        "path": route.path,
                        "headers": [],
                        "root_path": root_paths[(route_index + mode) % len(root_paths)],
                    }
                )
                response = asyncio.run(route.endpoint(request))
                response_kinds.add(type(response).__name__)

        self.assertEqual(direct_calls, len(modes))
        self.assertGreater(len(modes), 20)
        self.assertEqual(min(route_counts), 0)
        self.assertGreaterEqual(max(route_counts), 4)
        self.assertGreaterEqual(len(set(route_counts)), 5)
        self.assertGreaterEqual(len(response_kinds), 2)
