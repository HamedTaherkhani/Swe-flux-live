import unittest

import click
from click.globals import resolve_color_default


class TestGeneratedColorResolution(unittest.TestCase):
    def test_programmatic_context_schedule(self):
        command = click.Command("generated")
        contexts = [
            click.Context(
                command,
                color=bool(((slot * slot * 3 + slot * 11 + 5) ^ (slot << 2)) & 1),
            )
            for slot in range(23)
        ]

        plans = []
        state = 157
        for index in range(200):
            state = (state * 149 + index * 61 + 37) % 3001
            selector = (state ^ (state >> 2) ^ (index * 13)) % 16
            argument = None if selector in {0, 1, 4, 7, 9, 11, 14, 15} else bool(selector & 1)
            use_context = ((state + index * index) % 13) not in {0, 3, 7, 10}
            context_index = (state + selector * 5 + index) % len(contexts)
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