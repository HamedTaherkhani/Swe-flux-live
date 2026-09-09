import json
import random
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import llamafactory.data.loader as loader_module
from llamafactory.extras.constants import DATA_CONFIG


class TestIndirectDatasetLoadingCallGraph(unittest.TestCase):
    def test_seeded_train_and_eval_dataset_loading(self):
        rng = random.Random(sum((index + 5) * ord(char) for index, char in enumerate(self.id())))

        train_names = [f"train_{index}_{rng.randrange(100_000, 999_999)}" for index in range(19)]
        eval_names = [f"eval_{index}_{rng.randrange(100_000, 999_999)}" for index in range(23)]
        rng.shuffle(train_names)
        rng.shuffle(eval_names)

        def make_entry(name, ordinal):
            entry = {}
            mode = (ordinal * ordinal + ordinal + len(name)) % 5
            if mode == 0:
                entry.update(hf_hub_url=f"hf/{name}", ms_hub_url=f"ms/{name}")
            elif mode == 1:
                entry.update(hf_hub_url=f"hf/{name}", om_hub_url=f"om/{name}")
            elif mode == 2:
                entry["ms_hub_url"] = f"ms/{name}"
            elif mode == 3:
                entry["script_url"] = f"scripts/{name}.py"
            else:
                entry["file_name"] = f"records/{name}.jsonl"

            if (ordinal + len(name)) % 2 == 0:
                entry["columns"] = {
                    key: f"{key}_{(ordinal * 17 + position * 11) % 97}"
                    for position, key in enumerate(
                        [
                            "prompt",
                            "query",
                            "response",
                            "history",
                            "messages",
                            "system",
                            "tools",
                            "images",
                            "videos",
                            "audios",
                            "chosen",
                            "rejected",
                            "kto_tag",
                        ]
                    )
                    if (ordinal + position) % 4 != 1
                }

            if (ordinal * 3 + len(name)) % 5 in {0, 2}:
                entry["tags"] = {
                    key: f"{key}_{(ordinal + position * position) % 31}"
                    for position, key in enumerate(
                        [
                            "role_tag",
                            "content_tag",
                            "user_tag",
                            "assistant_tag",
                            "observation_tag",
                            "function_tag",
                            "system_tag",
                        ]
                    )
                    if (ordinal * position + len(name)) % 3 != 0
                }

            entry["subset"] = f"slice-{(ordinal * 7) % 13}" if ordinal % 4 == 0 else None
            entry["split"] = "validation" if ordinal % 6 == 0 else "train"
            return entry

        all_names = train_names + eval_names
        dataset_info = {name: make_entry(name, ordinal) for ordinal, name in enumerate(all_names)}
        load_kinds = []

        def fake_load(dataset_attr, _model_args, _data_args, _training_args):
            load_kinds.append(dataset_attr.load_from)
            return (dataset_attr.dataset_name, dataset_attr.formatting)

        with tempfile.TemporaryDirectory() as dataset_dir:
            Path(dataset_dir, DATA_CONFIG).write_text(
                json.dumps(dataset_info, sort_keys=True),
                encoding="utf-8",
            )
            data_args = SimpleNamespace(
                tokenized_path=None,
                dataset_dir=dataset_dir,
                dataset=train_names,
                eval_dataset=eval_names,
                streaming=False,
            )
            training_args = SimpleNamespace(
                do_predict=False,
                seed=rng.randrange(1, 1_000_000),
                main_process_first=lambda **_kwargs: nullcontext(),
            )

            with (
                patch.object(loader_module, "_load_single_dataset", side_effect=fake_load),
                patch.object(loader_module, "merge_dataset", side_effect=lambda values, *_args, **_kwargs: tuple(values)),
                patch.object(loader_module, "_get_preprocessed_dataset", side_effect=lambda value, *_args, **_kwargs: value),
                patch.object(
                    loader_module,
                    "split_dataset",
                    side_effect=lambda train, evaluation, *_args, **_kwargs: {
                        "train_dataset": train,
                        "eval_dataset": evaluation,
                    },
                ),
                patch.object(loader_module, "get_dataset_module", side_effect=lambda value: value),
                patch("llamafactory.data.parser.use_modelscope", side_effect=lambda: rng.randrange(7) in {1, 4}),
                patch("llamafactory.data.parser.use_openmind", side_effect=lambda: rng.randrange(5) == 2),
            ):
                result = loader_module.get_dataset(
                    template=SimpleNamespace(),
                    model_args=SimpleNamespace(),
                    data_args=data_args,
                    training_args=training_args,
                    stage="sft",
                    tokenizer=SimpleNamespace(),
                )

        self.assertEqual(set(result), {"train_dataset", "eval_dataset"})
        self.assertEqual(set(result["eval_dataset"]), set(eval_names))
        self.assertTrue(all(kind.endswith(("hub", "script", "file")) for kind in load_kinds))
        self.assertGreater(len(set(load_kinds)), 2)
