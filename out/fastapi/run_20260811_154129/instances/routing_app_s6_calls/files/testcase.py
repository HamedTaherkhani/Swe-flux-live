import asyncio
import random
import unittest

import httpx
from fastapi import FastAPI


class TestRouterDispatchCallOrder(unittest.TestCase):
    def test_seeded_route_matrix(self) -> None:
        rng = random.Random(80421)
        route_tokens = list(range(37))
        rng.shuffle(route_tokens)

        app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

        def make_endpoint(token: int):
            async def endpoint() -> dict[str, int]:
                return {"token": token, "check": (token * token + 7) % 41}

            return endpoint

        registered_paths: list[str] = []
        for position, token in enumerate(route_tokens):
            path = f"/matrix/{position:02d}-{(token * 19 + position * 7) % 97:02d}"
            registered_paths.append(path)
            app.add_api_route(path, make_endpoint(token), methods=["GET"])

        async def exercise_routes() -> None:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://route-matrix.test"
            ) as client:
                for request_index in range(18):
                    route_index = (request_index * 17 + 11) % len(registered_paths)
                    response = await client.get(registered_paths[route_index])
                    self.assertEqual(response.status_code, 200)
                    payload = response.json()
                    self.assertEqual(set(payload), {"token", "check"})
                    self.assertEqual(
                        payload["check"],
                        (payload["token"] * payload["token"] + 7) % 41,
                    )

        asyncio.run(exercise_routes())
