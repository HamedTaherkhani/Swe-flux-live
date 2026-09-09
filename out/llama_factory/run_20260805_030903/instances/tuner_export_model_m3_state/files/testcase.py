import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import torch
from transformers import PreTrainedModel, PretrainedConfig

from llamafactory.extras.constants import V_HEAD_SAFE_WEIGHTS_NAME
from llamafactory.webui.components.export import save_model


class _StateMap(dict):
    def __init__(self, tokenizer, processor, ticket):
        super().__init__(tokenizer=tokenizer, processor=processor)
        self.history = []
        self.ticket = ticket
        tokenizer.owner = self
        if processor is not None:
            processor.owner = self

    def __getitem__(self, key):
        value = dict.__getitem__(self, key)
        self.history.append(("get", key, (self.ticket * 17 + len(self.history) * 13) % 997))
        return value

    def __repr__(self):
        return repr(
            {
                "tokenizer": dict.__getitem__(self, "tokenizer"),
                "processor": dict.__getitem__(self, "processor"),
                "history": self.history,
                "ticket": self.ticket,
            }
        )


class _Tokenizer:
    def __init__(self, ticket):
        self.ticket = ticket
        self.padding_side = "right"
        self.init_kwargs = {"marker": (ticket * ticket + 31) % 503}
        self.owner = None
        self.saves = 0
        self.pushes = 0

    def save_pretrained(self, directory):
        self.saves += 1
        self.owner.history.append(("ts", (self.ticket + self.saves * 29) % 991))

    def push_to_hub(self, model_id, token=None):
        self.pushes += 1
        self.owner.history.append(("th", (self.ticket + self.pushes * 43) % 983))

    def __repr__(self):
        return repr(
            {
                "ticket": self.ticket,
                "side": self.padding_side,
                "kwargs": self.init_kwargs,
                "saves": self.saves,
                "pushes": self.pushes,
            }
        )


class _Processor:
    def __init__(self, ticket):
        self.ticket = ticket
        self.owner = None
        self.saves = 0
        self.pushes = 0

    def save_pretrained(self, directory):
        self.saves += 1
        self.owner.history.append(("ps", (self.ticket * 3 + self.saves * 11) % 977))

    def push_to_hub(self, model_id, token=None):
        self.pushes += 1
        self.owner.history.append(("ph", (self.ticket * 5 + self.pushes * 7) % 971))

    def __repr__(self):
        return repr({"ticket": self.ticket, "saves": self.saves, "pushes": self.pushes})


class _Model(PreTrainedModel):
    config_class = PretrainedConfig

    def __init__(self, ticket, quantized, starts_float32):
        super().__init__(PretrainedConfig())
        self.ticket = ticket
        self.quantization_method = "mock-int" if quantized else None
        self.config.torch_dtype = torch.float32 if starts_float32 else torch.bfloat16
        self.moves = []

    def _init_weights(self, module):
        return None

    def to(self, dtype):
        self.moves.append(str(dtype))
        return self

    def save_pretrained(self, **kwargs):
        return None

    def push_to_hub(self, *args, **kwargs):
        return None


class _Template:
    def __init__(self, tokenizer, ticket):
        self.tokenizer = tokenizer
        self.ticket = ticket

    def get_ollama_modelfile(self, tokenizer):
        tokenizer.owner.history.append(("om", (self.ticket * 19 + 5) % 967))
        return "FROM generated\n"


