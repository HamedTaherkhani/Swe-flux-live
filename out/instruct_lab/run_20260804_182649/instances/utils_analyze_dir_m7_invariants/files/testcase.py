import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from instructlab import utils


class TestGeneratedModelDirectoryAnalysis(unittest.TestCase):
    def test_generated_model_forest(self):
        seed_material = "model-directory-invariant"
        rng = random.Random(sum((index + 1) * ord(char) for index, char in enumerate(seed_material)))

        def write_generated_files(directory, group_index, node_index):
            file_count = rng.randrange(1, 7)
            for file_index in range(file_count):
                size = rng.randrange(23, 613) + (group_index + 1) * (node_index + 3)
                payload = bytes(
                    (size + group_index * 19 + node_index * 11 + offset * 7) % 251
                    for offset in range(size)
                )
                filename = f"weight_{file_index}_{(size * 37) % 997}.bin"
                (directory / filename).write_bytes(payload)

        def path_score(path):
            encoded = Path(path).name.encode("utf-8")
            return sum((index + 1) * byte for index, byte in enumerate(encoded))

        def safetensors_candidate(path):
            score = path_score(path)
            return score % 4 != 0

        def gguf_candidate(path):
            score = path_score(path)
            return score % 7 == 0 or score % 11 == 3

        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            model_directories = []
            for group_index in range(4):
                model_dir = base / f"collection_{group_index}_{rng.randrange(100, 999)}"
                model_dir.mkdir()
                model_directories.append(model_dir)
                write_generated_files(model_dir, group_index, 0)

                for node_index in range(1, 19):
                    suffix = (rng.randrange(1000, 9999) * (node_index + 5)) % 10007
                    node = model_dir / f"segment_{node_index}_{suffix}"
                    node.mkdir()
                    write_generated_files(node, group_index, node_index)

            with mock.patch.object(
                utils, "is_model_safetensors", side_effect=safetensors_candidate
            ), mock.patch.object(utils, "is_model_gguf", side_effect=gguf_candidate):
                results = utils.list_models([base], False)

            self.assertTrue(results)
            self.assertTrue(all(result.model_path in model_directories for result in results))
            self.assertTrue(all(result.model_size.endswith(("B", "KB")) for result in results))
