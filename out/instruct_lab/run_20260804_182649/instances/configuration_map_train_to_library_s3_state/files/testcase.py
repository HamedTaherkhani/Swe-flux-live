import unittest
from unittest import mock

from click.testing import CliRunner

from instructlab import lab


class TestTrainConfigurationMapping(unittest.TestCase):
    def test_generated_lora_cli_runs(self):
        runner = CliRunner()
        results = []

        with mock.patch(
            "instructlab.model.accelerated_train.accelerated_train"
        ) as accelerated:
            for phase in range(3):
                rank = sum((index * (phase + 2) + 3) % 17 for index in range(19))
                alpha = sum((index * index + phase * 7) % 29 for index in range(23))
                dropout = (
                    sum((index + phase) % 13 for index in range(31)) % 41 + 1
                ) / 100
                target_modules = [
                    "".join(
                        chr(97 + ((phase * 5 + index * 3 + offset) % 26))
                        for offset in range(6)
                    )
                    for index in range(5)
                ]
                quantize_dtype = "".join(
                    chr(97 + ((phase * 11 + offset * 7) % 26))
                    for offset in range(8)
                )

                arguments = [
                    "--config=DEFAULT",
                    "model",
                    "train",
                    "--pipeline",
                    "accelerated",
                    "--strategy",
                    "lab-skills-only",
                    "--device",
                    "cuda",
                    "--lora-rank",
                    str(rank),
                    "--lora-alpha",
                    str(alpha),
                    "--lora-dropout",
                    str(dropout),
                    "--lora-quantize-dtype",
                    quantize_dtype,
                    "--is-padding-free",
                    "false",
                ]
                for module_name in target_modules:
                    arguments.extend(["--lora-target-modules", module_name])

                results.append(runner.invoke(lab.ilab, arguments))

        self.assertEqual(len(results), accelerated.call_count)
        self.assertTrue(all(result.exception is None for result in results))
        self.assertTrue(all(result.exit_code == 0 for result in results))

