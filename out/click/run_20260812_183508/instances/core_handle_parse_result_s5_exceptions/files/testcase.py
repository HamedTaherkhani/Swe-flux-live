import builtins
import unittest

import click


class TestGeneratedResilientParsing(unittest.TestCase):
    def test_generated_callback_failures_are_absorbed(self):
        instances_by_name = {}

        for candidate in builtins.__dict__.values():
            if not isinstance(candidate, type):
                continue

            try:
                if not issubclass(candidate, Exception) or candidate is Exception:
                    continue
                instance = candidate(
                    f"signal-{sum(ord(char) for char in candidate.__name__) % 997}"
                )
            except Exception:
                continue

            instances_by_name.setdefault(candidate.__name__, instance)

        instances = [
            instances_by_name[name] for name in sorted(instances_by_name)
        ]
        selected = instances[: len(instances) // 2 + 4]
        self.assertGreater(len(selected), 15)

        def callback_for(instance):
            def fail_during_conversion(ctx, param, value):
                raise instance

            return fail_during_conversion

        parameters = [
            click.Option(
                [f"--field-{index:x}-{(index * index + 11) % 37:x}"],
                callback=callback_for(instance),
            )
            for index, instance in enumerate(selected)
        ]
        command = click.Command("generated-probe", params=parameters)

        with command.make_context(
            "generated-probe", [], resilient_parsing=True
        ) as context:
            self.assertEqual(
                set(context.params),
                {parameter.name for parameter in parameters},
            )
            self.assertTrue(all(value is None for value in context.params.values()))
