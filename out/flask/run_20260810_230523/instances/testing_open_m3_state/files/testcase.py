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

        state = 0x5A17
        plans = []

        for index in range(28):
            state = (state * 1103515245 + 12345 + index * index) & 0x7FFFFFFF
            token = "".join(
                chr(97 + ((state >> shift) + index * (shift + 5)) % 26)
                for shift in range(0, 25, 5)
            )
            method = ("GET", "POST", "PUT")[(state ^ index) % 3]
            query_value = (state // 97 + index * 43) % 997
            plans.append((index % 4, f"/probe/{token}?q={query_value:x}", method))

        random.Random(state ^ len(plans)).shuffle(plans)
        client = app.test_client()
        observed = []

        with client:
            for form, path, method in plans:
                if form == 0:
                    response = FlaskClient.open(
                        client, path, method=method, headers={"X-Form": str(form)}
                    )
                else:
                    builder = EnvironBuilder(
                        app, path=path, method=method, headers={"X-Form": str(form)}
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
