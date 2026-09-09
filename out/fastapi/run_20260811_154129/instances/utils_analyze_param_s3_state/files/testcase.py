import inspect
import unittest
from typing import Annotated

from fastapi import Cookie, FastAPI, Header, Query


class TestGeneratedRoute(unittest.TestCase):
    def test_generated_signature_registration(self) -> None:
        app = FastAPI()

        async def generated_endpoint(**values):
            return {"received": len(values)}

        parameters = []
        for index in range(27):
            name_code = (index * 37 + index * index + 11) % 997
            parameter_name = f"field_{name_code:03d}_{index:02d}"
            selector = (index * 7 + name_code) % 5
            magnitude = sum((index + offset) ** 2 for offset in range(1, 5))

            if selector == 0:
                annotation = Annotated[
                    int,
                    Query(
                        gt=(magnitude % 13) - 7,
                        alias=f"query-{(name_code * 3 + magnitude) % 1009}",
                    ),
                ]
                default = magnitude // 3
            elif selector == 1:
                annotation = str
                default = "".join(
                    chr(97 + ((name_code + index * step) % 26))
                    for step in range(5)
                )
            elif selector == 2:
                annotation = list[int]
                default = [
                    (name_code * factor + magnitude) % 101
                    for factor in range(1, 5)
                ]
            elif selector == 3:
                annotation = int
                default = Header(
                    default=magnitude - name_code,
                    alias=f"header-{(magnitude * 5 + name_code) % 1013}",
                )
            else:
                annotation = Annotated[
                    str,
                    Cookie(
                        alias=f"cookie-{(name_code + magnitude * 7) % 1021}"
                    ),
                ]
                default = f"token-{(name_code ^ magnitude):x}"

            parameters.append(
                inspect.Parameter(
                    parameter_name,
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    annotation=annotation,
                    default=default,
                )
            )

        generated_endpoint.__signature__ = inspect.Signature(parameters)
        app.add_api_route("/generated", generated_endpoint, methods=["GET"])

        generated_route = app.routes[-1]
        self.assertEqual(generated_route.path, "/generated")
        self.assertGreater(
            len(generated_route.dependant.query_params)
            + len(generated_route.dependant.header_params)
            + len(generated_route.dependant.cookie_params)
            + len(generated_route.dependant.body_params),
            20,
        )
