import unittest
from unittest import mock

from click.exceptions import UsageError
from click.termui import prompt


class TestPromptLoopBehavior(unittest.TestCase):
    def test_generated_retries_and_confirmations(self):
        seed = 0xA53
        state = seed
        checksum = 0
        gate = len(format(seed**3, "b")) // 2
        responses = []
        rejected_values = set()
        final_value = None
        attempt = 0

        while final_value is None:
            attempt += 1
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            checksum = (checksum + (state ^ (attempt * 97))) % 65521
            candidate = f"{state:x}:{attempt:x}:{checksum:x}"

            responses.extend("" for _ in range((state >> 5) % 4))
            responses.append(candidate)

            accepted = (state ^ (attempt * 17) ^ checksum) % 5 != 0
            if not accepted:
                rejected_values.add(candidate)
                continue

            responses.extend("" for _ in range((state >> 11) % 3))
            succeeds = (
                attempt > gate
                and (state + checksum + attempt * attempt) % 11 == 0
            )
            if succeeds:
                responses.append(candidate)
                final_value = candidate
            else:
                responses.append(f"{candidate}:{(state ^ checksum) & 0xFF:x}")

        def convert_candidate(value):
            if value in rejected_values:
                raise UsageError(f"generated token rejected: {value}")
            return sum(
                (position + 3) * ord(character)
                for position, character in enumerate(value)
            )

        with mock.patch(
            "click.termui.visible_prompt_func", side_effect=responses
        ) as input_mock:
            result = prompt(
                "Generated access token",
                value_proc=convert_candidate,
                confirmation_prompt="Verify generated token",
                show_default=False,
            )

        self.assertEqual(result, convert_candidate(final_value))
        self.assertEqual(input_mock.call_count, len(responses))