class _Harness:
    def __init__(self, rng):
        self.rng = rng
        self.index = -1

    def get_infer_args(self, args):
        self.index += 1
        ticket = sum((position + 1) * self.rng.randrange(2, 211) for position in range(6))
        adapter_value = args.get("adapter_name_or_path")
        model_args = SimpleNamespace(
            export_dir=args["export_dir"],
            adapter_name_or_path=adapter_value.split(",") if adapter_value else None,
            export_quantization_bit=args["export_quantization_bit"],
            infer_dtype="auto" if self.index % 3 else "float16",
            export_size=args["export_size"],
            export_legacy_format=args["export_legacy_format"],
            export_hub_model_id=args["export_hub_model_id"],
            hf_hub_token=None,
            model_name_or_path=args["model_name_or_path"],
            state_ticket=ticket,
        )
        data_args = SimpleNamespace()
        finetuning_args = SimpleNamespace(stage="rm" if self.index % 3 == 1 else "sft")
        return model_args, data_args, finetuning_args, SimpleNamespace()

    def load_tokenizer(self, model_args):
        tokenizer = _Tokenizer(model_args.state_ticket)
        processor = _Processor(model_args.state_ticket) if self.index % 4 != 2 else None
        return _StateMap(tokenizer, processor, model_args.state_ticket)

    def fix_template(self, tokenizer, data_args):
        tokenizer.init_kwargs["template"] = (tokenizer.ticket * 23 + self.index) % 953
        tokenizer.owner.history.append(("fx", (tokenizer.ticket + self.index * 31) % 947))
        return _Template(tokenizer, tokenizer.ticket)

    def load_model(self, tokenizer, model_args, finetuning_args):
        tokenizer.owner.history.append(("lm", (tokenizer.ticket * 7 + self.index) % 941))
        return _Model(
            tokenizer.ticket,
            model_args.export_quantization_bit is not None,
            starts_float32=self.index % 2 == 0,
        )


class TestExportModelProgramState(unittest.TestCase):
    def test_seeded_webui_export_matrix(self):
        rng = random.Random(sum((index + 5) * ord(char) for index, char in enumerate(self.id())))
        harness = _Harness(rng)

        with TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            source_dirs = []
            export_dirs = []
            for index in range(19):
                source_dir = root / f"source-{index}"
                export_dir = root / f"result-{index}"
                source_dir.mkdir()
                export_dir.mkdir()
                if index % 3 == 1:
                    payload = bytes((rng.randrange(1, 251) + offset) % 256 for offset in range(37))
                    (source_dir / V_HEAD_SAFE_WEIGHTS_NAME).write_bytes(payload)
                source_dirs.append(source_dir)
                export_dirs.append(export_dir)

            all_statuses = []
            with (
                patch("llamafactory.train.tuner.get_infer_args", side_effect=harness.get_infer_args),
                patch("llamafactory.train.tuner.load_tokenizer", side_effect=harness.load_tokenizer),
                patch("llamafactory.train.tuner.get_template_and_fix_tokenizer", side_effect=harness.fix_template),
                patch("llamafactory.train.tuner.load_model", side_effect=harness.load_model),
                patch("llamafactory.train.tuner.infer_optim_dtype", return_value=torch.bfloat16),
                patch("llamafactory.webui.components.export.load_config", return_value={}),
                patch("llamafactory.webui.components.export.get_save_dir", side_effect=lambda _m, _f, a: a),
                patch("llamafactory.webui.components.export.torch_gc", return_value=None),
            ):
                for index, (source_dir, export_dir) in enumerate(zip(source_dirs, export_dirs)):
                    quantized = index % 4 == 0
                    checkpoint = [] if quantized else [str(source_dir)]
                    statuses = list(
                        save_model(
                            "en",
                            f"generated-{index}",
                            str(source_dir),
                            "lora",
                            checkpoint,
                            "generated-template",
                            2 + index % 7,
                            "4" if quantized else "none",
                            "generated-dataset",
                            "cpu",
                            index % 2 == 0,
                            str(export_dir),
                            f"generated-hub-{index}" if index % 5 in (1, 4) else "",
                        )
                    )
                    all_statuses.append(statuses)

            self.assertEqual(harness.index + 1, len(export_dirs))
            self.assertTrue(all(len(statuses) == 2 for statuses in all_statuses))
            self.assertTrue(all((directory / "Modelfile").is_file() for directory in export_dirs))
            copied_heads = sum((directory / V_HEAD_SAFE_WEIGHTS_NAME).is_file() for directory in export_dirs)
            self.assertGreater(copied_heads, len(export_dirs) // 8)
