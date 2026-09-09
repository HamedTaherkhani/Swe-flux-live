import random
import unittest

from haystack import Document
from haystack.components.rankers.meta_field import MetaFieldRanker


class TestMetaFieldRunProgramState(unittest.TestCase):
    def test_generated_mixed_metadata_linear_merge(self):
        seed_material = f"{self.__class__.__name__}:{self._testMethodName}"
        seed = sum((position + 3) * ord(character) for position, character in enumerate(seed_material))
        rng = random.Random(seed)

        alphabet = "abcdefghijklmnopqrstuvwxyz"
        fragments = [
            "".join(alphabet[(slot * slot + slot * offset + offset) % len(alphabet)] for slot in range(4 + offset % 6))
            for offset in range(23)
        ]
        documents = []
        missing_index = (rng.randrange(10_000) + seed) % 52
        rolling = seed % 997
        for index in range(52):
            rolling = (rolling * 73 + rng.randrange(101) + index * index) % 1009
            token_count = 5 + (rolling % 9)
            content = " ".join(
                fragments[(rolling + position * position + rng.randrange(len(fragments))) % len(fragments)]
                for position in range(token_count)
            )
            metadata = {
                "group": (rolling + index * 11) % 17,
                "signal": sum(ord(character) for character in content) % 211,
            }
            if index != missing_index:
                metadata["priority"] = str((rolling * (index + 5) + metadata["signal"]) % 887)
            document_id = f"node-{index:02x}-{(rolling * 37 + index) % 4093:03x}"
            score = ((rolling + rng.randrange(401)) % 997) / 997
            documents.append(Document(id=document_id, content=content, meta=metadata, score=score))

        ranker = MetaFieldRanker(
            meta_field="priority",
            weight=sum((index % 5) + 1 for index in range(9)) / 43,
            top_k=sum((index * index + 3) % 11 for index in range(13)),
            ranking_mode="linear_score",
            sort_order="ascending",
            missing_meta="drop",
            meta_value_type="int",
        )
        result = ranker.run(documents=documents)

        self.assertIsInstance(result["documents"], list)
        self.assertGreater(len(result["documents"]), len(documents) // 2)
        self.assertLess(len(result["documents"]), len(documents))
        self.assertTrue(all("priority" in document.meta for document in result["documents"]))
        self.assertTrue(all(document.score is not None for document in result["documents"]))
