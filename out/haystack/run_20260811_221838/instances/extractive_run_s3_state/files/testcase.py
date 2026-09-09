import random
import unittest
from types import MethodType, SimpleNamespace

import torch

from haystack import Document
from haystack.components.readers.extractive import ExtractiveReader


class TestExtractiveRunProgramState(unittest.TestCase):
    def test_batched_logits_accumulate_from_generated_documents(self):
        seed_text = f"{self.__class__.__name__}:{self._testMethodName}"
        rng = random.Random(sum((index + 1) * ord(char) for index, char in enumerate(seed_text)))
        vocabulary = [
            "".join(chr(ord("a") + ((slot * slot + offset) % 26)) for slot in range(3 + offset % 5))
            for offset in range(19)
        ]
        documents = []
        for doc_index in range(27):
            word_count = 14 + rng.randrange(23)
            words = [
                vocabulary[(rng.randrange(len(vocabulary)) + doc_index * (position + 1)) % len(vocabulary)]
                for position in range(word_count)
            ]
            documents.append(Document(content=" ".join(words), meta={"rank": (doc_index * 7) % 13}))

        query = " ".join(vocabulary[(index * index + len(documents)) % len(vocabulary)] for index in range(11))
        reader = ExtractiveReader.__new__(ExtractiveReader)
        reader.top_k = sum(index % 4 for index in range(7))
        reader.score_threshold = None
        reader.max_seq_length = sum(len(word) for word in vocabulary[:8])
        reader.stride = len(vocabulary) + len(query.split())
        reader.max_batch_size = sum((index * index + 1) % 3 for index in range(3))
        reader.answers_per_seq = None
        reader.no_answer = bool(len(documents) % 2)
        reader.overlap_threshold = None

        class GeneratedLogitModel:
            def __init__(self):
                self.calls = 0

            def __call__(self, *, input_ids, attention_mask):
                self.calls += 1
                positions = torch.arange(input_ids.shape[1], dtype=torch.float32)
                starts = torch.remainder(
                    input_ids.float() * (self.calls % 5 + 2)
                    + attention_mask.float() * (self.calls % 7)
                    + positions
                    + self.calls,
                    37,
                ) - 18
                ends = torch.remainder(starts * 2 + positions + self.calls, 41) - 20
                return SimpleNamespace(start_logits=starts, end_logits=ends)

        reader.model = GeneratedLogitModel()

        def fake_preprocess(self, *, queries, documents, max_seq_length, query_ids, stride):
            row_counts = [
                2 + ((len(document.content.split()) + index + stride) % 3)
                for index, document in enumerate(documents)
            ]
            expanded_document_ids = [
                document_id
                for document_id, row_count in enumerate(row_counts)
                for _ in range(row_count)
            ]
            width = 3 + (max_seq_length % 4)
            token_rows = []
            for row_index, document_id in enumerate(expanded_document_ids):
                content_weight = sum(
                    (position + 1) * len(word)
                    for position, word in enumerate(documents[document_id].content.split())
                )
                token_rows.append(
                    [
                        (content_weight + row_index * row_index + column * (document_id + 3)) % 53
                        for column in range(width)
                    ]
                )
            input_ids = torch.tensor(token_rows, dtype=torch.int64)
            attention_mask = ((input_ids + torch.arange(width)) % 4 != 0).to(torch.int64)
            sequence_ids = torch.ones_like(input_ids)
            encodings = [None for _ in expanded_document_ids]
            expanded_query_ids = [query_ids[document_id] for document_id in expanded_document_ids]
            return (
                input_ids,
                attention_mask,
                sequence_ids,
                encodings,
                expanded_query_ids,
                expanded_document_ids,
            )

        def fake_postprocess(self, *, start, end, sequence_ids, attention_mask, answers_per_seq, encodings):
            row_totals = (start + end).sum(dim=1)
            starts = [[int(abs(value.item())) % 5] for value in row_totals]
            ends = [[value[0] + 1] for value in starts]
            probabilities = torch.sigmoid(row_totals).unsqueeze(1)
            return starts, ends, probabilities

        def fake_nest_answers(self, **kwargs):
            checksums = [
                sum(span) + document_id
                for span, document_id in zip(kwargs["start"], kwargs["document_ids"])
            ]
            return [checksums]

        reader._preprocess = MethodType(fake_preprocess, reader)
        reader._postprocess = MethodType(fake_postprocess, reader)
        reader._nest_answers = MethodType(fake_nest_answers, reader)

        result = reader.run(query=query, documents=documents)

        self.assertIsInstance(result["answers"], list)
        self.assertGreater(reader.model.calls, len(documents) // 2)
        self.assertEqual(len(result["answers"]), sum(2 + ((len(doc.content.split()) + i + reader.stride) % 3) for i, doc in enumerate(documents)))
