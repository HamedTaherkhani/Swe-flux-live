import pathlib
import tempfile
import unittest
from unittest import mock

import numpy as np

from instructlab.llamacpp import llamacpp_convert_to_gguf as converter


class RecordingWriter:
    instances = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        type(self).instances.append(self)

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


class GeneratedVocabFactory:
    def __init__(self, path, vocab, special_vocab):
        self.vocab = vocab
        self.special_vocab = special_vocab

    def load_vocab(self, vocab_types, model_parent_path):
        return self.vocab, self.special_vocab


class GeneratedSpecialVocab:
    def add_to_gguf(self, writer):
        writer.add_special_token_count(sum(index % 5 for index in range(17)))


class TestLlamaCppConversionCallGraph(unittest.TestCase):
    def test_programmatic_model_conversion(self):
        tensor_count = sum(1 for value in range(53) if value % 3 != 0)
        model = {}
        for index in range(tensor_count):
            rows = 1 + (index * 7) % 4
            columns = 2 + (index * 11) % 5
            values = (
                np.arange(rows * columns, dtype=np.float32).reshape(rows, columns)
                + (index * index % 13)
            )
            model[f"generated.tensor.{index:02d}"] = converter.LazyTensor(
                lambda values=values: converter.UnquantizedTensor(values),
                list(values.shape),
                converter.DT_F32,
                f"generated-{index}",
            )

        token_count = sum((index % 4) + 1 for index in range(13))
        vocab = converter.BpeVocab.__new__(converter.BpeVocab)
        vocab.vocab = {
            f"token-{index:02d}".encode("utf-8"): index
            for index in range(token_count)
        }
        vocab.added_tokens_dict = {}
        vocab.added_tokens_list = []
        vocab.vocab_size_base = token_count
        vocab.vocab_size = token_count
        vocab.fname_tokenizer = pathlib.Path("generated-vocab.json")
        vocab.fname_added_tokens = None

        params = converter.Params(
            n_vocab=token_count,
            n_embd=24,
            n_layer=3,
            n_ctx=512,
            n_ff=64,
            n_head=6,
            n_head_kv=2,
            f_norm_eps=1e-5,
        )
        model_plus = converter.ModelPlus(
            model=model,
            paths=[pathlib.Path("generated") / "weights.bin"],
            format="none",
            vocab=vocab,
        )
        special_vocab = GeneratedSpecialVocab()
        RecordingWriter.instances.clear()

        with tempfile.TemporaryDirectory() as temp_dir:
            output = pathlib.Path(temp_dir) / "converted.gguf"
            with (
                mock.patch.object(
                    converter, "load_some_model", return_value=model_plus
                ),
                mock.patch.object(converter.Params, "load", return_value=params),
                mock.patch.object(
                    converter,
                    "VocabFactory",
                    side_effect=lambda path: GeneratedVocabFactory(
                        path, vocab, special_vocab
                    ),
                ),
                mock.patch.object(
                    converter, "convert_model_names", side_effect=lambda value, *_: value
                ),
                mock.patch.object(
                    converter,
                    "pick_output_type",
                    return_value=converter.GGMLFileType.AllF32,
                ),
                mock.patch.object(
                    converter,
                    "convert_to_output_type",
                    side_effect=lambda value, *_: value,
                ),
                mock.patch.object(converter.gguf, "GGUFWriter", RecordingWriter),
            ):
                result = converter.convert_llama_to_gguf(
                    model=pathlib.Path(temp_dir),
                    outfile=str(output),
                    concurrency=1,
                )

        self.assertEqual(pathlib.Path(result).suffix, ".gguf")
        self.assertEqual(len(RecordingWriter.instances), 1)
        writes = [
            call
            for call in RecordingWriter.instances[0].calls
            if call[0] == "write_tensor_data"
        ]
        self.assertEqual(len(writes), len(model))
        self.assertTrue(all(call[1][0].size > 0 for call in writes))
