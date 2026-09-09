import sys
import types
import unittest
from unittest import mock

from instructlab.model import evaluate


class TestEvaluateLaunchPath(unittest.TestCase):
    def test_branch_evaluation_reuses_serve_config(self):
        activity = []

        class FakeServer:
            def __init__(self, selected_backend):
                self.selected_backend = selected_backend

            def run_detached(self, client, **kwargs):
                activity.append(("start", self.selected_backend, bool(client), len(kwargs)))
                return f"http://local/{len(activity)}"

            def shutdown(self):
                activity.append(("stop", self.selected_backend))

        class FakeBranchEvaluator:
            serial = 0

            def __init__(self, *args, **kwargs):
                type(self).serial += 1
                self.serial = type(self).serial

            def gen_answers(self, api_base, max_workers, serving_gpus):
                activity.append(("generate", self.serial, api_base, serving_gpus))

            def judge_answers(self, api_base, max_workers, serving_gpus):
                activity.append(("judge", self.serial, api_base, serving_gpus))
                rows = [
                    {
                        "qna_file": f"topic-{index % 7}",
                        "score": ((index * (self.serial + 3)) % 19) / 3,
                    }
                    for index in range(23)
                ]
                return self.serial / 5, rows, self.serial / 100

        fake_mt_bench = types.ModuleType("instructlab.eval.mt_bench")
        fake_mt_bench.MTBenchBranchEvaluator = FakeBranchEvaluator

        serve_config = types.SimpleNamespace(
            backend=None,
            model_path=None,
            vllm=types.SimpleNamespace(gpus=None, vllm_args=[]),
            llama_cpp=types.SimpleNamespace(max_ctx_size=sum(range(40))),
        )
        selected = []

        def select_backend(_config, backend):
            selected.append(backend)
            return FakeServer(backend)

        worker_count = str(sum(value * value for value in range(14)))
        gpu_count = sum(1 for value in range(17) if value % 5 == 0)

        with (
            mock.patch.dict(sys.modules, {"instructlab.eval.mt_bench": fake_mt_bench}),
            mock.patch.object(evaluate, "validate_options"),
            mock.patch.object(evaluate, "get_cpu_count", return_value=len(range(9))),
            mock.patch.object(evaluate, "get_model_arch", return_value="stub-arch"),
            mock.patch.object(evaluate, "get_sysprompt", return_value="stub prompt"),
            mock.patch.object(evaluate, "display_models_and_scores"),
            mock.patch.object(evaluate, "display_branch_eval_summary"),
            mock.patch.object(evaluate, "display_error_rate"),
            mock.patch.object(evaluate.backends, "select_backend", side_effect=select_backend),
            mock.patch("instructlab.model.backends.vllm.contains_argument") as contains,
            mock.patch.object(evaluate, "http_client", return_value=object()),
        ):
            contains.side_effect = (
                lambda option, arguments: any(item == option for item in arguments)
            )
            evaluate.evaluate_model(
                serve_config=serve_config,
                model="/models/candidate",
                base_model="/models/baseline",
                benchmark=evaluate.Benchmark.MT_BENCH_BRANCH,
                judge_model="/models/judge",
                output_dir="/unused",
                max_workers=worker_count,
                taxonomy_path="/taxonomy",
                branch="candidate",
                base_branch="baseline",
                few_shots=0,
                batch_size=1,
                tasks_dir=None,
                gpus=gpu_count,
                merge_system_user_message=False,
                backend=evaluate.backends.VLLM,
                judge_backend=evaluate.backends.LLAMA_CPP,
                tls_insecure=False,
                tls_client_cert=None,
                tls_client_key=None,
                tls_client_passwd=None,
                enable_serving_output=False,
                skip_server=False,
                input_questions=None,
                output_file_formats="json",
                system_prompt=None,
                temperature=0.0,
            )

        self.assertEqual(len(selected), len(activity) // 3)
        self.assertGreater(serve_config.llama_cpp.max_ctx_size, sum(range(100)))
        self.assertTrue(all(kind in {"start", "generate", "judge", "stop"} for kind, *_ in activity))
