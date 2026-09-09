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
                wave_tags = (
                    "wave-tag: corpus=knowledge shard=17 lane=3 parity=1 checksum=1549 residue=2",
                    "wave-tag: corpus=skills shard=23 lane=5 parity=0 checksum=2117 residue=5",
                    "wave-tag: corpus=blend shard=31 lane=7 parity=1 checksum=2903 residue=8",
                    "wave-tag: corpus=final shard=41 lane=11 parity=0 checksum=3797 residue=13",
                )
                outputs = (
                    "\n".join(
                        (
                            wave_tags[0],
                            "epoch-trace: phase=1 status=fail bucket=4 modulus=13",
                            "stderr-tail: exit=1 signal=training wave=0 token=17",
                            phase_one,
                            workflow.INTENTIONAL_TRAINING_FAILURE_MESSAGE,
                        )
                    ),
                    "\n".join(
                        (
                            wave_tags[1],
                            "epoch-trace: phase=1 status=ok bucket=6 modulus=17",
                            "epoch-trace: phase=2 status=fail bucket=9 modulus=19",
                            "stderr-tail: exit=1 signal=training wave=1 token=41",
                            phase_one,
                            phase_two,
                            workflow.INTENTIONAL_TRAINING_FAILURE_MESSAGE,
                        )
                    ),
                    "\n".join(
                        (
                            wave_tags[2],
                            "epoch-trace: phase=2 status=resume bucket=2 modulus=23",
                            "epoch-trace: eval=mtbench status=fail bucket=11 modulus=29",
                            "stderr-tail: exit=1 signal=mtbench wave=2 token=67",
                            phase_two,
                            evaluation,
                            journal_one,
                            workflow.INTENTIONAL_MT_BENCH_FAILURE_MESSAGE,
                        )
                    ),
                    "\n".join(
                        (
                            wave_tags[3],
                            "epoch-trace: eval=mtbench status=ok bucket=13 modulus=31",
                            "epoch-trace: phase=2 status=skip bucket=17 modulus=37",
                            "stderr-tail: exit=0 signal=complete wave=3 token=97",
                            evaluation,
                            journal_one,
                            "SKIPPING: Training Phase 2/2; already in Journal",
                            (
                                "ᕦ(òᴗóˇ)ᕤ Accelerated model training completed "
                                "successfully! ᕦ(òᴗóˇ)ᕤ"
                            ),
                            "Best final checkpoint: generated-checkpoint-shard-41-epoch-7",
                        )
                    ),
                )
                failed = call_index < len(outputs) - 1
                return types.SimpleNamespace(
                    output=outputs[call_index],
                    exception=RuntimeError(
                        f"generated failure wave-{call_index}-token-{call_index * 41 + 17}"
                    )
                    if failed
                    else None,
                    exit_code=int(failed),
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            data_paths = [
                root
                / (
                    f"{kind}-sq{sum(index * index for index in range(limit))}-"
                    f"cb{sum(index * index * index for index in range(limit % 13 + 11))}-"
                    f"ln{sum(index for index in range(limit % 7 + 5))}.jsonl"
                )
                for kind, limit in (("knowledge-corpus-alpha", 73), ("skills-corpus-beta", 89))
            ]
            for index, path in enumerate(data_paths):
                path.write_text(
                    "\n".join(
                        f'{{"row": {row}, "bucket": {(row * row + index) % 13}, '
                        f'"lane": {row % 7}, "parity": {row % 3}, '
                        f'"shard": {(row * 5 + index) % 19}, '
                        f'"residue": {(row * row * row + index) % 23}, '
                        f'"modulus": {(row * 7 + index) % 29}}}'
                        for row in range(73 + index * 37)
                    ),
                    encoding="utf-8",
                )
            config_path = root / "generated-config-shard-41-epoch-7.yaml"
            config_path.write_text(
                "general:\n  log_level: DEBUG\n"
                "training:\n  phased:\n    resume: true\n"
                "    checkpoint_prefix: variant-shard-41\n"
                "    epoch_limit: 7\n"
                "    knowledge_weight: 0.73\n"
                "    skills_weight: 0.89\n"
                "evaluation:\n  mtbench:\n    shard: 31\n    lane: 11\n"
                "    threshold: 0.67\n",
                encoding="utf-8",
            )

            with mock.patch.object(workflow, "CliRunner", DeterministicCliRunner):
                workflow.test_phased_training_resume(
                    str(data_paths[1]),
                    str(data_paths[0]),
                    str(root),
                    str(config_path),
                )

        self.assertEqual(
            len(DeterministicCliRunner.invocations), len(data_paths) * len(data_paths)
        )
        self.assertTrue(
            all("--phased-base-dir" in args for _, args in DeterministicCliRunner.invocations)
        )
