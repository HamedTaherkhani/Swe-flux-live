import random
import unittest
from typing import Annotated

from fastapi import FastAPI, Query
from pydantic import create_model


def make_endpoint(model_type, route_index):
    def generated_endpoint(filters):
        return {
            "route": route_index,
            "checksum": sum(value for value in filters.model_dump().values()),
        }

    generated_endpoint.__name__ = f"generated_endpoint_{route_index}"
    generated_endpoint.__annotations__ = {
        "filters": Annotated[model_type, Query()],
    }
    return generated_endpoint


class TestGeneratedParameterLoops(unittest.TestCase):
    def test_openapi_for_variable_width_query_models(self):
        app = FastAPI(
            title="Variable Width API",
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )
        rng = random.Random(314159)
        field_counts = rng.sample(range(24, 36), 6)

        for route_index, field_count in enumerate(field_counts):
            model_type = create_model(
                f"QueryBundle{route_index}",
                **{
                    f"metric_{field_index}_{(field_index * field_index + route_index) % 17}": (
                        int,
                        (field_index * 11 + route_index * 7) % 101,
                    )
                    for field_index in range(field_count)
                },
            )
            app.add_api_route(
                f"/generated/{route_index}",
                make_endpoint(model_type, route_index),
                methods=["GET"],
            )

        schema = app.openapi()

        self.assertEqual(len(schema["paths"]), len(field_counts))
        observed_parameters = [
            operation["parameters"]
            for path_item in schema["paths"].values()
            for operation in path_item.values()
        ]
        self.assertTrue(all(observed_parameters))
        self.assertGreater(
            sum(len(parameters) for parameters in observed_parameters),
            len(field_counts) * len(field_counts),
        )
