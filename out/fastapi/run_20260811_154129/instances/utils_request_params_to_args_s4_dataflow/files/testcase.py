import asyncio
import inspect
import random
import unittest
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, Query
from pydantic import ConfigDict, create_model


class TestRequestParameterDataFlow(unittest.TestCase):
    def test_generated_query_header_and_dependency_inputs(self) -> None:
        rng = random.Random(24681357)
        field_count = 21

        query_fields = {
            f"query_slot_{index}": (
                list[int] if index % 5 == 0 else int,
                ...,
            )
            for index in range(field_count)
        }
        header_fields = {
            f"header_slot_{index}": (
                list[str] if index % 4 == 0 else str,
                ...,
            )
            for index in range(field_count)
        }
        QueryBundle = create_model(
            "GeneratedQueryBundle",
            __config__=ConfigDict(extra="allow"),
            **query_fields,
        )
        HeaderBundle = create_model(
            "GeneratedHeaderBundle",
            __config__=ConfigDict(extra="allow"),
            **header_fields,
        )

        def generated_dependency(**values: object) -> int:
            return len(values)

        dependency_parameters = []
        for index in range(field_count):
            annotation = list[int] if index % 6 == 0 else int
            dependency_parameters.append(
                inspect.Parameter(
                    f"dependency_slot_{index}",
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=Annotated[
                        annotation,
                        Query(alias=f"generated-key-{index}"),
                    ],
                )
            )
        generated_dependency.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
            dependency_parameters
        )

        app = FastAPI()

        @app.get("/aggregate")
        async def aggregate(
            query_bundle: Annotated[QueryBundle, Query()],
            header_bundle: Annotated[HeaderBundle, Header()],
        ) -> dict[str, int]:
            return {
                "query_size": len(query_bundle.model_fields_set),
                "header_size": len(header_bundle.model_fields_set),
            }

        @app.get("/individual")
        async def individual(
            dependency_size: Annotated[int, Depends(generated_dependency)],
        ) -> dict[str, int]:
            return {"dependency_size": dependency_size}

        query_items: list[tuple[str, str]] = []
        for index in range(field_count):
            repeats = 3 if index % 5 == 0 else 1
            for repetition in range(repeats):
                number = rng.randrange(1000, 9000) + index * 17 + repetition
                query_items.append((f"query_slot_{index}", str(number)))
        for index in range(field_count // 2):
            repetitions = 2 if index % 3 == 0 else 1
            for repetition in range(repetitions):
                query_items.append(
                    (
                        f"query_extra_{index}",
                        f"extra-{rng.randrange(10000, 99999)}-{repetition}",
                    )
                )

        header_items: list[tuple[str, str]] = []
        for index in range(field_count):
            repeats = 2 if index % 4 == 0 else 1
            for repetition in range(repeats):
                header_items.append(
                    (
                        f"header-slot-{index}",
                        f"h-{rng.randrange(100000, 999999)}-{repetition}",
                    )
                )
        for index in range(field_count // 2):
            header_items.append(
                (
                    f"x-generated-extra-{index}",
                    f"hx-{rng.randrange(10000, 99999)}",
                )
            )

        async def make_requests() -> tuple[httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://generated.test",
            ) as client:
                aggregate_result = await client.get(
                    "/aggregate",
                    params=query_items,
                    headers=header_items,
                )

                dependency_items: list[tuple[str, str]] = []
                for index in range(field_count):
                    if index % 7 == 0:
                        continue
                    repeats = 2 if index % 6 == 0 else 1
                    for repetition in range(repeats):
                        generated = rng.randrange(2000, 8000) + repetition
                        text = (
                            "not-an-integer" if index % 8 == 0 else str(generated)
                        )
                        dependency_items.append(
                            (f"generated-key-{index}", text)
                        )

                individual_result = await client.get(
                    "/individual",
                    params=dependency_items,
                )
            return aggregate_result, individual_result

        aggregate_response, individual_response = asyncio.run(make_requests())
        self.assertEqual(aggregate_response.status_code // 100, 2)
        self.assertEqual(
            set(aggregate_response.json()),
            {"query_size", "header_size"},
        )

        self.assertEqual(individual_response.status_code // 100, 4)
        self.assertIsInstance(individual_response.json().get("detail"), list)
