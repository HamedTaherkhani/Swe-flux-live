import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import llamafactory.chat.hf_engine as engine_module


class _TokenizerHarness:
    def __init__(self, index, chat_template, has_eos, has_pad):
        self.index = index
        self.chat_template = chat_template
        self.eos_token = f"<end-{index}>"
        self.eos_token_id = index + 100 if has_eos else None
        self.pad_token = f"<pad-{index}>" if has_pad else None
        self.pad_token_id = index + 300 if has_pad else None
        self.bos_token = f"<begin-{index}>"
        self.bos_token_id = index + 500
        self.additional_special_tokens = []

    def encode(self, text, add_special_tokens=True):
        if not text:
            return [self.index + 700]
        return [((ord(char) + self.index * 11) % 89) + 1 for char in text]

    def decode(self, token_ids):
        if token_ids == [self.index + 700]:
            return f"<prefix-{self.index}>"
        return "".join(chr(33 + (token % 57)) for token in token_ids)

    def apply_chat_template(self, messages, add_generation_prompt=False, tokenize=False):
        prefix = self.decode(self.encode(""))
        default = f"generated-system-{self.index}-" + "".join(
            chr(97 + ((self.index * 7 + offset * 5) % 26)) for offset in range(32)
        )
        roles = [message["role"] for message in messages]
        if roles == ["system"]:
            rendered = "<S>{{content}}</S>"
        elif roles == ["system", "user"]:
            rendered = "<S></S><U>{{content}}</U><A>"
        elif roles == ["user"]:
            rendered = f"<S>{default}</S><U>{{{{content}}}}</U><A>"
        elif roles == ["user", "assistant"]:
            rendered = f"<S>{default}</S><U>{{{{content}}}}</U><A>{{{{content}}}}</A>"
        else:
            raise AssertionError("unexpected message layout")
        return prefix + rendered

    def add_special_tokens(self, mapping, replace_additional_special_tokens=True):
        if "eos_token" in mapping:
            self.eos_token = mapping["eos_token"]
            self.eos_token_id = self.index + 900
            return 1
        additions = list(mapping.get("additional_special_tokens", []))
        before = len(self.additional_special_tokens)
        for token in additions:
            if token not in self.additional_special_tokens:
                self.additional_special_tokens.append(token)
        return len(self.additional_special_tokens) - before


class _GeneratingArguments:
    def __init__(self, nonce):
        self.nonce = nonce

    def to_dict(self):
        return {"temperature": (self.nonce % 13 + 1) / 10}


class TestIndirectTemplateCallGraph(unittest.TestCase):
    def test_seeded_engine_construction(self):
        rng = random.Random(sum((i + 3) * ord(char) for i, char in enumerate(self.id())))
        template_pool = (None, "alpaca", "empty", "default", "llama3")
        plans = []
        for index in range(18):
            selected = template_pool[(rng.randrange(1000) + index * index) % len(template_pool)]
            if index < len(template_pool):
                selected = template_pool[index]
            chat_template = f"seeded-chat-{index}" if selected is None or index % 4 == 0 else None
            plans.append(
                (
                    SimpleNamespace(marker=index),
                    SimpleNamespace(template=selected, train_on_prompt=False, tool_format=None),
                    _TokenizerHarness(index, chat_template, index % 3 != 0, index % 5 != 0),
                )
            )

        tokenizer_by_marker = {model_args.marker: tokenizer for model_args, _, tokenizer in plans}

        def fake_load_tokenizer(model_args):
            return {"tokenizer": tokenizer_by_marker[model_args.marker], "processor": None}

        engines = []
        with (
            patch.object(engine_module, "load_tokenizer", side_effect=fake_load_tokenizer),
            patch.object(engine_module, "load_model", side_effect=lambda tokenizer, *_args, **_kwargs: tokenizer),
        ):
            for model_args, data_args, _tokenizer in plans:
                engines.append(
                    engine_module.HuggingfaceEngine(
                        model_args,
                        data_args,
                        SimpleNamespace(stage="sft"),
                        _GeneratingArguments(model_args.marker + rng.randrange(100)),
                    )
                )

        self.assertEqual(len(engines), len(plans))
        self.assertTrue(all(engine.template is not None for engine in engines))
        self.assertTrue(all(engine.tokenizer.eos_token_id is not None for engine in engines))
        self.assertTrue(all(engine.tokenizer.pad_token is not None for engine in engines))
