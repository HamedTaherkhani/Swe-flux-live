import random
import unittest
from types import SimpleNamespace

import torch

from haystack import Document
from haystack.components.rankers.transformers_similarity import TransformersSimilarityRanker


class _BatchEncoding:
    def __init__(self, data):
        self.data = data

    def __getitem__(self, key):
        return self.data[key]

    def to(self, device):
        self.data = {key: value.to(device) for key, value in self.data.items()}
        return self


class _Tokenizer:
    def __call__(self, pairs, *, padding, truncation, return_tensors):
        assert padding and truncation and return_tensors == "pt"
        rows = []
        for query, document in pairs:
            combined = query + "\N{RECORD SEPARATOR}" + document
            weighted = sum((position + 1) * ord(character) for position, character in enumerate(combined))
            rows.append([weighted % 997, len(combined) % 89, sum(map(ord, document)) % 211])
        return _BatchEncoding({"input_ids": torch.tensor(rows, dtype=torch.float32)})


class _Model:
    def __init__(self):
        self.calls = 0

    def __call__(self, *, input_ids):
        self.calls += 1
        weights = torch.tensor([0.013, -0.071, 0.029], dtype=torch.float32)
        logits = (input_ids * weights).sum(dim=1, keepdim=True) + self.calls * 0.017
        return SimpleNamespace(logits=logits)


class _TorchDevice:
    @staticmethod
    def to_torch():
        return torch.device("cpu")


def _build_documents(rng):
    documents = []
    rolling = rng.randrange(10_000)
    candidate_count = 180 + rng.randrange(90)
    for index in range(candidate_count):
        rolling = (rolling * 73 + rng.randrange(10_000) + index * index) % 104_729
        if (rolling + index) % 11 in (0, 4):
            continue
        metadata = {
            "group": f"g-{(rolling // 17) % 31}",
            "signal": (rolling % 19) if index % 4 else 0,
        }
        if index % 6:
            metadata["tag"] = f"tag-{(rolling + index) % 23}"
        content_size = 3 + rolling % 17
        content = " ".join(f"token-{(rolling + offset * 29) % 101}" for offset in range(content_size))
        documents.append(Document(content=content, meta=metadata))
    return documents


class TestTransformersSimilarityRunLoops(unittest.TestCase):
    def test_seeded_batched_ranking(self):
        rng = random.Random(819_271)
        documents = _build_documents(rng)
        batch_size = 3 + rng.randrange(4)
        top_k = 11 + rng.randrange(17)

        ranker = TransformersSimilarityRanker(
            model="synthetic-local-model",
            top_k=top_k,
            meta_fields_to_embed=["group", "signal", "tag"],
            embedding_separator=" | ",
            scale_score=True,
            calibration_factor=0.37,
            score_threshold=0.45,
            batch_size=batch_size,
        )
        ranker.model = _Model()
        ranker.tokenizer = _Tokenizer()
        ranker.device = SimpleNamespace(first_device=_TorchDevice())

        query_parts = [f"q{rng.randrange(10_000):04d}" for _ in range(9)]
        result = ranker.run(query=":".join(query_parts), documents=documents)

        ranked = result["documents"]
        self.assertTrue(ranked)
        self.assertLessEqual(len(ranked), ranker.top_k)
        self.assertGreater(ranker.model.calls, 1)
        self.assertTrue(all(document.score is not None for document in ranked))
        self.assertTrue(all(left.score >= right.score for left, right in zip(ranked, ranked[1:])))
