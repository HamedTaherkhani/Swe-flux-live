import unittest

import click
from click.globals import resolve_color_default


class TestGeneratedColorResolution(unittest.TestCase):
    def test_programmatic_context_schedule(self):
        command = click.Command("generated")
        contexts = [
            click.Context(
                command,
                color=bool(((slot * slot + slot * 7 + 3) ^ (slot << 1)) & 1),
            )
            for slot in range(9)
        ]

        plans = []
        state = 73
        for index in range(56):
            state = (state * 109 + index * 47 + 31) % 1009
            selector = (state ^ (state >> 2) ^ (index * 11)) % 12
            argument = None if selector in {0, 2, 3, 7, 11} else bool(selector & 1)
            use_context = ((state + index * index) % 7) not in {0, 5}
            context_index = (state + selector * 3 + index) % len(contexts)
            plans.append((argument, use_context, context_index))

        outcomes = []
        for argument, use_context, context_index in plans:
            if use_context:
                with contexts[context_index]:
                    outcomes.append(resolve_color_default(argument))
            else:
                outcomes.append(resolve_color_default(argument))

        self.assertEqual(len(outcomes), len(plans))
        self.assertTrue(any(value is None for value in outcomes))
        self.assertTrue(any(value is True for value in outcomes))
        self.assertTrue(any(value is False for value in outcomes))
