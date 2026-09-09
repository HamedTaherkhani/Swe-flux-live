import random
import types
import unittest
from types import SimpleNamespace

from llamafactory.data.mm_plugin import IMAGE_PLACEHOLDER, get_mm_plugin
from llamafactory.data.processor.pairwise import PairwiseDatasetProcessor


class _ImageProcessor:
    max_slice_nums = 4
    use_image_id = True

    def get_slice_image_placeholder(self, image_size, index, max_slice_nums, use_image_id):
        width, height = image_size
        pieces = 1 + (width * height + index + max_slice_nums + int(use_image_id)) % 5
        return "<slice>" * pieces


class _TemplateHarness:
    efficient_eos = False

    def __init__(self, plugin):
        self.mm_plugin = plugin

    def encode_oneturn(self, tokenizer, messages, system, tools):
        lengths = [len(message["content"]) for message in messages]
        pivot = max(1, len(lengths) - 1)
        prompt_ids = [1 + value % 89 for value in lengths[:pivot]]
        response_ids = [2 + sum(lengths[pivot:]) % 83]
        return prompt_ids, response_ids


class TestMiniCPMVNestedLoopBehavior(unittest.TestCase):
    def test_seeded_pairwise_batch_through_public_preprocessor(self):
        seed_text = "pairwise-minicpmv-nested-runtime"
        rng = random.Random(sum((index + 1) * ord(char) for index, char in enumerate(seed_text)))
        example_total = ord("T") // 4

        prompts = []
        responses = []
        image_batches = []
        for example_index in range(example_total):
            image_count = ord("0") // 3 + rng.randrange(ord("!"))
            message_count = 1 + 2 * rng.randrange(5)
            allocations = [0] * message_count
            for image_index in range(image_count):
                slot = (image_index * image_index + rng.randrange(message_count) + example_index) % message_count
                allocations[slot] += 1

            prompt = []
            for message_index, allocation in enumerate(allocations):
                noise = "".join(chr(ord("a") + rng.randrange(26)) for _ in range(3 + message_index % 4))
                prompt.append(
                    {
                        "role": "user" if message_index % 2 == 0 else "assistant",
                        "content": f"{example_index}:{message_index}:{noise}:" + IMAGE_PLACEHOLDER * allocation,
                    }
                )

            prompts.append(prompt)
            responses.append(
                [
                    {"role": "assistant", "content": f"chosen-{rng.randrange(10_000):04d}"},
                    {"role": "assistant", "content": f"rejected-{rng.randrange(10_000):04d}"},
                ]
            )
            image_batches.append([object() for _ in range(image_count)])

        plugin = get_mm_plugin(
            name="minicpm_v",
            image_token="<unused-image-token>",
            video_token=None,
            audio_token=None,
        )

        def _fake_mm_inputs(self, images, videos, audios, processor, **kwargs):
            sizes = [(17 + (index * 7) % 31, 19 + (index * index) % 29) for index in range(len(images))]
            return {"image_sizes": [sizes]}

        plugin._get_mm_inputs = types.MethodType(_fake_mm_inputs, plugin)
        processor = SimpleNamespace(image_processor=_ImageProcessor())
        template = _TemplateHarness(plugin)
        tokenizer = SimpleNamespace(eos_token_id=0)
        data_args = SimpleNamespace(cutoff_len=257)
        dataset_processor = PairwiseDatasetProcessor(template, tokenizer, processor, data_args)
        examples = {
            "_prompt": prompts,
            "_response": responses,
            "_system": [None] * example_total,
            "_tools": [None] * example_total,
            "_images": image_batches,
            "_videos": [None] * example_total,
            "_audios": [None] * example_total,
        }

        result = dataset_processor.preprocess_dataset(examples)

        self.assertEqual(len(result["chosen_input_ids"]), example_total)
        self.assertEqual(len(result["rejected_input_ids"]), example_total)
        self.assertTrue(all(result["chosen_attention_mask"]))
        self.assertTrue(all(result["rejected_attention_mask"]))
        self.assertIs(result["images"][0], image_batches[0])
