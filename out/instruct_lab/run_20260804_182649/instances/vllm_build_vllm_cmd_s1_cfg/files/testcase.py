import json
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from instructlab.model.backends import vllm


class TestVllmBuildPath(unittest.TestCase):
    def test_middle_server_uses_autodetected_configuration(self):
        processes = []

        class FakeProcess:
            def __init__(self):
                self.pid = sum((index + 1) ** 2 for index in range(len(processes) + 7))

        def launch_process(*_args, **_kwargs):
            process = FakeProcess()
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as root:
            root_path = pathlib.Path(root)
            models = [root_path / f"model-{index}" for index in range(3)]
            for index, model in enumerate(models):
                model.mkdir()
                quant_method = "".join(chr(code) for code in (98, 105, 116, 115, 97, 110, 100, 98, 121, 116, 101, 115))
                (model / "config.json").write_text(
                    json.dumps(
                        {
                            "quantization_config": {
                                "quant_method": quant_method if index else "none"
                            }
                        }
                    ),
                    encoding="utf-8",
                )

            option_names = [
                "--" + "-".join(parts)
                for parts in (
                    ("host",),
                    ("port",),
                    ("model",),
                    ("chat", "template"),
                    ("quantization",),
                    ("load", "format"),
                    ("enforce", "eager"),
                    ("distributed", "executor", "backend"),
                    ("served", "model", "name"),
                )
            ]
            first_args = [
                value
                for index, option in enumerate(option_names)
                for value in (option, f"preset-{index}")
            ]
            unrelated_args = [
                value
                for index in range(sum(1 for number in range(37) if number % 2))
                for value in (f"--extra-{index}", str(index * index + 3))
            ]
            third_args = [
                value
                for index in (4, 8)
                for value in (option_names[index], f"manual-{index}")
            ]

            servers = [
                vllm.Server(
                    api_base=f"http://127.0.0.1:{sum(range(20 + index))}",
                    model_family=f"family-{index}",
                    model_path=models[index],
                    chat_template=(
                        "auto"
                        if index < 2
                        else "".join(chr(code) for code in (116, 111, 107, 101, 110, 105, 122, 101, 114))
                    ),
                    host="127.0.0.1",
                    port=sum(range(30 + index)),
                    background=bool(index % 2),
                    vllm_args=(first_args, unrelated_args, third_args)[index],
                )
                for index in range(3)
            ]

            discovered = [
                types.SimpleNamespace(model_name=f"catalog/{index}-{index * index}")
                for index in range(sum(1 for number in range(29) if number % 7 == 0))
            ]
            template = "".join(chr(65 + (index * 11) % 26) for index in range(41))

            with (
                mock.patch.object(vllm.subprocess, "Popen", side_effect=launch_process),
                mock.patch.object(
                    vllm, "get_model_template", return_value=(template, None, None)
                ),
                mock.patch.object(vllm, "list_models", return_value=discovered),
            ):
                for server in servers:
                    server.create_server_process(server.port, server.background)

            self.assertEqual(len(processes), len(servers))
            self.assertTrue(any(server.resources for server in servers))
            self.assertTrue(all(process.pid > 0 for process in processes))

            for server in servers:
                for resource in server.resources:
                    resource.close()
