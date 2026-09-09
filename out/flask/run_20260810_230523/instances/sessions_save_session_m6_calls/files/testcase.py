import random
import unittest

from flask import Flask
from flask.sessions import SecureCookieSession
from flask.sessions import SecureCookieSessionInterface
from werkzeug.wrappers import Response


class TestSecureCookieSaveSessionCalls(unittest.TestCase):
    def test_generated_session_matrix(self) -> None:
        rng = random.Random(0x5E5510)
        app = Flask(__name__)
        app.secret_key = "".join(
            chr(ord("a") + rng.randrange(26)) for _ in range(48)
        )
        interface = SecureCookieSessionInterface()
        observations = []

        for index in range(37):
            token = rng.randrange(10**7, 10**9)
            app.config.update(
                SESSION_COOKIE_NAME=f"s_{(token ^ index) % 1543:x}",
                SESSION_COOKIE_DOMAIN=(
                    f"d{token % 997}.example.test" if token % 4 == 0 else None
                ),
                SESSION_COOKIE_PATH=(
                    f"/p/{(token // 7) % 881}" if token % 5 else None
                ),
                APPLICATION_ROOT=f"/a/{(token // 11) % 877}",
                SESSION_COOKIE_SECURE=bool(token & 1),
                SESSION_COOKIE_PARTITIONED=(token + index) % 7 == 0,
                SESSION_COOKIE_SAMESITE=(
                    ("Lax", "Strict", None)[(token + index) % 3]
                ),
                SESSION_COOKIE_HTTPONLY=(token + index) % 6 != 0,
                SESSION_REFRESH_EACH_REQUEST=(token ^ index) % 3 == 0,
            )

            payload_size = (token + index * 13) % 23
            payload = {
                f"k{item}_{(token >> (item % 9)) % 257}": (
                    token * (item + 3) + index
                )
                % 100_003
                for item in range(payload_size)
            }
            session = SecureCookieSession(payload)
            session.accessed = (token + index) % 4 != 0
            session.modified = (token ^ (index * 17)) % 5 in {0, 1}

            if payload and (token + index) % 3 == 0:
                dict.__setitem__(session, "_permanent", True)

            response = Response()
            SecureCookieSessionInterface.save_session(
                interface, app, session, response
            )
            observations.append(
                (
                    bool(payload),
                    session.modified,
                    session.permanent,
                    "Set-Cookie" in response.headers,
                    "Cookie" in response.vary,
                )
            )

        self.assertEqual(len(observations), 37)
        self.assertTrue(any(not row[0] for row in observations))
        self.assertTrue(any(row[3] for row in observations))
        self.assertTrue(any(row[0] and not row[3] for row in observations))
        self.assertGreater(sum(row[4] for row in observations), 15)
