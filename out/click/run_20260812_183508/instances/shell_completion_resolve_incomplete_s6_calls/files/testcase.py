from __future__ import annotations

import unittest

import click
from click.shell_completion import CompletionItem, ShellComplete


class ScriptedComplete(ShellComplete):
    name = "scripted"
    source_template = ""

    def __init__(
        self,
        cli: click.Command,
        scenarios: list[tuple[list[str], str]],
    ) -> None:
        super().__init__(cli, {}, "forge", "_FORGE_COMPLETE")
        self._scenarios = scenarios
        self._cursor = 0

    def get_completion_args(self) -> tuple[list[str], str]:
        args, incomplete = self._scenarios[self._cursor]
        self._cursor += 1
        return args.copy(), incomplete

    def format_completion(self, item: CompletionItem[str]) -> str:
        return f"{item.type}:{item.value}"


class ShellCompletionResolveIncompleteCallsTest(unittest.TestCase):
    def test_scripted_completion_workload(self) -> None:
        params: list[click.Parameter] = []

        for index in range(18):
            option_name = f"--field-{(index * 17 + 5) % 97:02d}"

            if index % 4 == 0:
                params.append(click.Option([option_name], is_flag=True))
            elif index % 4 == 1:
                params.append(click.Option([option_name], count=True))
            else:
                params.append(click.Option([option_name], type=str))

        params.extend(click.Argument([f"slot_{index}"]) for index in range(6))
        command = click.Command("forge", params=params)

        value_options = [
            param
            for param in params
            if isinstance(param, click.Option) and not param.is_flag and not param.count
        ]
        flag_options = [
            param
            for param in params
            if isinstance(param, click.Option) and (param.is_flag or param.count)
        ]
        positional = [
            f"payload-{(index * index + 3 * index + 11) % 101:03d}"
            for index in range(6)
        ]

        base_args: list[str] = []

        for index, param in enumerate(value_options):
            base_args.extend([param.opts[0], f"value-{(index * 29 + 7) % 89:02d}"])

        for index, param in enumerate(flag_options):
            if index % 3 == 0:
                base_args.append(param.opts[0])

        scenarios: list[tuple[list[str], str]] = []

        for ordinal in range(18):
            mode = ordinal % 6
            args = [*base_args, *positional]

            if mode == 0:
                incomplete = f"--field-{(ordinal * 13 + 9) % 97:02d}"
            elif mode == 1:
                incomplete = "="
            elif mode == 2:
                args = [*base_args, value_options[ordinal % len(value_options)].opts[0]]
                incomplete = f"fragment-{(ordinal * 7 + 1) % 43:02d}"
            elif mode == 3:
                incomplete = (
                    f"{value_options[(ordinal + 2) % len(value_options)].opts[0]}"
                    f"=joined-{(ordinal * 19 + 4) % 71:02d}"
                )
            elif mode == 4:
                args = [*base_args, "--", *positional]
                incomplete = f"tail-{(ordinal * 23 + 6) % 67:02d}"
            else:
                incomplete = ""

            scenarios.append((args, incomplete))

        completer = ScriptedComplete(command, scenarios)
        outputs = [completer.complete() for _ in scenarios]

        self.assertEqual(len(outputs), len(scenarios))
        self.assertTrue(all(isinstance(output, str) for output in outputs))
        self.assertEqual(completer._cursor, len(scenarios))
