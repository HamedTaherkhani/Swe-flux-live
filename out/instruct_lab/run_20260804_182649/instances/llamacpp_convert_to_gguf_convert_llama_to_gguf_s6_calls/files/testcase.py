import importlib
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TestLlamaCppConversionCalls(unittest.TestCase):
    def test_second_seeded_simple_train_conversion(self):
        rng = random.Random(482_071)
        run_number = 0
        model_number = 0
        converted_tensor_counts = []

        conversion_module = importlib.import_module(
            "instructlab.llamacpp." + "llamacpp_convert_to_gguf"
        )
        train_module = importlib.import_module("instructlab.model.simple_train")

        def make_tensor(tag, dimensions):
            return conversion_module.LazyTensor(
                lambda: None,
                list(dimensions),
                conversion_module.DT_F16,
                tag,
            )

        def fake_linux_train(**_kwargs):
            nonlocal run_number
            run_number += 1
            result = workspace / f"seeded-run-{run_number}"
            checkpoint = result / f"checkpoint-{rng.randrange(100, 999)}"
            merged = result / "merged_model"
            checkpoint.mkdir(parents=True)
            merged.mkdir()
            for index, name in enumerate(
                (
                    "added_tokens.json",
                    "special_tokens_map.json",
                    "tokenizer.json",
                    "tokenizer.model",
                    "tokenizer_config.json",
                )
            ):
                payload = (rng.randrange(1_000_000) + index * run_number) % 65_521
                (checkpoint / name).write_text(str(payload), encoding="utf-8")
            (merged / "config.json").write_text("{}", encoding="utf-8")
            (merged / "generation_config.json").write_text("{}", encoding="utf-8")
            (merged / "model.safetensors").write_bytes(
                bytes(rng.randrange(256) for _ in range(41 + run_number))
            )
            return result

        def fake_load_model(path):
            nonlocal model_number
            model_number += 1
            layer_count = 17 + rng.randrange(7)
            width = 8 + 4 * (model_number % 2)
            model = {
                "model.embed_tokens.weight": make_tensor(
                    f"embedding-{model_number}", (width, width)
                ),
                "model.norm.weight": make_tensor(
                    f"normalization-{model_number}", (width,)
                ),
                "lm_head.weight": make_tensor(
                    f"output-{model_number}", (width, width)
                ),
            }
            for layer in range(layer_count):
                phase = (rng.randrange(97) + layer * (model_number + 3)) % 11
                for projection in ("q_proj", "k_proj", "v_proj"):
                    model[
                        f"model.layers.{layer}.self_attn.{projection}.weight"
                    ] = make_tensor(
                        f"{projection}-{layer}-{phase}",
                        (width, width),
                    )
            return conversion_module.ModelPlus(
                model=model,
                paths=[Path(path) / "model.safetensors"],
                format="safetensors",
                vocab=None,
            )

        def fake_load_params(model_plus):
            layers = sum(
                name.endswith("q_proj.weight") for name in model_plus.model
            )
            return conversion_module.Params(
                n_vocab=128,
                n_embd=12,
                n_layer=layers,
                n_ctx=4096,
                n_ff=32,
                n_head=2,
                n_head_kv=2,
                f_norm_eps=1e-5,
            )

        class FakeVocabFactory:
            def __init__(self, path):
                self.path = Path(path)

            def load_vocab(self, vocab_types, model_parent_path):
                token_count = len(vocab_types) + len(Path(model_parent_path).parts)
                return (
                    SimpleNamespace(vocab_size=token_count),
                    SimpleNamespace(source=self.path.name),
                )

        def fake_write_all(outfile, _ftype, _params, model, *_args, **_kwargs):
            converted_tensor_counts.append(len(model))
            destination = Path(outfile)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(
                bytes((index * 13 + len(model)) % 256 for index in range(53))
            )

        linux_module = types.ModuleType("instructlab.train.linux_train")
        linux_module.linux_train = fake_linux_train

        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            checkpoints = workspace / "checkpoints"
            data = workspace / "prepared-data"
            data.mkdir()
            defaults = SimpleNamespace(
                CHECKPOINTS_DIR=str(checkpoints),
                DATASETS_DIR=str(workspace / "default-datasets"),
            )

            with (
                patch.object(train_module.utils, "is_macos_with_m_chip", return_value=False),
                patch.object(train_module, "DEFAULTS", defaults),
                patch.dict(
                    sys.modules,
                    {"instructlab.train.linux_train": linux_module},
                ),
                patch.object(
                    conversion_module,
                    "load_some_model",
                    side_effect=fake_load_model,
                ),
                patch.object(
                    conversion_module.Params,
                    "load",
                    side_effect=fake_load_params,
                ),
                patch.object(
                    conversion_module,
                    "VocabFactory",
                    FakeVocabFactory,
                ),
                patch.object(
                    conversion_module.OutputFile,
                    "write_all",
                    side_effect=fake_write_all,
                ),
            ):
                for pass_index in range(2):
                    train_module.simple_train(
                        model_path=f"seeded-model-{pass_index}",
                        skip_preprocessing=True,
                        skip_quantize=True,
                        gguf_model_path=None,
                        tokenizer_dir=None,
                        data_path=str(data),
                        input_dir=str(data),
                        ckpt_output_dir=str(workspace / "unused"),
                        iters=1,
                        local=True,
                        num_epochs=1,
                        device="cpu",
                        four_bit_quant=False,
                    )

            artifact = checkpoints / "ggml-model-f16.gguf"
            self.assertTrue(artifact.is_file())
            self.assertEqual(run_number, model_number)
            self.assertGreater(sum(converted_tensor_counts), artifact.stat().st_size)
