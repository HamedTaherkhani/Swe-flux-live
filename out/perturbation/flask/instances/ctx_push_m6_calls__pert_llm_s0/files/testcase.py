import random
import unittest

from flask import Flask
from flask.ctx import AppContext
from flask.sessions import SecureCookieSession, SessionInterface


class AlternatingSessionInterface(SessionInterface):
    def __init__(self):
        self.opened_paths = []

    def open_session(self, app, request):
        self.opened_paths.append(request.path)
        score = sum((index + 11) * ord(char) for index, char in enumerate(request.path))
        if score % 11 in {0, 2, 4, 6, 8}:
            return None
        return SecureCookieSession({"score": score % 211})


class TestContextPushGraph(unittest.TestCase):
    def test_seeded_context_matrix(self):
        app = Flask(__name__)
        session_interface = AlternatingSessionInterface()
        app.session_interface = session_interface

        for slot in range(23):
            endpoint = f"entry_{slot}"
            app.add_url_rule(
                f"/entry/{slot}/<int:value>",
                endpoint,
                lambda value, slot=slot: f"{slot}:{value}",
            )

        rng = random.Random(5_912_847)
        seeds = [rng.getrandbits(23) ^ (index * 17_503) for index in range(79)]
        request_contexts = 0
        total_pushes = 0

        for index, seed in enumerate(seeds):
            if index % 4 == 0:
                ctx = app.app_context()
            else:
                request_contexts += 1
                slot = (seed ^ (seed >> 9) ^ index) % 23
                value = (seed * (index + 23) + seeds[index - 1]) % 24_769
                selector = (seed + index * index) % 5
                if selector == 0:
                    path = f"/entry/{slot}/{value}"
                elif selector == 1:
                    path = f"/entry/{(slot + 13) % 23}/{value}/extra"
                elif selector == 2:
                    path = f"/entry/{slot}/v{value}"
                else:
                    path = f"/missing/{slot ^ (value % 31)}"
                ctx = app.test_request_context(path, method=("POST" if seed & 7 else "GET"))

            push_count = 1 + ((seed >> (index % 17)) % 6)
            for _ in range(push_count):
                AppContext.push(ctx)
                total_pushes += 1

            self.assertIsNotNone(ctx._cv_token)
            for _ in range(push_count):
                ctx.pop()
            self.assertIsNone(ctx._cv_token)

        self.assertEqual(len(session_interface.opened_paths), request_contexts)
        self.assertGreater(total_pushes, len(seeds))
        self.assertGreater(len(set(session_interface.opened_paths)), request_contexts // 2)
