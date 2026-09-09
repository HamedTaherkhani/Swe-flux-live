import importlib
import random
import types
import unittest
from unittest import mock

from click.testing import CliRunner

from instructlab import lab


class TestConfigStateTransitions(unittest.TestCase):
    def test_seeded_public_cli_profiles(self):
        suffix = "".join(chr(value) for value in (105, 110, 105, 116))
        command_module = importlib.import_module(
            "instructlab.cli.config." + suffix
        )
        rng = random.Random(sum(index**3 for index in range(17)))
        tokens = [rng.randrange(10_000, 99_999) for _ in range(10)]
        written = []
        selected_by_processors = {}

        def generated_text(token, salt):
            return "".join(
                chr(97 + ((token // (position + 3) + salt * position) % 26))
                for position in range(18)
            )

        def make_config(token, salt):
            stem = generated_text(token, salt)
            return types.SimpleNamespace(
                chat=types.SimpleNamespace(model=f"chat-{stem}"),
                serve=types.SimpleNamespace(model_path=f"serve-{stem[::-1]}"),
                evaluate=types.SimpleNamespace(
                    model=f"judge-{stem[::2]}",
                    mt_bench_branch=types.SimpleNamespace(
                        taxonomy_path=f"bench-{stem[1::2]}"
                    ),
                ),
                generate=types.SimpleNamespace(
                    taxonomy_base=f"base-{stem[2:]}",
                    taxonomy_path=f"tree-{stem[:-2]}",
                ),
            )

        sources = [make_config(token, index + 2) for index, token in enumerate(tokens)]
        chosen = [
            make_config(token ^ tokens[-index - 1], index + 23)
            for index, token in enumerate(tokens)
        ]
        source_index = {id(cfg): index for index, cfg in enumerate(sources)}

        def route_params(*args, **kwargs):
            del kwargs
            index = len(written)
            return args[4], args[5], sources[index]

        def detect_profile(**kwargs):
            index = source_index[id(kwargs["cfg"])]
            processors = [
                (
                    [
                        generated_text(tokens[index] + position**2, position + 5),
                        str((tokens[position % len(tokens)] * (position + 7)) % 997),
                    ],
                    generated_text(tokens[-position % len(tokens)], position + 31),
                )
                for position in range(19)
            ]
            selected_by_processors[id(processors)] = chosen[index]
            return make_config(tokens[index], index + 71), {"generated": processors}, True

        def choose_profile(processors):
            return selected_by_processors[id(processors)]

        def capture_config(*, cfg):
            written.append(cfg)

        runner = CliRunner()
        results = []
        with (
            mock.patch.object(lab.cfg, suffix, return_value=None),
            mock.patch.object(
                command_module, "ensure_storage_directories_exist", return_value=False
            ),
            mock.patch.object(
                command_module, "check_if_configs_exist", return_value=False
            ),
            mock.patch.object(command_module, "get_params", side_effect=route_params),
            mock.patch.object(
                command_module, "initialize_config", side_effect=detect_profile
            ),
            mock.patch.object(
                command_module,
                "prompt_user_to_choose_vendors",
                return_value="generated",
            ),
            mock.patch.object(
                command_module,
                "prompt_user_to_choose_profile",
                side_effect=choose_profile,
            ),
            mock.patch.object(command_module, "write_config", side_effect=capture_config),
            mock.patch.object(command_module.utils, "print_init_success"),
        ):
            for index, token in enumerate(tokens):
                model = generated_text(token * (index + 11), index + 43)
                taxonomy = generated_text(token + tokens[index - 1], index + 59)
                arguments = [
                    "config",
                    suffix,
                    "--interactive",
                    "--model-path",
                    f"/generated/{model}/{token % 101}",
                    "--taxonomy-base",
                    f"branch-{taxonomy[::2]}",
                    "--taxonomy-path",
                    f"/taxonomy/{taxonomy[1::2]}",
                ]
                results.append(runner.invoke(lab.ilab, arguments))

        self.assertEqual(len(written), len(tokens))
        self.assertTrue(all(result.exit_code == 0 for result in results), results)
        self.assertTrue(all(result.exception is None for result in results))
        self.assertGreater(
            sum(result.output.count("[") for result in results),
            len(tokens) * len(tokens),
        )
        self.assertTrue(all(item in chosen for item in written))
