import random
import unittest
from functools import partial

from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_flat_params


class TestUsesScopesCallOrder(unittest.TestCase):
    def test_seeded_dependency_fanout(self) -> None:
        rng = random.Random(73129)

        def make_callable(token: int):
            def dependency() -> int:
                return (token * token + 17) % 101

            wrapped = dependency
            for _ in range(1 + rng.randrange(4)):
                wrapped = partial(wrapped)
            return wrapped

        width = 19 + sum(rng.randrange(3) for _ in range(11))
        dependencies = [
            Dependant(call=make_callable(token), name=f"dep_{token}")
            for token in range(width)
        ]
        scope_token = "".join(chr(97 + rng.randrange(26)) for _ in range(9))
        dependencies.append(
            Dependant(
                call=make_callable(width),
                name=f"dep_{width}",
                own_oauth_scopes=[scope_token],
            )
        )
        root = Dependant(
            call=make_callable(width + 1),
            dependencies=dependencies,
            name="root",
        )

        flattened = get_flat_params(root)

        self.assertIsInstance(flattened, list)
        self.assertFalse(flattened)
        self.assertGreater(len(root.dependencies), 20)
