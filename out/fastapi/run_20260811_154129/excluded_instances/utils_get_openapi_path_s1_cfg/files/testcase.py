import unittest

from fastapi import FastAPI, Query
from pydantic import Field, create_model


Payload = create_model(
    "GeneratedPayload",
    **{
        f"metric_{index}": (
            int,
            Field(
                default=index * index + 1,
                ge=index % 5,
                description=f"derived metric {index * 7 + 3}",
            ),
        )
        for index in range(18)
    },
)

Result = create_model(
    "GeneratedResult",
    **{
        f"result_{index}": (
            str,
            Field(default_factory=lambda index=index: chr(97 + index % 26) * (index + 1)),
        )
        for index in range(16)
    },
)


def build_responses():
    responses = {}
    for index in range(18):
        status = 240 + index
        response = {
            "description": f"generated branch {(index * 13 + 5) % 29}",
            "headers": {
                f"X-Metric-{index}": {
                    "schema": {"type": "integer", "minimum": index % 4}
                }
            },
        }
        if index % 3:
            response["model"] = Result
        if index % 4 == 0:
            response["content"] = {
                "application/problem+json": {
                    "example": {"code": index * index + status}
                }
            }
        responses[status] = response
    return responses


class TestGeneratedOpenAPISchema(unittest.TestCase):
    def test_schema_for_programmatic_routes(self):
        app = FastAPI(title="Generated API", docs_url=None, redoc_url=None)

        @app.get("/warmup")
        def warmup(seed: int = Query(default=7, ge=0)):
            return {"seed": seed}

        @app.post(
            "/matrix",
            response_model=Result,
            responses=build_responses(),
            tags=["generated", "matrix"],
            deprecated=True,
            openapi_extra={"x-derived": {"parity": [index % 2 for index in range(18)]}},
        )
        def matrix(payload: Payload, scale: int = Query(default=11, gt=1)):
            return {
                f"result_{index}": str(
                    (getattr(payload, f"metric_{index}", index) * scale + index) % 997
                )
                for index in range(16)
            }

        @app.get("/cooldown", include_in_schema=False)
        def cooldown():
            return {"done": True}

        schema = app.openapi()

        self.assertIn("/matrix", schema["paths"])
        self.assertIn("/warmup", schema["paths"])
        self.assertNotIn("/cooldown", schema["paths"])
        self.assertGreater(len(schema.get("components", {}).get("schemas", {})), 2)
