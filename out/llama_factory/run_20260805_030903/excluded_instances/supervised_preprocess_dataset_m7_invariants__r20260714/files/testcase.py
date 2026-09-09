import types
import unittest

from src.llamafactory.data.processor.supervised import PackedSupervisedDatasetProcessor


def _turn(tag: str) -> dict[str, str]:
    return {"role": "user", "content": tag}


class TestPackedSupervisedPreprocessDatasetM7Invariants(unittest.TestCase):
    def _build_processor(self, encoded_by_tag: dict[str, tuple[list[int], list[int]]]) -> PackedSupervisedDatasetProcessor:
        tokenizer = types.SimpleNamespace(pad_token_id=0)
        data_args = types.SimpleNamespace(cutoff_len=7, neat_packing=False)
        processor = PackedSupervisedDatasetProcessor(
            template=object(),
            tokenizer=tokenizer,
            processor=None,
            data_args=data_args,
        )

        def _stub_encode_data_example(self, prompt, response, system, tools, images, videos, audios):
            marker = prompt[0]["content"]
            if marker not in encoded_by_tag:
                raise AssertionError(f"Unexpected marker: {marker}")
            return encoded_by_tag[marker]

        processor._encode_data_example = types.MethodType(_stub_encode_data_example, processor)
        return processor

    def _build_examples(self, tags: list[str], *, invalid_even_prompt: bool = False) -> dict[str, list]:
        prompts = [[_turn(tag)] for tag in tags]
        responses = [[_turn(f"{tag}-response")] for tag in tags]
        if invalid_even_prompt:
            prompts.append([_turn("invalid-a"), _turn("invalid-b")])
            responses.append([_turn("invalid-response")])

        n = len(prompts)
        return {
            "_prompt": prompts,
            "_response": responses,
            "_system": [None] * n,
            "_tools": [None] * n,
            "_images": [None] * n,
            "_videos": [None] * n,
            "_audios": [None] * n,
        }

    def test_invariants_on_inner_packing_loop(self) -> None:
        encoded_by_tag = {
            "a4": ([11, 12, 13, 14], [111, 112, 113, 114]),
            "b3": ([21, 22, 23], [121, 122, 123]),
            "c5": ([31, 32, 33, 34, 35], [131, 132, 133, 134, 135]),
            "d2": ([41, 42], [141, 142]),
            "e2": ([51, 52], [151, 152]),
            "f2": ([61, 62], [161, 162]),
            "long8": ([71, 72, 73, 74, 75, 76, 77, 78], [171, 172, 173, 174, 175, 176, 177, 178]),
        }
        processor = self._build_processor(encoded_by_tag)

        out1 = processor.preprocess_dataset(self._build_examples(["a4", "b3"], invalid_even_prompt=True))
        out2 = processor.preprocess_dataset(self._build_examples(["c5", "d2", "long8"], invalid_even_prompt=False))
        out3 = processor.preprocess_dataset(self._build_examples(["d2", "e2", "f2"], invalid_even_prompt=False))

        # Each invocation should emit exactly one packed sequence of cutoff_len + 1.
        self.assertEqual(len(out1["input_ids"]), 1)
        self.assertEqual(len(out2["input_ids"]), 1)
        self.assertEqual(len(out3["input_ids"]), 1)
        self.assertEqual(len(out1["input_ids"][0]), 8)
        self.assertEqual(len(out2["input_ids"][0]), 8)
        self.assertEqual(len(out3["input_ids"][0]), 8)

