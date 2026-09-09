import inspect
import random
import unittest

from flask import Flask
from flask.sansio.app import App
from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import BadRequestKeyError
from werkzeug.exceptions import NotFound


class ReentrantConfig(dict):
    def __init__(self, app, nested):
        super().__init__()
        self.app = app
        self.nested = iter(nested)
        self.armed = False
        self.nested_results = []

    @staticmethod
    def _current_exception():
        frame = inspect.currentframe()
        while frame is not None:
            candidate = frame.f_locals.get("e")
            if frame.f_code is App.trap_http_exception.__code__:
                return candidate
            frame = frame.f_back
        raise AssertionError("target frame not found")

    def __getitem__(self, key):
        error = self._current_exception()
        marker = error.qa_marker

        if key == "TRAP_HTTP_EXCEPTIONS":
            if self.armed:
                try:
                    nested_error = next(self.nested)
                except StopIteration:
                    pass
                else:
                    self.nested_results.append(
                        App.trap_http_exception(self.app, nested_error)
                    )
            return ((marker * marker + marker * 5 + 7) % 17) < 3

        if key == "TRAP_BAD_REQUEST_ERRORS":
            selector = (marker * 11 + marker // 3) % 5
            return None if selector < 2 else selector == 4

        if key == "DEBUG":
            return ((marker ^ (marker >> 2)) & 1) == 1

        raise KeyError(key)


def make_error(marker):
    selector = (marker * marker + marker * 7 + 13) % 6
    if selector < 2:
        error = BadRequestKeyError(f"field-{marker ** 2 + 3 * marker}")
    elif selector < 5:
        error = BadRequest()
    else:
        error = NotFound()
    error.qa_marker = marker
    return error


class TestTrapHTTPException(unittest.TestCase):
    def test_reentrant_branch_path(self):
        rng = random.Random(20260811)
        markers = [
            token ^ (position * 29 + token // 7)
            for position, token in enumerate(rng.randrange(40, 900) for _ in range(71))
        ]
        errors = [make_error(marker) for marker in markers]

        app = Flask("qa-runtime")
        config = ReentrantConfig(app, errors[18:53])
        app.config = config

        outcomes = [
            App.trap_http_exception(app, error)
            for error in errors[:18]
        ]
        config.armed = True
        outcomes.append(App.trap_http_exception(app, errors[53]))
        config.armed = False
        outcomes.extend(
            App.trap_http_exception(app, error)
            for error in errors[54:]
        )

        all_results = outcomes + config.nested_results
        self.assertEqual(len(all_results), len(errors))
        self.assertTrue(any(all_results))
        self.assertTrue(any(not value for value in all_results))
