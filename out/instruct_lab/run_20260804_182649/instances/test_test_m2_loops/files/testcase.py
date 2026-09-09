from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import random

import click
from click.testing import CliRunner

from instructlab.model.model import model as model_group


class HarnessContext:
    def ensure_config(self, _ctx):
        return None


@click.group()
@click.pass_context
def command_root(ctx):
    ctx.obj = HarnessContext()


command_root.add_command(model_group)


class TestModelCommandLoops(TestCase):
    def test_generated_answer_shapes(self):
        rng = random.Random(8675309)
        payloads = []
        for invocation_index in range(11):
            words = [
                f"{invocation_index:x}-{rng.getrandbits(48):x}"
                for _ in range(13 + rng.randrange(9))
            ]
            payloads.append("\n".join(words))

        calls = []

        def generated_answers(_ctx, test_file, **_kwargs):
            payload = Path(test_file).read_bytes()
            digest = sha256(payload + len(calls).to_bytes(2, "big")).digest()
            calls.append(digest)
            answers = {}
            for question_index in range(6 + digest[0] % 7):
                models = {}
                for model_index in range(4 + digest[question_index + 1] % 8):
                    name_byte = digest[(question_index * 3 + model_index) % len(digest)]
                    models[f"model-{question_index:x}-{model_index:x}-{name_byte:x}"] = (
                        f"answer-{digest[-model_index - 1]:x}"
                    )
                answers[f"question-{question_index:x}-{digest[question_index]:x}"] = models
            return answers

        runner = CliRunner()
        with (
            patch("instructlab.utils.is_macos_with_m_chip", return_value=False),
            patch("instructlab.model.model.storage_dirs_exist", return_value=True),
            patch(
                "instructlab.model.linux_test.linux_test",
                side_effect=generated_answers,
            ) as linux_runner,
            runner.isolated_filesystem(),
        ):
            for invocation_index, payload in enumerate(payloads):
                input_path = Path(f"input-{invocation_index:x}.jsonl")
                input_path.write_text(payload, encoding="utf-8")
                result = runner.invoke(
                    command_root,
                    [
                        "model",
                        "test",
                        "--test_file",
                        str(input_path),
                    ],
                )
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn("successfully", result.output)

        self.assertEqual(linux_runner.call_count, len(payloads))
        self.assertTrue(all(calls))
