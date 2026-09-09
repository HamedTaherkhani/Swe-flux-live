import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from llamafactory.data import loader as loader_module
from llamafactory.data.parser import DatasetAttr


class _DatasetHarness:
    def __init__(self, size, divisor):
        self.size = size
        self.divisor = divisor
        self.selections = []

    def __len__(self):
        return self.size

    def select(self, indexes):
        self.selections.append(tuple(int(index) for index in indexes))
        return self


class TestLayeredDatasetExceptions(unittest.TestCase):
    def test_seeded_dataset_loading_matrix(self):
        seed = sum((index + 11) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            empty_dir = root / f"empty-{rng.randrange(10_000, 99_999)}"
            mixed_dir = root / f"mixed-{rng.randrange(10_000, 99_999)}"
            empty_dir.mkdir()
            mixed_dir.mkdir()

            extensions = ("json", "csv")
            for index in range(19):
                extension = (
                    extensions[index]
                    if index < len(extensions)
                    else extensions[(index * index + rng.randrange(7)) % len(extensions)]
                )
                (mixed_dir / f"part-{index:02d}.{extension}").write_text(
                    f'{{"ordinal": {index}, "weight": {(index * 37 + seed) % 997}}}\n',
                    encoding="utf-8",
                )

            stream_file = root / f"stream-{rng.randrange(10_000, 99_999)}.json"
            stream_file.write_text("{}\n", encoding="utf-8")

            mode_names = [
                "unknown",
                "absent_file",
                "empty_directory",
                "mixed_directory",
                "streaming_file",
                "opaque_sampling",
                "missing_registry_entry",
                "alignment_arithmetic",
                "successful_sampling",
            ]
            modes = mode_names * 3
            rng.shuffle(modes)

            registry = {
                "alignment-arithmetic": _DatasetHarness(17, 0),
                "successful-sampling": _DatasetHarness(17, 1),
            }
            state = {"attr": None}

            def fake_dataset_list(_names, _dataset_dir):
                return [state["attr"]]

            def fake_load_dataset(path, data_files=None, **_kwargs):
                if data_files is not None or path.startswith("opaque"):
                    return object()
                return registry[path]

            def fake_align_dataset(dataset, _dataset_attr, _data_args, _training_args):
                return dataset.size // dataset.divisor

            model_args = SimpleNamespace(
                cache_dir=None,
                hf_hub_token=None,
                ms_hub_token=None,
                om_hub_token=None,
                trust_remote_code=False,
            )
            training_args = SimpleNamespace(dataloader_num_workers=2, seed=seed)
            completed = []
            failed = []

            with (
                patch.object(loader_module, "get_dataset_list", side_effect=fake_dataset_list),
                patch.object(loader_module, "load_dataset", side_effect=fake_load_dataset),
                patch.object(loader_module, "align_dataset", side_effect=fake_align_dataset),
                patch.object(loader_module.logger, "info_rank0", return_value=None),
            ):
                for ordinal, mode in enumerate(modes):
                    streaming = mode == "streaming_file"
                    num_samples = 23 if mode in {"opaque_sampling", "successful_sampling"} else None
                    max_samples = 13 if mode == "successful_sampling" else None

                    if mode == "unknown":
                        attr = DatasetAttr("generated", f"unknown-{ordinal}")
                    elif mode == "absent_file":
                        attr = DatasetAttr("file", f"absent-{ordinal}.json")
                    elif mode == "empty_directory":
                        attr = DatasetAttr("file", empty_dir.name)
                    elif mode == "mixed_directory":
                        attr = DatasetAttr("file", mixed_dir.name)
                    elif mode == "streaming_file":
                        attr = DatasetAttr("file", stream_file.name)
                    elif mode == "opaque_sampling":
                        attr = DatasetAttr("hf_hub", f"opaque-{ordinal}", num_samples=num_samples)
                    elif mode == "missing_registry_entry":
                        attr = DatasetAttr("hf_hub", f"registry-{ordinal}")
                    elif mode == "alignment_arithmetic":
                        attr = DatasetAttr("hf_hub", "alignment-arithmetic")
                    else:
                        attr = DatasetAttr("hf_hub", "successful-sampling", num_samples=num_samples)

                    state["attr"] = attr
                    data_args = SimpleNamespace(
                        dataset_dir=str(root),
                        max_samples=max_samples,
                        preprocessing_num_workers=None,
                        streaming=streaming,
                    )
                    try:
                        result = loader_module._get_merged_dataset(
                            [f"case-{ordinal}"],
                            model_args,
                            data_args,
                            training_args,
                            stage="sft",
                            merge=False,
                        )
                        completed.append(result)
                    except Exception as exc:
                        failed.append(exc)

            self.assertEqual(len(completed) + len(failed), len(modes))
            self.assertGreater(len(completed), 0)
            self.assertGreater(len(failed), len(completed))
            self.assertTrue(all(isinstance(exc, Exception) for exc in failed))
