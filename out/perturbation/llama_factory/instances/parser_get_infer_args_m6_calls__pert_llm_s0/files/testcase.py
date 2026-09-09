import random
import unittest
from unittest.mock import patch

import llamafactory.chat.chat_model as chat_module


class _EngineHarness:
    created = 0

    def __init__(self, *_args):
        type(self).created += 1


class _LoopHarness:
    pass


class _ThreadHarness:
    def __init__(self, **_kwargs):
        self.started = False

    def start(self):
        self.started = True


class TestIndirectInferArgumentCallGraph(unittest.TestCase):
    def test_seeded_chat_model_construction_matrix(self):
        seed = sum((index + 17) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)
        configs = []
        for index in range(60):
            mode = index % 7
            config = {
                "model_name_or_path": "model-" + "".join(chr(97 + rng.randrange(26)) for _ in range(11 + index % 5)),
                "infer_backend": "huggingface"
                if mode in {0, 1, 6} or (mode == 3 and index % 2 == 0) or (mode == 5 and index % 3 == 0)
                else "vllm",
            }
            if mode == 0:
                config.update(
                    export_dir="/tmp/export-" + str(rng.randrange(100, 99999)),
                    export_device="cpu" if index % 3 else "auto",
                    cutoff_len=(512, 1024, 1536, 2048, 2560, 3072, 3584, 4096, 8192)[index % 9],
                )
            elif mode == 2:
                config["stage"] = ("dpo", "ppo", "rm", "kto", "pt")[index % 5]
            elif mode == 3:
                config.update(
                    quantization_bit=8 if index % 2 else 4,
                    finetuning_type="full" if index % 6 == 0 else "lora",
                    pissa_init=index % 6 == 1,
                    resize_vocab=index % 6 == 2,
                    create_new_adapter=index % 6 == 3,
                    adapter_name_or_path=(
                        "adapter-" + str(rng.randrange(100, 999))
                        if index % 6 == 3
                        else ",".join("adapter-" + str(rng.randrange(100, 999)) for _ in range(2))
                        if index % 6 == 4
                        else None
                    ),
                )
            elif mode == 4:
                config["rope_scaling"] = ("linear", "dynamic", "yarn", "llama3")[index % 4]
            elif mode == 5:
                config.update(
                    adapter_name_or_path=",".join(
                        "adapter-" + str(rng.randrange(10, 9999)) for _ in range(2 + index % 3)
                    ),
                    finetuning_type="full" if index % 4 == 1 else "lora",
                    quantization_bit=4 if index % 4 == 2 else None,
                )
            elif mode == 6:
                config.update(template="yi", use_fast_tokenizer=True)
            configs.append(config)

        _EngineHarness.created = 0
        completed = 0
        rejected = 0
        with (
            patch.object(chat_module, "HuggingfaceEngine", _EngineHarness),
            patch.object(chat_module.asyncio, "new_event_loop", return_value=_LoopHarness()),
            patch.object(chat_module, "Thread", _ThreadHarness),
        ):
            for config in configs:
                try:
                    model = chat_module.ChatModel(config)
                except ValueError:
                    rejected += 1
                else:
                    completed += 1
                    self.assertIsInstance(model.engine, _EngineHarness)

        self.assertEqual(completed + rejected, len(configs))
        self.assertEqual(_EngineHarness.created, completed)
        self.assertGreater(completed, len(configs) // 4)
        self.assertGreater(rejected, len(configs) // 3)