import base64
import functools
import ipaddress
import json
import os
import random
import unittest
from unittest import mock

from werkzeug.debug import DebuggedApplication
from werkzeug.test import Client


def _descend(depth, payload, tag_every=0):
    if tag_every and depth % tag_every == 0:
        __traceback_info__ = f"lvl-{depth}"  # noqa: F841
    if depth <= 0:
        return payload()
    return _descend(depth - 1, payload, tag_every)


def _hidden_descend(depth, payload):
    if depth % 2:
        __traceback_hide__ = True  # noqa: F841
    if depth <= 0:
        return payload()
    return _hidden_descend(depth - 1, payload)


def _marker(mode, payload):
    __traceback_hide__ = mode  # noqa: F841
    return payload()


def _raiser(exc_type, text):
    def payload():
        raise exc_type(text)

    return payload


def _serve(scenario):
    def app(environ, start_response):
        scenario()
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"unreachable"]

    with mock.patch.dict(os.environ, {"WERKZEUG_DEBUG_PIN": "off"}):
        debugged = DebuggedApplication(app, evalex=False)
        return Client(debugged).get("/")


class RenderTracebackScenarios(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(7331)

    def _check(self, response, needle):
        self.assertEqual(response.status_code, 500)
        body = response.get_data(as_text=True)
        self.assertIn('class="traceback"', body)
        self.assertIn(needle, body)
        return body

    def test_plain_recursion(self):
        depth = self.rng.randint(5, 9)
        resp = _serve(lambda: _descend(depth, _raiser(ValueError, "plain")))
        self._check(resp, "ValueError")

    def test_tagged_recursion(self):
        depth = sum(self.rng.choice([2, 3, 4]) for _ in range(4))
        resp = _serve(lambda: _descend(depth, _raiser(LookupError, "tagged"), 3))
        self._check(resp, "LookupError")

    def test_json_library_frames(self):
        bad = "{" + ",".join(f'"k{i}": {i}' for i in range(4)) + ",}"

        def payload():
            return json.loads(bad)

        resp = _serve(lambda: _descend(self.rng.randint(2, 4), payload, 2))
        self._check(resp, "JSONDecodeError")

    def test_context_chain(self):
        inner = self.rng.randint(3, 6)
        outer = self.rng.randint(1, 3)

        def scenario():
            try:
                _descend(inner, _raiser(KeyError, "missing"), 4)
            except KeyError:
                _descend(outer, _raiser(TypeError, "while handling"))

        resp = _serve(scenario)
        self._check(resp, "TypeError")

    def test_cause_chain_three(self):
        sizes = [self.rng.randint(1, 4) for _ in range(3)]

        def scenario():
            try:
                try:
                    _descend(sizes[0], _raiser(OSError, "root"), 2)
                except OSError as e:
                    _descend(sizes[1], _raiser(RuntimeError, "mid"))
            except RuntimeError as e:
                raise ArithmeticError("top") from e

        resp = _serve(lambda: _descend(sizes[2], scenario))
        self._check(resp, "ArithmeticError")

    def test_suppressed_context(self):
        n = self.rng.randint(2, 5)

        def scenario():
            try:
                _descend(n, _raiser(IndexError, "hidden away"))
            except IndexError:
                raise AttributeError("fresh") from None

        resp = _serve(lambda: _descend(n + 1, scenario, 5))
        self._check(resp, "AttributeError")

    def test_syntax_error(self):
        src = "\n".join(f"v{i} = {i}" for i in range(6)) + "\nbroken = (1,\n"

        def payload():
            compile(src, "<generated>", "exec")

        resp = _serve(lambda: _descend(self.rng.randint(1, 3), payload))
        body = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 500)
        self.assertIn("syntaxerror", body)

    def test_hidden_frames(self):
        depth = self.rng.randint(6, 10)
        resp = _serve(lambda: _hidden_descend(depth, _raiser(ZeroDivisionError, "h")))
        self._check(resp, "ZeroDivisionError")

    def test_hide_before(self):
        def payload():
            return _marker("before", lambda: _descend(3, _raiser(NameError, "b"), 1))

        resp = _serve(lambda: _descend(self.rng.randint(3, 5), payload))
        self._check(resp, "NameError")

    def test_library_in_context_only(self):
        addr = ".".join(str(self.rng.randint(256, 400)) for _ in range(4))

        def scenario():
            try:
                _descend(2, lambda: ipaddress.ip_address(addr))
            except ValueError:
                _descend(2, _raiser(PermissionError, "after parse"), 1)

        resp = _serve(scenario)
        self._check(resp, "PermissionError")

    def test_only_library_frames_visible(self):
        blob = "".join(self.rng.choice("abcdef") for _ in range(5))

        def payload():
            return _marker("before_and_this", functools.partial(base64.b64decode, blob))

        resp = _serve(lambda: _descend(4, payload, 2))
        self._check(resp, "Error")

    def test_after_then_reset(self):
        def tail():
            return _marker("reset", lambda: _descend(2, _raiser(UnicodeError, "u"), 2))

        def payload():
            return _marker("after", lambda: _descend(3, tail))

        resp = _serve(lambda: _descend(self.rng.randint(1, 3), payload, 1))
        self._check(resp, "UnicodeError")

    def test_deep_cause_with_tags(self):
        depths = [self.rng.randint(2, 6) for _ in range(2)]

        def scenario():
            try:
                _descend(depths[0], _raiser(StopIteration, "first"), 3)
            except StopIteration as e:
                try:
                    _descend(depths[1], _raiser(EOFError, "second"), 2)
                except EOFError:
                    raise MemoryError("third") from e

        resp = _serve(scenario)
        self._check(resp, "MemoryError")


if __name__ == "__main__":
    unittest.main()
