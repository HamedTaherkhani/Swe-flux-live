import pathlib
import random
import tempfile
import unittest
from unittest import mock

from instructlab.model import evaluate


class TestEvaluateValidationCalls(unittest.TestCase):
    def test_generated_mt_validation_plan(self):
        rng = random.Random(sum(index * index for index in range(23)))
        plan = [
            rng.choice(
                (
                    evaluate.Benchmark.MT_BENCH,
                    evaluate.Benchmark.MT_BENCH_BRANCH,
                )
            )
            for _ in range(19)
        ]
        invalid_workers = "".join(chr(code) for code in (98, 108, 111, 99, 107, 101, 100))
        failures = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            model_paths = []
            for index in range(len(plan) + 2):
                model_path = root / f"model-{index:02d}"
                model_path.mkdir()
                model_paths.append(str(model_path))

            with mock.patch.object(
                evaluate, "is_model_safetensors", return_value=True
            ):
                for index, benchmark in enumerate(plan):
                    with self.assertRaises(ValueError):
                        evaluate.evaluate_model(
                            serve_config=None,
                            model=model_paths[index],
                            base_model=model_paths[-2],
                            benchmark=benchmark,
                            judge_model=model_paths[-1],
                            output_dir=str(root / "results"),
                            max_workers=invalid_workers,
                            taxonomy_path=str(root / "taxonomy"),
                            branch=f"candidate-{index % 7}",
                            base_branch=f"baseline-{index % 5}",
                            few_shots=index % 4,
                            batch_size=(index % 3) + 1,
                            tasks_dir=None,
                            gpus=index % 2,
                            merge_system_user_message=bool(index % 2),
                            backend=None,
                            judge_backend=None,
                            tls_insecure=False,
                            tls_client_cert=None,
                            tls_client_key=None,
                            tls_client_passwd=None,
                            enable_serving_output=False,
                            skip_server=True,
                            input_questions=None,
                            output_file_formats="json",
                            system_prompt=None,
                            temperature=0.0,
                        )
                    failures += 1

        self.assertEqual(failures, len(plan))
        self.assertGreater(len({item.value for item in plan}), 1)
