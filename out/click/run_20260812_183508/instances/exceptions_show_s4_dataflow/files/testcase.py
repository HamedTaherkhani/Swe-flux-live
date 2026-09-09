import io
import unittest
from unittest import mock

import click
from click.exceptions import UsageError


class TestUsageErrorShowDataFlow(unittest.TestCase):
    def test_generated_context_and_output_matrix(self):
        state = sum((index + 3) * ord(char) for index, char in enumerate(__name__))
        cases = []

        for index in range(len(__name__) + 7):
            state = (state * 1103515245 + 12345 + index * index) & 0x7FFFFFFF
            command_name = "".join(
                chr(97 + ((state >> shift) + index) % 26)
                for shift in range(0, 25, 5)
            )
            message = "-".join(
                format((state ^ (index * factor)) & 0xFFFF, "x")
                for factor in range(3, 8)
            )

            if index % 4 == 0:
                context = None
            else:
                command = click.Command(
                    command_name,
                    add_help_option=(state + index) % 3 != 0,
                )
                context = click.Context(
                    command,
                    color=(None, False, True)[(state >> 3) % 3],
                )
            cases.append((UsageError(message, context), (state ^ index) % 3 == 0))

        sink = io.StringIO()
        with mock.patch("click.exceptions.get_text_stderr", return_value=sink):
            for error, use_default_stream in cases:
                if use_default_stream:
                    error.show()
                else:
                    error.show(file=sink)

        rendered = sink.getvalue()
        self.assertEqual(rendered.count("Error:"), len(cases))
        self.assertGreater(rendered.count("Usage:"), len(cases) // 3)
        self.assertIn("for help", rendered)
