import unittest

from flask import Flask
from flask.sessions import SecureCookieSession, SessionInterface


def _numbers(seed, count):
    value = seed
    result = []
    for index in range(count):
        value = (value * 1103515245 + 12345 + index * 97) & 0x7FFFFFFF
        result.append(value)
    return result


def _encode(value):
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    chars = []
    while value:
        value, remainder = divmod(value, len(alphabet))
        chars.append(alphabet[remainder])
    return "".join(reversed(chars)) or alphabet[0]


class StatefulSessionInterface(SessionInterface):
    def __init__(self):
        self.state = 0x13579BDF
        self.opened = 0
        self.saved = 0

    def open_session(self, app, request):
        path_score = sum(
            (position + 3) * ord(character)
            for position, character in enumerate(request.full_path)
        )
        self.opened += 1
        self.state = (
            ((self.state << 7) | (self.state >> 25))
            ^ path_score
            ^ (self.opened * 0x45D9F3B)
        ) & 0xFFFFFFFF

        if request.headers.get("X-Phase") == "halt":
            error_types = []
            for kind in Exception.__subclasses__():
                if kind.__module__ != "builtins":
                    continue
                try:
                    candidate = kind("probe")
                except BaseException:
                    continue
                if str(candidate) == "probe":
                    error_types.append(kind)
            error_types.sort(key=lambda kind: kind.__name__)
            error_type = error_types[
                (self.state ^ path_score ^ self.saved ^ self.opened) % len(error_types)
            ]
            checksum = (self.state * 2654435761 + path_score + self.saved) & 0xFFFFFFFF
            raise error_type(
                "session-state:"
                + _encode(checksum)
                + ":"
                + _encode(self.state ^ (self.saved << 11))
            )

        return SecureCookieSession(
            {
                "skip": ((self.state >> (self.opened % 13)) & 1) == 0,
                "value": self.state ^ path_score,
            }
        )

    def is_null_session(self, session):
        return session["skip"]

    def save_session(self, app, session, response):
        self.saved += 1
        self.state = (
            self.state
            + session["value"]
            + self.saved * 0x9E3779B1
        ) & 0xFFFFFFFF


class TestSessionTransactionExceptions(unittest.TestCase):
    def test_final_generated_request_propagates(self):
        app = Flask(__name__)
        interface = StatefulSessionInterface()
        app.session_interface = interface
        client = app.test_client()

        values = _numbers(0xCAFEBABE, 55)
        paths = [
            "/" + _encode(value ^ (index * index * 65537))
            for index, value in enumerate(values)
        ]

        for index, path in enumerate(paths):
            query = {
                "slot": _encode(values[-index - 1] ^ values[index]),
                "parity": _encode((value := values[index]) % 997),
            }
            with client.session_transaction(path, query_string=query) as session:
                session["value"] ^= (value >> (index % 17)) | index
                if index % 3 == 0:
                    session["skip"] = not session["skip"]

        caught = None
        final_path = "/" + _encode(sum(values) ^ interface.state)
        try:
            with client.session_transaction(
                final_path,
                query_string={"proof": _encode(interface.state ^ len(paths))},
                headers={"X-Phase": "halt"},
            ):
                self.fail("the transaction body must not be entered")
        except BaseException as error:
            caught = error

        self.assertIsNotNone(caught)
        self.assertGreater(len(str(caught)), len(paths) // 2)
        self.assertEqual(interface.opened, len(paths) * 2 + 1)
