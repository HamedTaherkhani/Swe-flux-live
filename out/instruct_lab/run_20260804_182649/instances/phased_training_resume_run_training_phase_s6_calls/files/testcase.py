import contextlib
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from scripts import phased_training_resume as workflow


class TestPhasedTrainingResumeCalls(unittest.TestCase):
    def test_resume_sequence_with_generated_paths(self):
        class DeterministicCliRunner:
            invocations = []

            def isolated_filesystem(self):
                return contextlib.nullcontext()

            def invoke(self, command, arguments):
                call_index = len(type(self).invocations)
                type(self).invocations.append((command, tuple(arguments)))

                phase_one = "Training Phase 1/2..."
                phase_two = "Training Phase 2/2..."
                evaluation = "MT-Bench evaluation for Phase 2..."
                journal_one = "SKIPPING: Training Phase 1/2; already in Journal"
                outputs = (
                    "\n".join(
                        (phase_one, workflow.INTENTIONAL_TRAINING_FAILURE_MESSAGE)
                    ),
                    "\n".join(
                        (
                            phase_one,
                            phase_two,
                            workflow.INTENTIONAL_TRAINING_FAILURE_MESSAGE,
                        )
                    ),
                    "\n".join(
                        (
                            phase_two,
                            evaluation,
                            journal_one,
                            workflow.INTENTIONAL_MT_BENCH_FAILURE_MESSAGE,
                        )
                    ),
                    "\n".join(
                        (
                            evaluation,
                            journal_one,
                            "SKIPPING: Training Phase 2/2; already in Journal",
                            (
                                "ᕦ(òᴗóˇ)ᕤ Accelerated model training completed "
                                "successfully! ᕦ(òᴗóˇ)ᕤ"
                            ),
                            "Best final checkpoint: generated-checkpoint",
                        )
                    ),
                )
                failed = call_index < len(outputs) - 1
                return types.SimpleNamespace(
                    output=outputs[call_index],
                    exception=RuntimeError("generated failure") if failed else None,
                    exit_code=int(failed),
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            data_paths = [
                root / f"{kind}-{sum(index * index for index in range(limit))}.jsonl"
                for kind, limit in (("knowledge", 17), ("skills", 19))
            ]
            for index, path in enumerate(data_paths):
                path.write_text(
                    "\n".join(
                        f'{{"row": {row}, "bucket": {(row * row + index) % 7}}}'
                        for row in range(23 + index)
                    ),
                    encoding="utf-8",
                )
            config_path = root / "generated-config.yaml"
            config_path.write_text("general:\n  log_level: INFO\n", encoding="utf-8")

            with mock.patch.object(workflow, "CliRunner", DeterministicCliRunner):
                workflow.test_phased_training_resume(
                    str(data_paths[0]),
                    str(data_paths[1]),
                    str(root),
                    str(config_path),
                )

        self.assertEqual(
            len(DeterministicCliRunner.invocations), len(data_paths) * len(data_paths)
        )
        self.assertTrue(
            all("--phased-base-dir" in args for _, args in DeterministicCliRunner.invocations)
        )
