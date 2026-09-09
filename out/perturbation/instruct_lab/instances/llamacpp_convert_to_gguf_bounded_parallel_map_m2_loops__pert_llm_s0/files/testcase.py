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
    current_vocab = None
    current_special_vocab = None

    def __init__(self, path):
        self.path = path

    def load_vocab(self, vocab_types, model_parent_path):
        return type(self).current_vocab, type(self).current_special_vocab


class GeneratedSpecialVocab:
    def __init__(self, scenario):
        self.scenario = scenario

    def add_to_gguf(self, writer):
        writer.add_special_token_count(
            sum((index * index + self.scenario) % 4 for index in range(17))
        )


class TestBoundedConversionLoops(unittest.TestCase):
    def test_generated_conversion_workloads(self):
        scenario_count = sum(value % 4 != 2 for value in range(14))
        completed = []
        RecordingWriter.instances.clear()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            for scenario in range(scenario_count):
                tensor_count = sum(
                    1 + int((index * index + 5 * scenario) % 7 == 0)
                    for index in range(31 + scenario * 7)
                )
                model = {}
                for index in range(tensor_count):
                    rows = 1 + (index * 5 + scenario) % 5
                    columns = 2 + (index * 13 + scenario * scenario) % 7
                    values = (
                        np.arange(rows * columns, dtype=np.float32).reshape(
                            rows, columns
                        )
                        + ((index + 1) * (scenario + 3) % 23)
                    )
                    model[f"generated.{scenario}.{index:03d}"] = converter.LazyTensor(
                        lambda values=values: converter.UnquantizedTensor(values),
                        list(values.shape),
                        converter.DT_F32,
                        f"scenario-{scenario}-tensor-{index}",
                    )

                token_count = sum(
                    1 + int((index + scenario) % 5 == 0)
                    for index in range(23 + scenario * 2)
                )
                vocab = converter.BpeVocab.__new__(converter.BpeVocab)
                vocab.vocab = {
                    f"token-{scenario}-{index:03d}".encode(): index
                    for index in range(token_count)
                }
                vocab.added_tokens_dict = {}
                vocab.added_tokens_list = []
                vocab.vocab_size_base = token_count
                vocab.vocab_size = token_count
                vocab.fname_tokenizer = root / f"vocab-{scenario}.json"
                vocab.fname_added_tokens = None

                params = converter.Params(
                    n_vocab=token_count,
                    n_embd=16 + (scenario % 3) * 8,
                    n_layer=3 + scenario % 2,
                    n_ctx=256 if scenario % 3 == 0 else (4096 if scenario % 3 == 1 else 512),
                    n_ff=64 + (scenario % 4) * 16,
                    n_head=4 + (scenario % 3) * 2,
                    n_head_kv=1 + scenario % 3,
                    f_norm_eps=1e-5,
                )
                model_plus = converter.ModelPlus(
                    model=model,
                    paths=[root / f"weights-{scenario}.bin"],
                    format="none",
                    vocab=vocab,
                )
                GeneratedVocabFactory.current_vocab = vocab
                GeneratedVocabFactory.current_special_vocab = GeneratedSpecialVocab(
                    scenario
                )
                concurrency = 1 + sum(
                    (scenario + offset * offset) % 7 == 0 for offset in range(8)
                )
                output = root / f"converted-{scenario}.gguf"

                with (
                    mock.patch.object(
                        converter, "load_some_model", return_value=model_plus
                    ),
                    mock.patch.object(converter.Params, "load", return_value=params),
                    mock.patch.object(
                        converter, "VocabFactory", GeneratedVocabFactory
                    ),
                    mock.patch.object(
                        converter,
                        "convert_model_names",
                        side_effect=lambda value, *_: value,
                    ),
                    mock.patch.object(
                        converter,
                        "pick_output_type",
                        return_value=converter.GGMLFileType.MostlyQ8_0,
                    ),
                    mock.patch.object(
                        converter,
                        "convert_to_output_type",
                        side_effect=lambda value, *_: value,
                    ),
                    mock.patch.object(converter.gguf, "GGUFWriter", RecordingWriter),
                ):
                    result = converter.convert_llama_to_gguf(
                        model=root,
                        outfile=str(output),
                        concurrency=concurrency,
                    )

                writer = RecordingWriter.instances[-1]
                tensor_writes = [
                    call for call in writer.calls if call[0] == "write_tensor_data"
                ]
                self.assertEqual(len(tensor_writes), len(model))
                self.assertTrue(all(call[1][0].size > 0 for call in tensor_writes))
                completed.append(pathlib.Path(result).suffix)

        self.assertEqual(len(completed), scenario_count)
        self.assertTrue(all(suffix == ".gguf" for suffix in completed))
