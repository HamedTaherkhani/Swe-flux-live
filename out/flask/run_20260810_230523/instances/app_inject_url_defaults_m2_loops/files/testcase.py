import random
import string
import unittest

from flask import Flask


class TestInjectUrlDefaultsLoopDynamics(unittest.TestCase):
    def test_generated_nested_blueprint_defaults(self):
        rng = random.Random(904_381)
        app = Flask(__name__)

        def word(width):
            return "".join(rng.choice(string.ascii_lowercase) for _ in range(width))

        @app.url_defaults
        def application_default(endpoint, values):
            values["hits"] = values.get("hits", 0) + 1
            values["digest"] = (
                (values.get("digest", 2_166_136_261) ^ len(endpoint)) * 16_777_619
            ) & 0xFFFFFFFF

        depths = [
            1
            + (
                index * index
                + rng.randrange(len(string.ascii_lowercase))
                + (index ^ rng.randrange(len(string.digits)))
            )
            % len(string.hexdigits)
            for index in range(
                len(string.ascii_lowercase) + len(string.digits)
            )
        ]
        depths.extend((0, len(string.ascii_lowercase)))
        rng.shuffle(depths)

        scenarios = []
        for call_index, depth in enumerate(depths):
            segments = [
                f"bp{call_index:x}_{level:x}_{word(4 + (level % 4))}"
                for level in range(depth)
            ]
            endpoint = ".".join((*segments, "view_" + word(6)))

            for level in range(depth):
                prefix = ".".join(segments[: level + 1])
                score = sum(
                    (position + 3) * ord(character)
                    for position, character in enumerate(prefix)
                )
                if score % 4:
                    callback_count = 1 + score % 7

                    for callback_index in range(callback_count):
                        salt = (
                            score * (callback_index + 5)
                            + level * level
                            + call_index
                        ) & 0xFFFFFFFF

                        def blueprint_default(
                            current_endpoint,
                            values,
                            *,
                            callback_salt=salt,
                        ):
                            values["hits"] = values.get("hits", 0) + 1
                            values["digest"] = (
                                (
                                    values.get("digest", 2_166_136_261)
                                    ^ callback_salt
                                )
                                * 16_777_619
                                + len(current_endpoint)
                            ) & 0xFFFFFFFF

                        app.url_default_functions[prefix].append(blueprint_default)

            scenarios.append(endpoint)

        observations = []
        for endpoint in scenarios:
            values = {}
            result = app.inject_url_defaults(endpoint, values)
            observations.append((result, values))

        self.assertTrue(all(result is None for result, _ in observations))
        self.assertTrue(all(values["hits"] > 0 for _, values in observations))
        self.assertGreater(len({values["hits"] for _, values in observations}), 5)
        self.assertTrue(
            all(isinstance(values["digest"], int) for _, values in observations)
        )
