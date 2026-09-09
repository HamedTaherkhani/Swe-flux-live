import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from instructlab.model import dk_bench_utils as benchmark_support
from instructlab.model import evaluate as model_evaluate


class _SyntheticEvaluator:
    def run(self, dataset, **_kwargs):
        record = json.loads(pathlib.Path(dataset).read_text(encoding="utf-8").splitlines()[0])
        selector = record.get("selector", 0)
        if selector == 1:
            return record["unavailable"]
        if selector == 2:
            return selector.unavailable
        if selector == 3:
            return selector + record["response"]
        if selector == 4:
            return selector // (selector - selector)
        if selector == 5:
            return [record][selector]
        if selector == 6:
            return next(iter(record.get("items", [])))
        return {"record_count": len(record)}


class TestDkBenchExceptionEvents(unittest.TestCase):
    def test_layered_outcomes_across_generated_cases(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            root = pathlib.Path(raw_dir)
            output_dir = root / "output"
            output_dir.mkdir()
            wrong_suffix = root / "questions.data"
            wrong_suffix.write_text("{}\n", encoding="utf-8")
            malformed = root / "malformed.jsonl"
            malformed.write_text('{"response": ', encoding="utf-8")

            valid_paths = []
            for selector in range(7):
                path = root / f"generated_{selector:02d}.jsonl"
                record = {
                    "user_input": f"question-{selector * selector + 11}",
                    "reference": f"reference-{selector + 101}",
                    "response": f"response-{selector * 3 + 7}",
                    "selector": selector,
                    "items": [],
                }
                path.write_text(json.dumps(record) + "\n", encoding="utf-8")
                valid_paths.append(path)

            missing_path = root / "absent.jsonl"
            scenario_count = len(valid_paths) * 3 + 5
            failures = 0
            successes = 0

            def judge_is_available(name, _api_key):
                return sum(ord(char) for char in name) % 7 != 0

            with (
                mock.patch.object(
                    benchmark_support, "is_judge_model_name_valid", judge_is_available
                ),
                mock.patch.object(
                    benchmark_support, "RagasEvaluator", _SyntheticEvaluator
                ),
                mock.patch.object(
                    benchmark_support, "write_results", return_value=[]
                ),
                mock.patch.object(benchmark_support, "print_results"),
                mock.patch.object(model_evaluate, "get_model_arch", return_value="synthetic"),
                mock.patch.object(model_evaluate, "get_sysprompt", return_value="generated"),
            ):
                for index in range(scenario_count):
                    residue = index % 13
                    if residue == 0:
                        questions = valid_paths[0]
                    elif residue == 1:
                        questions = missing_path
                    elif residue == 2:
                        questions = wrong_suffix
                    elif residue == 3:
                        questions = malformed
                    else:
                        questions = valid_paths[(index * index + 3 * index) % len(valid_paths)]

                    judge_name = f"judge-{index * index + 17}"
                    environment = (
                        {"OPENAI_API_KEY": f"token-{index + 31}"}
                        if residue != 0
                        else {}
                    )
                    try:
                        with mock.patch.dict(os.environ, environment, clear=True):
                            model_evaluate.evaluate_model(
                                serve_config=mock.sentinel.serve_config,
                                model=f"model-{index + 1}",
                                base_model=None,
                                benchmark=model_evaluate.Benchmark.DK_BENCH,
                                judge_model=judge_name,
                                output_dir=str(output_dir),
                                max_workers="auto",
                                taxonomy_path=None,
                                branch=None,
                                base_branch=None,
                                few_shots=None,
                                batch_size="auto",
                                tasks_dir=None,
                                gpus=None,
                                merge_system_user_message=False,
                                backend=None,
                                judge_backend=None,
                                tls_insecure=False,
                                tls_client_cert=None,
                                tls_client_key=None,
                                tls_client_passwd=None,
                                enable_serving_output=False,
                                skip_server=False,
                                input_questions=str(questions),
                                output_file_formats="jsonl",
                                system_prompt="generated-system-prompt",
                                temperature=0.25,
                            )
                    except Exception:
                        failures += 1
                    else:
                        successes += 1

            self.assertEqual(failures + successes, scenario_count)
            self.assertGreater(failures, successes)
            self.assertGreater(successes, 0)

