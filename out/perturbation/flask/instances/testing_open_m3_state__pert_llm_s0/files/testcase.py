import random
import unittest

from flask import Flask
from flask import request
from flask.testing import EnvironBuilder
from flask.testing import FlaskClient


class TestOpenProgramState(unittest.TestCase):
    def test_generated_request_forms(self):
        app = Flask(__name__)

        @app.route("/probe/<token>", methods=["GET", "POST", "PUT"])
        def probe(token):
            weighted = sum((index + 3) * ord(char) for index, char in enumerate(token))
            return {
                "method": request.method,
                "result": (weighted ^ len(request.query_string)) % 1009,
                "token_size": len(token),
            }

        state = 0xDEADBEEF
        plans = []

        for index in range(128):
            state = (state * 1664525 + 1013904223 + index * index) & 0xFFFFFFFF
            token = "".join(
                chr(97 + ((state >> shift) + index * (shift + 5)) % 26)
                for shift in range(0, 55, 2)
            )
            method = ("GET", "POST", "PUT")[(state ^ index) % 3]
            query_value = (state // 89 + index * 37) % 991
            plans.append(
                (
                    index % 4,
                    f"/probe/{token}?q={query_value:x}&s={index:x}&p={index % 9}&r={(state >> 11) & 0xFF:x}",
                    method,
                )
            )

        random.Random(state ^ len(plans)).shuffle(plans)
        client = app.test_client()
        observed = []

        with client:
            for form, path, method in plans:
                if form == 0:
                    response = FlaskClient.open(
                        client,
                        path,
                        method=method,
                        headers={"X-Form": str(form), "X-Method": method},
                    )
                else:
                    builder = EnvironBuilder(
                        app,
                        path=path,
                        method=method,
                        headers={"X-Form": str(form), "X-Method": method},
                    )

                    try:
                        if form == 1:
                            response = FlaskClient.open(client, builder)
                        elif form == 2:
                            response = FlaskClient.open(client, builder.get_environ())
                        else:
                            response = FlaskClient.open(client, builder.get_request())
                    finally:
                        builder.close()

                self.assertEqual(response.status_code // 100, 2)
                payload = response.get_json()
                self.assertEqual(payload["method"], method)
                self.assertGreater(payload["token_size"], 3)
                observed.append(payload["result"])

        self.assertEqual(len(observed), len(plans))
        self.assertGreater(len(set(observed)), len(plans) // 2)
