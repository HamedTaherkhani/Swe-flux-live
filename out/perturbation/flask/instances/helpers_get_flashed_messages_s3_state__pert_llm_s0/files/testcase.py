import random
import unittest

from flask import Flask
from flask import session
from flask.helpers import get_flashed_messages


class TestComputedFlashFiltering(unittest.TestCase):
    def test_tracks_seeded_filter_matrix(self) -> None:
        rng = random.Random(2_913_557)
        app = Flask(__name__)
        app.secret_key = "benchmark-flash-matrix-v2-heterogeneous"

        with app.test_request_context("/"):
            category_pool = tuple(
                f"group-{index}-{(rng.randrange(67, 1999) * (index + 13)) % 3001:04d}"
                for index in range(23)
            )
            generated_flashes = []
            rolling = rng.randrange(53_000, 241_000)

            for position in range(68):
                samples = [rng.randrange(5, 12289) for _ in range(19)]
                rolling = (
                    rolling * 113
                    + sum((offset + 11) * value for offset, value in enumerate(samples))
                    + position**4
                    + (position % 5) * 17_003
                ) % 3_000_007
                category_index = (
                    rolling
                    + samples[position % len(samples)]
                    + position * position * 5
                    + samples[(position + 3) % len(samples)]
                ) % len(category_pool)
                message_code = (
                    rolling
                    ^ sum(value << (offset % 9) for offset, value in enumerate(samples))
                    ^ (position << 11)
                ) % 3_000_007
                generated_flashes.append(
                    (
                        category_pool[category_index],
                        f"notice-{position:03d}-{message_code:07d}-x{(position * 31 + rolling) % 997:03d}",
                    )
                )

            session["_flashes"] = generated_flashes
            results = []

            for turn in range(58):
                selector = [
                    (
                        rng.randrange(59, 9049)
                        + rolling * (index + 13)
                        + turn * (turn + index + 23)
                        + (index % 4) * 1_009
                    )
                    % 12_289
                    for index in range(23)
                ]
                width = 2
                chosen_indices = [
                    (value + selector[index - 1] + turn * 7 + index * 3) % len(category_pool)
                    for index, value in enumerate(selector[:width])
                ]
                category_filter = tuple(
                    category_pool[index] for index in dict.fromkeys(chosen_indices)
                )
                result = get_flashed_messages(
                    with_categories=bool((sum(selector) + turn * 5 + rolling) % 2),
                    category_filter=category_filter,
                )
                results.append((category_filter, result))
                rolling = (rolling + sum(selector) * (turn + 29)) % 3_000_007

            self.assertEqual(len(results), 58)
            self.assertTrue(all(category_filter for category_filter, _ in results))
            self.assertTrue(all(isinstance(result, list) for _, result in results))
            self.assertTrue(any(result for _, result in results))
