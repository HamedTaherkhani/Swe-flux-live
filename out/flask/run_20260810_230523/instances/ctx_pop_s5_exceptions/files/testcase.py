import builtins
import random
import unittest

from flask import Flask
from flask import request
from werkzeug.datastructures import MultiDict


class _FailingResource:
    def __init__(self, error_kind):
        self.error_kind = error_kind
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        raise self.error_kind("resource shutdown rejected")


class TestAppContextPopExceptions(unittest.TestCase):
    def test_seeded_request_resource_failures(self):
        app = Flask(__name__)
        candidates = []

        for value in vars(builtins).values():
            if (
                isinstance(value, type)
                and issubclass(value, Exception)
                and value.__module__ == "builtins"
                and value.__name__.endswith("Error")
            ):
                try:
                    value("constructor probe")
                except BaseException:
                    continue
                candidates.append(value)

        candidates.sort(key=lambda value: value.__name__)
        selected = random.Random(731_429).sample(candidates, 18)
        resources = [_FailingResource(kind) for kind in selected]
        suppressed_exits = 0

        for index, resource in enumerate(resources):
            try:
                with app.test_request_context(f"/resource/{index * index + index}"):
                    concrete_request = request._get_current_object()
                    concrete_request.__dict__["files"] = MultiDict(
                        [(f"upload-{index % 7}", resource)]
                    )
            except BaseException:
                suppressed_exits += 1

        self.assertEqual(suppressed_exits, len(resources))
        self.assertTrue(all(resource.close_calls == 1 for resource in resources))

