import importlib
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TestPhasedTrainingDataFlow(unittest.TestCase):
    def test_seeded_phase_entry_paths(self):
        rng = random.Random(817_263)
        implementation = importlib.import_module(
            "instructlab.model." + "accelerated_" + "train"
        )
        phases = implementation.TrainingPhases

        class FakeTrainPhase:
            def __init__(self, checkpoints):
                self.checkpoints = checkpoints
                self.ended_at_utc = None

        class FakeEvalPhase:
            def __init__(self, checkpoints):
                self.checkpoints = list(checkpoints)
                self.finished_checkpoints = []
                self.results = []
                self.best_checkpoint = None
                self.ended_at_utc = None

        class FakeJournal:
            constructed = 0
            commits = 0

            def __init__(self, journalfile):
                type(self).constructed += 1
                self.serial = type(self).constructed
                self.journalfile = Path(journalfile)
                self.was_loaded = True
                entry_phase = (
                    phases.TRAIN1,
                    phases.TRAIN2,
                    phases.EVAL2,
                    phases.DONE,
                )[(self.serial - 1) % 4]
                wave = (self.serial - 1) // 4
                marker = self.journalfile.parent / f"prior-{wave}"
                self.journal = SimpleNamespace(
                    current_phase=entry_phase,
                    train_1=FakeTrainPhase(marker) if wave % 2 else None,
                    train_2=FakeTrainPhase(marker) if wave % 3 else None,
                    eval_2=FakeEvalPhase([marker]) if wave % 4 else None,
                    final_output=None,
                    ended_at_utc=None,
                )

            @property
            def current_phase(self):
                return self.journal.current_phase

            @current_phase.setter
            def current_phase(self, value):
                self.journal.current_phase = value

            def commit(self, create_new=False):
                type(self).commits += 1 + int(create_new)

            def print_model_rich(self):
                return ""

            @staticmethod
            def now_utc():
                return None

        outcomes = []

        def prepare(base_dir, delete_subdirs=True):
            del delete_subdirs
            for phase_name in ("phase1", "phase2"):
                checkpoint_root = Path(base_dir) / phase_name / "checkpoints"
                (checkpoint_root / "hf_format").mkdir(parents=True, exist_ok=True)
            phase1_hf = Path(base_dir) / "phase1" / "checkpoints" / "hf_format"
            for ordinal in range(17 + rng.randrange(5)):
                salt = (rng.randrange(10_000) + ordinal * ordinal) % 997
                (phase1_hf / f"samples_{ordinal * 1009 + salt + 1}").mkdir()
            phase2_hf = Path(base_dir) / "phase2" / "checkpoints" / "hf_format"
            for ordinal in range(16 + rng.randrange(6)):
                salt = (rng.randrange(20_000) ^ (ordinal * 47)) % 991
                (phase2_hf / f"candidate-{ordinal:02d}-{salt:03d}").mkdir()
            (Path(base_dir) / "phase2" / "eval_cache").mkdir(parents=True)

        def run_phase(*, journal, phase_model, next_phase, **_kwargs):
            phase_model.ended_at_utc = None
            journal.current_phase = next_phase
            journal.commit()

        def evaluate(*, phase_model, journal, eval_func):
            del eval_func
            chosen = phase_model.checkpoints[
                (journal.serial * journal.serial + len(phase_model.checkpoints))
                % len(phase_model.checkpoints)
            ]
            score = ((journal.serial * 43) % 101) / 100
            journal.commit()
            return SimpleNamespace(checkpoint=chosen, score=score)

        run_total = 18 + sum(rng.randrange(7) % 2 for _ in range(9))
        with tempfile.TemporaryDirectory() as workdir:
            root = Path(workdir)
            phase1_data = root / "knowledge.jsonl"
            phase2_data = root / "skills.jsonl"
            judge = root / "judge"
            phase1_data.write_text("{}\n", encoding="utf-8")
            phase2_data.write_text("{}\n", encoding="utf-8")
            judge.mkdir()

            with (
                patch.object(implementation, "TrainingJournal", FakeJournal),
                patch.object(implementation, "TrainPhaseModel", FakeTrainPhase),
                patch.object(implementation, "EvalPhaseModel", FakeEvalPhase),
                patch.object(implementation, "_prepare_phased_base_dir", prepare),
                patch.object(implementation, "_run_phase", side_effect=run_phase),
                patch.object(
                    implementation,
                    "_evaluate_dir_of_checkpoints",
                    side_effect=evaluate,
                ),
                patch.object(implementation.click, "secho"),
            ):
                for index in range(run_total):
                    offset = index % 4
                    wave = index // 4
                    use_multiphase = offset == 0 or (offset == 1 and wave % 2 == 0)
                    strategy = (
                        "lab-multiphase" if use_multiphase else "lab-skills-only"
                    )
                    base_dir = root / f"run-{index}"
                    implementation.accelerated_train(
                        train_args=SimpleNamespace(run=index),
                        torch_args=SimpleNamespace(run=index),
                        strategy=strategy,
                        distributed_backend="fsdp",
                        phased_phase1_data=(
                            phase1_data if strategy == "lab-multiphase" else None
                        ),
                        phased_phase2_data=phase2_data,
                        phased_base_dir=base_dir,
                        phased_phase1_num_epochs=1 + index % 3,
                        phased_phase1_samples_per_save=(index * 7) % 31,
                        phased_phase1_learning_rate=(index + 1) / 10_000,
                        phased_phase1_effective_batch_size=8 + index % 5,
                        phased_phase2_num_epochs=1 + index % 4,
                        phased_phase2_samples_per_save=(index * 11) % 37,
                        phased_phase2_learning_rate=(index + 3) / 20_000,
                        phased_phase2_effective_batch_size=12 + index % 7,
                        enable_serving_output=bool(index % 2),
                        phased_mt_bench_judge=judge,
                        skip_user_confirm=True,
                        force_clear_phased_cache=False,
                        eval_serve=object(),
                        eval_gpus=index % 3,
                        training_journal=None,
                    )
                    outcomes.append(FakeJournal.commits)

        self.assertEqual(len(outcomes), run_total)
        self.assertTrue(all(left <= right for left, right in zip(outcomes, outcomes[1:])))
        self.assertGreater(FakeJournal.commits, FakeJournal.constructed)
