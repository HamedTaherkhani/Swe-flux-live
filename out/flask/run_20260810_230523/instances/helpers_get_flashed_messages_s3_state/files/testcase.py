import random
import unittest

from flask import Flask
from flask import session
from flask.helpers import get_flashed_messages


class TestComputedFlashFiltering(unittest.TestCase):
    def test_tracks_seeded_filter_matrix(self) -> None:
        rng = random.Random(604_921)
        app = Flask(__name__)
        app.secret_key = "qa-secret"

        with app.test_request_context("/"):
            category_pool = tuple(
                f"group-{index}-{(rng.randrange(101, 997) * (index + 7)) % 1009:04d}"
                for index in range(7)
            )
            generated_flashes = []
            rolling = rng.randrange(10_000, 90_000)

            for position in range(43):
                samples = [rng.randrange(17, 4093) for _ in range(8)]
                rolling = (
                    rolling * 73
                    + sum((offset + 3) * value for offset, value in enumerate(samples))
                    + position**3
                ) % 1_000_003
                category_index = (
                    rolling
                    + samples[position % len(samples)]
                    + position * position
                ) % len(category_pool)
                message_code = (
                    rolling
                    ^ sum(value << (offset % 5) for offset, value in enumerate(samples))
                ) % 1_000_003
                generated_flashes.append(
                    (
                        category_pool[category_index],
                        f"notice-{position:02d}-{message_code:06d}",
                    )
                )

            session["_flashes"] = generated_flashes
            results = []

            for turn in range(26):
                selector = [
                    (
                        rng.randrange(29, 2029)
                        + rolling * (index + 5)
                        + turn * (turn + index + 11)
                    )
                    % 4099
                    for index in range(11)
                ]
                width = 1
                chosen_indices = [
                    (value + selector[index - 1] + turn * 3) % len(category_pool)
                    for index, value in enumerate(selector[:width])
                ]
                category_filter = tuple(
                    category_pool[index] for index in dict.fromkeys(chosen_indices)
                )
                result = get_flashed_messages(
                    with_categories=bool((sum(selector) + turn) % 2),
                    category_filter=category_filter,
                )
                results.append((category_filter, result))
                rolling = (rolling + sum(selector) * (turn + 13)) % 1_000_003

            self.assertEqual(len(results), 26)
            self.assertTrue(all(category_filter for category_filter, _ in results))
            self.assertTrue(all(isinstance(result, list) for _, result in results))
            self.assertTrue(any(result for _, result in results))
