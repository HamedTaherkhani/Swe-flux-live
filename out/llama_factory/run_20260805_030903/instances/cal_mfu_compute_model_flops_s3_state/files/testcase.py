import io
from contextlib import ExitStack, redirect_stdout
from types import SimpleNamespace
import unittest
from unittest.mock import mock_open, patch


class TestCalculateMFUState(unittest.TestCase):
    def test_calculate_multiple_generated_models(self):
        from scripts.stat_utils import cal_mfu

        alphabet = "".join(chr(code) for code in range(ord("a"), ord("z") + 1))
        fragments = [
            "".join(alphabet[(index * index + turn * 7 + index * turn) % len(alphabet)] for index in range(19))
            for turn in range(4)
        ]
        model_paths = [
            "/".join(("generated", fragment, str(sum(map(ord, fragment)) % 997)))
            for fragment in fragments
        ]
        run_arguments = []

        def generated_config(model_path):
            stream = [
                (ord(char) * (index + 3) + index * index) % 211
                for index, char in enumerate(model_path * 3)
            ]
            checksum = sum((index + 1) * value for index, value in enumerate(stream))
            return SimpleNamespace(
                hidden_size=96 + 8 * (sum(stream[::3]) % 29),
                vocab_size=700 + sum(stream[1::4]) % 1301,
                intermediate_size=384 + 16 * (sum(stream[2::5]) % 73),
                num_attention_heads=4 + checksum % 13,
                num_key_value_heads=1 + sum(stream[::7]) % 9,
                num_hidden_layers=3 + sum(stream[1::6]) % 17,
                tie_word_embeddings=len(set(model_path)) < len(model_path) // 3,
            )

        def record_run(arguments):
            run_arguments.append(dict(arguments))

        result_numbers = [
            (sum((index + 5) * ord(char) for index, char in enumerate(fragment)) % 503) + 1
            for fragment in fragments
        ]
        fake_result = {"train_steps_per_second": sum(result_numbers) / len(result_numbers)}
        captured = io.StringIO()

        with ExitStack() as stack:
            stack.enter_context(patch.object(cal_mfu, "run_exp", side_effect=record_run))
            stack.enter_context(
                patch.object(cal_mfu.AutoConfig, "from_pretrained", side_effect=generated_config)
            )
            stack.enter_context(patch.object(cal_mfu.dist, "is_initialized", return_value=False))
            stack.enter_context(patch.object(cal_mfu, "compute_device_flops", return_value=sum(result_numbers) ** 3))
            stack.enter_context(patch.object(cal_mfu, "open", mock_open(read_data="generated")))
            stack.enter_context(patch.object(cal_mfu.json, "load", return_value=fake_result))
            with redirect_stdout(captured):
                for index, model_path in enumerate(model_paths):
                    cal_mfu.calculate_mfu(
                        model_name_or_path=model_path,
                        batch_size=1 + result_numbers[index] % 5,
                        seq_length=48 + result_numbers[-index - 1] % 113,
                        num_steps=2 + index,
                        deepspeed_stage=(index % 2) * 2,
                    )

        rendered = captured.getvalue().splitlines()
        self.assertEqual(len(run_arguments), len(model_paths))
        self.assertEqual(len(rendered), len(model_paths))
        self.assertTrue(all(line.startswith("MFU: ") and line.endswith("%") for line in rendered))
        self.assertTrue(all(arguments["do_train"] for arguments in run_arguments))
