import random
import unittest

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


class TestPopulateApiRouteStateLoop(unittest.TestCase):
    def test_included_route_response_merge(self) -> None:
        rng = random.Random(8675309)
        status_pool = list(range(400, 480))
        include_codes = rng.sample(status_pool, 17)
        route_codes = rng.sample(status_pool, 19)

        def response_map(codes: list[int], salt: int) -> dict[int, dict[str, object]]:
            result: dict[int, dict[str, object]] = {}
            for position, code in enumerate(codes):
                entry: dict[str, object] = {
                    "description": f"generated-{(code * salt + position) % 97}"
                }
                selector = (code + position * salt) % 4
                if selector == 0:
                    entry["model"] = int
                elif selector == 1:
                    entry["model"] = list[str]
                result[code] = entry
            return result

        child = APIRouter()

        @child.get(
            "/payload",
            response_model=None,
            responses=response_map(route_codes, 7),
        )
        def payload() -> dict[str, bool]:
            return {"ok": True}

        app = FastAPI()
        app.include_router(
            child,
            prefix="/generated",
            responses=response_map(include_codes, 11),
        )

        included_branch = app.router.routes[-1]
        contexts = list(included_branch.effective_route_contexts())
        self.assertEqual(len(contexts), len(child.routes))

        response = TestClient(app).get("/generated/payload")
        self.assertEqual(response.status_code // 100, 2)
        self.assertEqual(set(response.json()), {"ok"})
        self.assertIs(response.json()["ok"], True)
