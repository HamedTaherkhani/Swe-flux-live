import importlib
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner
from git import GitError


class TestInitParameterPaths(unittest.TestCase):
    def test_command_routes_four_taxonomy_scenarios(self):
        command_module = importlib.import_module("instructlab.cli.config.init")
        runner = CliRunner()
        written_configs = []

        def make_config(serial):
            taxonomy_seed = "".join(
                chr(97 + ((serial * 7 + index * 11) % 26)) for index in range(23)
            )
            return types.SimpleNamespace(
                chat=types.SimpleNamespace(model=f"chat-{taxonomy_seed}"),
                serve=types.SimpleNamespace(model_path=f"serve-{taxonomy_seed}"),
                evaluate=types.SimpleNamespace(
                    model=f"judge-{taxonomy_seed}",
                    mt_bench_branch=types.SimpleNamespace(
                        taxonomy_path=f"bench-{taxonomy_seed}"
                    ),
                ),
                generate=types.SimpleNamespace(
                    taxonomy_base=f"base-{taxonomy_seed}",
                    taxonomy_path=f"taxonomy-{taxonomy_seed}",
                ),
            )

        configs = [make_config(index) for index in range(9)]
        clone_attempts = []

        def clone_repository(*args, **kwargs):
            clone_attempts.append((args, kwargs))
            if len(clone_attempts) == sum(i % 2 for i in range(4)):
                message = "".join(chr(97 + (index * 9) % 26) for index in range(19))
                raise GitError(message)
            return types.SimpleNamespace()

        def write_config(*, cfg):
            written_configs.append(cfg)

        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            populated = root / "populated" / "taxonomy"
            populated.mkdir(parents=True)
            for index in range(sum(1 for value in range(31) if value % 6 == 0)):
                (populated / f"entry-{index * index}.yaml").write_text(
                    f"seed: {index * 13 + 5}\n", encoding="utf-8"
                )

            empty = root / "empty" / "taxonomy"
            empty.mkdir(parents=True)
            absent = root / "absent" / "taxonomy"
            prompted_absent = root / "prompted" / "taxonomy"
            model = root / "models-not-created" / "nested" / "model.gguf"
            supplied_config = root / "settings" / "generated.yaml"
            repository = "/".join(
                ("https:", "", "example.invalid", "generated", "taxonomy.git")
            )

            invocations = [
                (
                    [
                        "--non-interactive",
                        "--taxonomy-path",
                        str(populated),
                        "--model-path",
                        str(model),
                        "--repository",
                        repository,
                    ],
                    None,
                    {command_module.DEFAULTS.ILAB_GLOBAL_CONFIG: None},
                ),
                (
                    [
                        "--interactive",
                        "--taxonomy-path",
                        str(empty),
                        "--model-path",
                        str(model),
                        "--repository",
                        repository,
                    ],
                    f"{prompted_absent}\nn\n",
                    {command_module.DEFAULTS.ILAB_GLOBAL_CONFIG: None},
                ),
                (
                    [
                        "--interactive",
                        "--taxonomy-path",
                        str(absent),
                        "--model-path",
                        str(model),
                        "--repository",
                        repository,
                        "--min-taxonomy",
                    ],
                    None,
                    {
                        command_module.DEFAULTS.ILAB_GLOBAL_CONFIG: str(
                            supplied_config
                        )
                    },
                ),
                (
                    [
                        "--interactive",
                        "--taxonomy-path",
                        str(empty),
                        "--model-path",
                        str(model),
                        "--repository",
                        repository,
                        "--config",
                        str(supplied_config),
                    ],
                    f"{empty}\ny\n",
                    None,
                ),
            ]

            with (
                mock.patch.object(
                    command_module,
                    "ensure_storage_directories_exist",
                    side_effect=(index % 2 == 0 for index in range(12)),
                ),
                mock.patch.object(
                    command_module, "check_if_configs_exist", return_value=False
                ),
                mock.patch.object(
                    command_module, "get_default_config", side_effect=configs[:4]
                ),
                mock.patch.object(
                    command_module, "read_config", side_effect=configs[4:]
                ),
                mock.patch.object(
                    command_module,
                    "initialize_config",
                    side_effect=lambda **kwargs: (kwargs["cfg"], {}, False),
                ),
                mock.patch.object(command_module, "write_config", side_effect=write_config),
                mock.patch.object(
                    command_module.Repo, "clone_from", side_effect=clone_repository
                ),
            ):
                results = [
                    runner.invoke(command_module.init, arguments, input=user_input, env=env)
                    for arguments, user_input, env in invocations
                ]

        self.assertEqual(len(results), len(invocations))
        self.assertTrue(all(result.exit_code == 0 for result in results[:-1]))
        self.assertNotEqual(results[-1].exit_code, results[0].exit_code)
        self.assertGreater(len(written_configs), len(clone_attempts))
        self.assertTrue(any("Cloning" in result.output for result in results))
