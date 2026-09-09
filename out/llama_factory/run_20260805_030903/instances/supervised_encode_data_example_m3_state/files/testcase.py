import random
import unittest
from types import SimpleNamespace

from llamafactory.data.processor.supervised import SupervisedDatasetProcessor


class _SeededMediaPlugin:
    def __init__(self, owner):
        self.owner = owner

    def process_messages(self, messages, _images, _videos, _audios, _processor):
        text = "|".join(message["content"] for message in messages)
        self.owner.runtime_salt = sum(
            (position + 3) * ord(character) for position, character in enumerate(text)
        )
        return messages

    def process_token_ids(
        self, _input_ids, _labels, _images, _videos, _audios, _tokenizer, _processor
    ):
        salt = self.owner.runtime_salt
        prefix = [10 + (salt // divisor) % 79 for divisor in (7, 13)]
        return prefix, [-100] * len(prefix)


class _SeededTemplate:
    def __init__(self, efficient_eos, turn_count):
        self.efficient_eos = efficient_eos
        self.turn_count = turn_count
        self.runtime_salt = 0
        self.mm_plugin = _SeededMediaPlugin(self)

    def encode_multiturn(self, _tokenizer, messages, system, tools):
        salt = self.runtime_salt
        salt += sum(ord(character) for character in (system or ""))
        salt += 3 * sum(ord(character) for character in (tools or ""))
        pairs = []
        rolling = salt
        for turn in range(self.turn_count):
            rolling = (rolling * 1103515245 + 12345 + turn * turn) & 0x7FFFFFFF
            source_ids = [
                10 + (rolling + turn * 17) % 79,
                10 + (rolling // 97 + turn * 11) % 79,
            ]
            target_ids = [
                10 + (rolling // 193 + turn * 7) % 79,
                10 + (rolling // 389 + turn * 5) % 79,
            ]
            pairs.append((source_ids, target_ids))
        return pairs


def _build_examples(rng, sample_count):
    columns = {
        "_prompt": [],
        "_response": [],
        "_system": [],
        "_tools": [],
        "_images": [],
        "_videos": [],
        "_audios": [],
    }
    for ordinal in range(sample_count):
        nonce = rng.randrange(1_000_000_000)
        columns["_prompt"].append(
            [
                {
                    "role": "user" if turn % 2 == 0 else "assistant",
                    "content": f"turn-{ordinal}-{turn}-{nonce ^ (turn * 65537)}",
                }
                for turn in range(3)
            ]
        )
        columns["_response"].append(
            [{"role": "assistant", "content": f"answer-{ordinal}-{nonce * 37 + 19}"}]
        )
        columns["_system"].append(f"policy-{(nonce // 17 + ordinal) % 997}")
        columns["_tools"].append(None if ordinal % 2 else f"tool-{nonce % 991}")
        columns["_images"].append(None)
        columns["_videos"].append(None)
        columns["_audios"].append(None)
    return columns


class TestSupervisedEncodeProgramState(unittest.TestCase):
    def test_seeded_multiconfiguration_preprocessing(self):
        seed = sum((index + 11) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)
        configurations = [
            (False, False, False),
            (True, False, True),
            (False, True, True),
        ]

        for mask_history, train_on_prompt, efficient_eos in configurations:
            processor = SupervisedDatasetProcessor(
                template=_SeededTemplate(
                    efficient_eos=efficient_eos,
                    turn_count=sum((step * step + 5) % 9 for step in range(8)),
                ),
                tokenizer=SimpleNamespace(eos_token_id=2),
                processor=None,
                data_args=SimpleNamespace(
                    cutoff_len=sum((step * 13 + 7) % 19 for step in range(10)),
                    mask_history=mask_history,
                    train_on_prompt=train_on_prompt,
                ),
            )
            examples = _build_examples(rng, sample_count=3)
            result = processor.preprocess_dataset(examples)

            self.assertEqual(len(result["input_ids"]), len(examples["_prompt"]))
            self.assertEqual(len(result["labels"]), len(result["input_ids"]))
            self.assertTrue(
                all(
                    len(input_ids) == len(labels)
                    for input_ids, labels in zip(result["input_ids"], result["labels"])
                )
            )
            self.assertTrue(
                all(len(input_ids) <= processor.data_args.cutoff_len for input_ids in result["input_ids"])
            )
