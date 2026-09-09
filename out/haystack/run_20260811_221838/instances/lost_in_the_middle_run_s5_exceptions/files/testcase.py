import random
from types import SimpleNamespace
import unittest

from haystack.components.rankers.lost_in_the_middle import LostInTheMiddleRanker


class TestLostInTheMiddleRuntimeFailure(unittest.TestCase):
    def test_generated_documents_with_late_missing_payload(self):
        rng = random.Random(731904)
        payloads = []
        for index in range(43):
            word_total = 2 + rng.randrange(3, 15)
            words = [
                f"w{index:x}{position:x}{rng.randrange(17, 997):x}"
                for position in range(word_total)
            ]
            payloads.append("" if (index + rng.randrange(9)) % 11 == 0 else " ".join(words))

        documents = [
            SimpleNamespace(content_type="text", content=payload)
            for payload in payloads
        ]
        missing_index = 18 + rng.randrange(5, 14)
        generated_name = "".join(chr(65 + rng.randrange(26)) for _ in range(13))
        missing_payload_type = type(generated_name, (), {"content_type": "text"})
        documents.insert(missing_index, missing_payload_type())

        threshold = sum(len(payload.split()) for payload in payloads) + len(payloads) ** 2
        caught = None
        try:
            LostInTheMiddleRanker().run(
                documents=documents,
                word_count_threshold=threshold,
            )
        except BaseException as exc:
            caught = exc

        self.assertIsNotNone(caught)
        self.assertGreater(len(str(caught)), len(documents) // 2)
