import functools
import random
import unittest

from flask.views import View


def make_decorator(salt: int):
    def decorator(view):
        if salt % 4:
            view.decorator_checksum = (
                getattr(view, "decorator_checksum", 0) * 33 + salt
            )
            return view

        @functools.wraps(view)
        def wrapped(**kwargs):
            return view(**kwargs)

        wrapped.decorator_checksum = salt ^ getattr(
            view, "decorator_checksum", 0
        )
        return wrapped

    return decorator


class TestViewAsViewDataFlow(unittest.TestCase):
    def test_generated_view_classes_and_decorators(self) -> None:
        rng = random.Random(0xA51E7)
        created = []
        expected_classes = []
        job_count = sum((value % 3) + 1 for value in range(18))

        for index in range(job_count):
            token = rng.getrandbits(31) ^ (index * 2654435761)
            decorator_count = (
                0 if index % 12 in {0, 1} else 15 + rng.randrange(9)
            )
            decorators = [
                make_decorator(
                    token ^ (position * position + 17 * position + index)
                )
                for position in range(decorator_count)
            ]

            def __init__(self, *args, **kwargs):
                self.payload = (args, tuple(sorted(kwargs.items())))

            def dispatch_request(self, **kwargs):
                return (self.payload, tuple(sorted(kwargs.items())))

            view_class = type(
                f"GeneratedView_{index}_{token:x}",
                (View,),
                {
                    "__init__": __init__,
                    "dispatch_request": dispatch_request,
                    "init_every_request": index % 2 == 0,
                    "decorators": decorators,
                    "methods": {
                        method
                        for bit, method in enumerate(("GET", "POST", "PATCH"))
                        if token & (1 << bit)
                    }
                    or {"GET"},
                    "provide_automatic_options": bool(token & 32),
                },
            )
            positional = tuple(
                (token >> shift) & 0xFF for shift in range(0, 24, 8)
            )
            keyword = {
                f"slot_{slot}": (token * (slot + 3)) % 10007
                for slot in range(2 + index % 4)
            }
            name = f"generated_{index}_{token ^ sum(positional):x}"
            generated_view = View.as_view.__func__(
                view_class, name, *positional, **keyword
            )
            created.append(generated_view)
            expected_classes.append(view_class)

        self.assertEqual(len(created), job_count)
        self.assertTrue(
            all(
                view.view_class is expected
                for view, expected in zip(created, expected_classes)
            )
        )
        self.assertTrue(all(view.__name__.startswith("generated_") for view in created))
        self.assertGreater(
            len({view.decorator_checksum for view in created if hasattr(view, "decorator_checksum")}),
            job_count // 2,
        )
