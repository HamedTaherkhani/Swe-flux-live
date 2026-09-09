import unittest

from flask import Flask
from flask.sessions import SecureCookieSession
from flask.sessions import SecureCookieSessionInterface
from werkzeug.test import EnvironBuilder


class TestOpenSessionCallGraph(unittest.TestCase):
    def test_seeded_cookie_matrix(self):
        interface = SecureCookieSessionInterface()
        keyed_apps = []

        state = 0x6D2B79F5
        for app_index in range(4):
            app = Flask(f"session-probe-{app_index}")
            secret_chars = []
            for position in range(29):
                state = (state * 1664525 + 1013904223 + position + app_index) & 0xFFFFFFFF
                secret_chars.append(chr(33 + ((state >> 11) % 90)))
            app.secret_key = "".join(secret_chars)
            app.config["SECRET_KEY_FALLBACKS"] = [
                "".join(reversed(secret_chars[shift::3]))
                for shift in range(3)
            ]
            keyed_apps.append(app)

        unsigned_app = Flask("session-probe-unsigned")
        cookie_bank = []
        for payload_index in range(19):
            app = keyed_apps[(state ^ payload_index) % len(keyed_apps)]
            payload_values = []
            for offset in range(7):
                state = (
                    state * 22695477
                    + 1
                    + payload_index * 131
                    + offset * offset
                ) & 0xFFFFFFFF
                payload_values.append((state >> (offset % 13)) % 10007)
            payload = {
                "bucket": payload_index % 5,
                "checksum": sum(
                    (position + 1) * value
                    for position, value in enumerate(payload_values)
                )
                % 65521,
                "values": payload_values,
            }
            serializer = interface.get_signing_serializer(app)
            self.assertIsNotNone(serializer)
            cookie_bank.append((app, serializer.dumps(payload), payload))

        plans = []
        for plan_index in range(43):
            state = (state * 1103515245 + 12345 + plan_index**3) & 0x7FFFFFFF
            branch = ((state >> 7) ^ (plan_index * 17)) % 7
            source_index = (state + plan_index * 11) % len(cookie_bank)
            source_app, signed_value, payload = cookie_bank[source_index]

            if branch == 0:
                plans.append((unsigned_app, None, None))
            elif branch in (1, 2):
                plans.append((source_app, None, None))
            elif branch in (3, 4):
                plans.append((source_app, signed_value, payload))
            else:
                pivot = 1 + (state % (len(signed_value) - 2))
                replacement = chr(65 + ((ord(signed_value[pivot]) + plan_index) % 26))
                damaged = signed_value[:pivot] + replacement + signed_value[pivot + 1 :]
                plans.append((source_app, damaged, None))

        observed = []
        loaded_payloads = 0
        for app, cookie_value, expected_payload in plans:
            headers = {}
            if cookie_value is not None:
                headers["Cookie"] = (
                    f"{app.config['SESSION_COOKIE_NAME']}={cookie_value}"
                )

            builder = EnvironBuilder(path="/session-probe", headers=headers)
            try:
                request = app.request_class(builder.get_environ())
                opened = interface.open_session(app, request)
            finally:
                builder.close()

            if app.secret_key is None:
                self.assertIsNone(opened)
            else:
                self.assertIsInstance(opened, SecureCookieSession)
                self.assertFalse(opened.modified)
                if expected_payload is not None and dict(opened) == expected_payload:
                    loaded_payloads += 1
            observed.append(opened)

        self.assertEqual(len(observed), len(plans))
        self.assertGreater(loaded_payloads, len(cookie_bank) // 4)
        self.assertGreater(sum(item is None for item in observed), 0)
