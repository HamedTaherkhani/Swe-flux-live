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
        seed = sum((index + 11) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)
        configs = []
        for index in range(24):
            mode = index % 7
            config = {
                "model_name_or_path": "model-" + "".join(chr(97 + rng.randrange(26)) for _ in range(9)),
                "infer_backend": "huggingface" if mode in {0, 1, 6} else "vllm",
            }
            if mode == 0:
                config.update(
                    export_dir="/tmp/export-" + str(rng.randrange(1000, 9999)),
                    export_device="cpu",
                    cutoff_len=1536 + 64 * rng.randrange(1, 8),
                )
            elif mode == 2:
                config["stage"] = "dpo"
            elif mode == 3:
                config["quantization_bit"] = 4
            elif mode == 4:
                config["rope_scaling"] = "linear"
            elif mode == 5:
                config["adapter_name_or_path"] = ",".join(
                    "adapter-" + str(rng.randrange(100, 999)) for _ in range(2)
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
