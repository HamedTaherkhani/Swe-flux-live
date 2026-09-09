import random
import unittest

from flask import Flask


class TestResponseMatrix(unittest.TestCase):
    def test_seeded_dispatch_matrix(self):
        app = Flask(__name__)
        rng = random.Random(20260811)
        modes = [rng.randrange(6) for _ in range(19)]

        @app.get("/matrix/<int:slot>")
        def response_matrix(slot):
            mode = modes[slot]
            fragments = [
                chr(97 + ((slot * 7 + offset * 11) % 26))
                for offset in range(5 + slot % 4)
            ]
            body = "".join(fragments)

            if mode == 0:
                return (
                    body.encode("utf-8"),
                    f"{207 + slot % 2} Multi-Status",
                    {"X-Matrix": f"{sum(map(ord, body)) % 997:03d}"},
                )
            if mode == 1:
                return {
                    "slot": slot,
                    "weight": sum((index + 1) * ord(ch) for index, ch in enumerate(body)),
                }
            if mode == 2:
                return (piece for piece in (body[:2], body[2:]))
            if mode == 3:
                return [slot, body, len(set(body))]
            if mode == 4:
                return body, {"X-Span": str(len(body) * (slot + 1))}
            return bytearray(body, "utf-8"), 201 + slot % 3

        with app.test_client() as client:
            responses = [client.get(f"/matrix/{slot}") for slot in range(len(modes))]

        self.assertEqual(len(responses), len(modes))
        self.assertTrue(all(response.data for response in responses))
        self.assertGreater(len({response.status_code for response in responses}), 3)
