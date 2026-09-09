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
        score = sum((index + 3) * ord(char) for index, char in enumerate(request.path))
        if score % 5 in {0, 2}:
            return None
        return SecureCookieSession({"score": score % 97})


class TestContextPushGraph(unittest.TestCase):
    def test_seeded_context_matrix(self):
        app = Flask(__name__)
        session_interface = AlternatingSessionInterface()
        app.session_interface = session_interface

        for slot in range(11):
            endpoint = f"entry_{slot}"
            app.add_url_rule(
                f"/entry/{slot}/<int:value>",
                endpoint,
                lambda value, slot=slot: f"{slot}:{value}",
            )

        rng = random.Random(731_946)
        seeds = [rng.getrandbits(19) ^ (index * 8_191) for index in range(29)]
        request_contexts = 0
        total_pushes = 0

        for index, seed in enumerate(seeds):
            if index % 7 == 0:
                ctx = app.app_context()
            else:
                request_contexts += 1
                slot = (seed ^ (seed >> 5) ^ index) % 11
                value = (seed * (index + 13) + seeds[index - 1]) % 10_003
                selector = (seed + index * index) % 4
                if selector == 0:
                    path = f"/entry/{slot}/{value}"
                elif selector == 1:
                    path = f"/entry/{(slot + 6) % 11}/{value}/extra"
                elif selector == 2:
                    path = f"/entry/{slot}/v{value}"
                else:
                    path = f"/missing/{slot ^ (value % 17)}"
                ctx = app.test_request_context(path, method=("POST" if seed & 1 else "GET"))

            push_count = 1 + ((seed >> (index % 9)) % 3)
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
