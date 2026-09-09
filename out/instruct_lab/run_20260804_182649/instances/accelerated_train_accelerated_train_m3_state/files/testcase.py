import importlib
import random
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest


class _Args:
    def __init__(self, ordinal):
        self.ordinal = ordinal
        self.accelerate_full_state_at_epoch = None


class _Journal(list):
    constructed = 0
    commits = 0

    def __init__(self, journalfile):
        super().__init__()
        type(self).constructed += 1
        self.serial = type(self).constructed
        self.journalfile = Path(journalfile)
        self.was_loaded = self.serial % 4 == 0
        self.journal = SimpleNamespace(
            current_phase=None,
            train_1=None,
            train_2=None,
            eval_2=None,
        )

    def commit(self, create_new=False):
        type(self).commits += 1
        mixed = (
            self.serial * self.serial
            + (len(self) + int(create_new) + 1) * 37
            + type(self).commits * 11
        )
        self.append(mixed % 1543)

    def print_model_rich(self):
        return None


class TestAcceleratedPipeline(unittest.TestCase):
    def test_seeded_phased_journals(self):
        rng = random.Random(904_271)
        decisions = [
            bool((rng.randrange(10_000) ^ (index * index + 31 * index)) % 5)
            for index in range(19)
        ]

        cli_module = importlib.import_module("instructlab.cli.model." + "train")
        implementation = importlib.import_module(
            "instructlab.model." + "accelerated_" + "train"
        )
        callback = cli_module.train.callback
        while hasattr(callback, "__wrapped__"):
            callback = callback.__wrapped__

        run_count = 0

        def run_phases(**kwargs):
            nonlocal run_count
            run_count += 1
            journal = kwargs["journal"]
            prior = sum(journal)
            journal.append(
                (prior * 3 + journal.serial * 41 + len(journal) * 13 + run_count**2)
                % 2017
            )

        with tempfile.TemporaryDirectory() as workdir:
            root = Path(workdir)
            data_path = root / "generated.jsonl"
            phase2_path = root / "skills.jsonl"
            judge_path = root / "judge"
            data_path.write_text("{}\n", encoding="utf-8")
            phase2_path.write_text("{}\n", encoding="utf-8")
            judge_path.mkdir()

            config = SimpleNamespace(
                generate=SimpleNamespace(output_dir=str(root)),
                serve=SimpleNamespace(),
                evaluate=SimpleNamespace(gpus=0),
            )
            context = SimpleNamespace(
                obj=SimpleNamespace(config=config),
                params={},
                fail=lambda message: self.fail(message),
            )
            created_args = []

            def mapped_args(_ctx, _params):
                args = _Args(len(created_args) + 1)
                created_args.append(args)
                return args, SimpleNamespace()

            with (
                patch.object(cli_module, "is_high_fidelity", return_value=True),
                patch.object(cli_module, "map_train_to_library", side_effect=mapped_args),
                patch.object(implementation, "TrainingJournal", _Journal),
                patch.object(
                    implementation,
                    "_prepare_phased_base_dir",
                    lambda *_args, **_kwargs: None,
                ),
                patch.object(
                    implementation,
                    "_run_phased_training",
                    side_effect=run_phases,
                ),
            ):
                for index, clear_cache in enumerate(decisions):
                    callback(
                        ctx=context,
                        data_path=str(data_path),
                        input_dir=str(root),
                        skip_preprocessing=False,
                        tokenizer_dir=None,
                        gguf_model_path=None,
                        model_path=str(root / f"model-{index}"),
                        iters=index,
                        local=True,
                        skip_quantize=False,
                        num_epochs=1 + index % 3,
                        device="cuda",
                        four_bit_quant=False,
                        strategy="lab-skills-only",
                        phased_base_dir=root / "phased",
                        phased_phase1_data=None,
                        phased_phase1_num_epochs=None,
                        phased_phase1_samples_per_save=None,
                        phased_phase1_learning_rate=None,
                        phased_phase1_effective_batch_size=None,
                        phased_phase2_data=phase2_path,
                        phased_phase2_num_epochs=1 + index % 4,
                        phased_phase2_samples_per_save=(index * 7) % 23,
                        phased_phase2_learning_rate=(index + 3) / 10_000,
                        phased_phase2_effective_batch_size=8 + index % 5,
                        phased_mt_bench_judge=judge_path,
                        skip_user_confirm=True,
                        enable_serving_output=False,
                        pipeline="accelerated",
                        training_journal=None,
                        force_clear_phased_cache=clear_cache,
                        distributed_backend="fsdp",
                        optimize_memory=False,
                        disable_accelerate_full_state_at_epoch=index % 2 == 0,
                    )

        self.assertEqual(run_count, len(decisions))
        self.assertEqual(len(created_args), run_count)
        self.assertGreater(_Journal.commits, run_count // 2)
        self.assertGreater(_Journal.constructed, run_count)
