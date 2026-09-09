import builtins
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from llamafactory.webui import runner as runner_module


class IdentityManager:
    def get_elem_by_id(self, elem_id):
        return elem_id


class TestRunnerCaughtExceptions(unittest.TestCase):
    def test_seeded_wait_failures_are_retried(self):
        seed = sum((index + 11) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)

        usable = []
        for name, candidate in vars(builtins).items():
            if (
                isinstance(candidate, type)
                and issubclass(candidate, Exception)
                and candidate not in (Exception,)
                and candidate.__module__ == "builtins"
                and len(name) > 6
            ):
                try:
                    candidate()
                except BaseException:
                    continue
                usable.append(candidate)

        usable.sort(key=lambda candidate: candidate.__name__)
        selected = rng.sample(usable, min(11, len(usable)))
        rng.shuffle(selected)
        schedule = [selected[(index * index + 3 * index + seed) % len(selected)] for index in range(24)]
        schedule.extend(selected)
        rng.shuffle(schedule)

        class ScriptedTrainer:
            def __init__(self):
                self.calls = 0

            def wait(self, timeout):
                self.calls += 1
                if self.calls <= len(schedule):
                    raise schedule[self.calls - 1]()
                return timeout

        trainer = ScriptedTrainer()
        subject = runner_module.Runner(IdentityManager())
        data = {
            key: value
            for key, value in (
                ("top.lang", "en"),
                ("top.model_name", "seeded-model"),
                ("top.finetuning_type", "lora"),
                ("train.output_dir", "seeded-output"),
            )
        }

        fake_gradio = SimpleNamespace(
            Info=lambda *args, **kwargs: None,
            Slider=lambda **kwargs: ("slider", tuple(sorted(kwargs.items()))),
        )

        def trainer_info(lang, output_path, do_train):
            ordinal = trainer.calls
            details = {}
            if ordinal % 2:
                details["loss_viewer"] = ("loss", ordinal * ordinal)
            if ordinal % 3 == 0:
                details["swanlab_link"] = ("link", ordinal + len(output_path))
            return f"{lang}:{ordinal}", ("progress", ordinal), details

        with (
            patch.object(runner_module.Runner, "_initialize", return_value=""),
            patch.object(
                runner_module.Runner,
                "_parse_train_args",
                return_value={"output_dir": "unused"},
            ),
            patch.object(runner_module.Runner, "_build_config_dict", return_value={}),
            patch.object(runner_module, "Popen", return_value=trainer),
            patch.object(runner_module, "TimeoutExpired", tuple(selected)),
            patch.object(runner_module, "get_save_dir", return_value="/virtual/seeded/run"),
            patch.object(runner_module, "get_trainer_info", side_effect=trainer_info),
            patch.object(runner_module, "save_args"),
            patch.object(runner_module, "save_cmd", return_value="seeded-command"),
            patch.object(runner_module.os, "makedirs"),
            patch.object(runner_module.os.path, "exists", return_value=False),
            patch.object(runner_module, "use_ray", return_value=False),
            patch.object(runner_module, "torch_gc"),
            patch.object(runner_module, "gr", fake_gradio),
        ):
            outputs = list(subject.run_train(data))

        self.assertGreater(len(outputs), len(selected))
        self.assertEqual(len(outputs), trainer.calls + 1)
        self.assertTrue(all(isinstance(item, dict) for item in outputs))
        self.assertFalse(subject.running)
