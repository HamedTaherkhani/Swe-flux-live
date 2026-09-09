import hashlib
import random
import unittest

import torch

from haystack import Document
from haystack.components.readers.extractive import ExtractiveReader


class TestExtractiveNestAnswersLoops(unittest.TestCase):
    def test_seeded_nested_answer_reconstruction(self):
        digest = hashlib.sha256(b"nested-answer-topology:opal-canopy").digest()
        seed = int.from_bytes(digest[:8], "big")
        rng = random.Random(seed)

        query_count = 5 + digest[8] % 3
        sequence_counts = [3 + digest[9 + index] % 5 for index in range(query_count)]
        query_ids = [
            query_id
            for query_id, sequence_count in enumerate(sequence_counts)
            for _ in range(sequence_count)
        ]
        answers_per_seq = 3 + digest[20] % 3

        alphabet = "abcdefghijklmnopqrstuvwxyz"
        documents = []
        for document_index in range(11):
            rotated = alphabet[document_index:] + alphabet[:document_index]
            content = "".join(
                "\f" if position and position % (43 + document_index) == 0 else rotated[position % len(rotated)]
                for position in range(360)
            )
            meta = {"page_number": 2 + document_index} if document_index % 3 else {}
            documents.append(Document(content=content, meta=meta))

        starts = []
        ends = []
        probability_rows = []
        document_ids = []
        for sequence_index, query_id in enumerate(query_ids):
            document_id = (rng.randrange(len(documents)) + query_id + sequence_index * 3) % len(documents)
            document_ids.append(document_id)
            anchor = (rng.randrange(190) + sequence_index * 13 + query_id * 7) % 230

            row_starts = []
            row_ends = []
            row_probabilities = []
            for candidate_index in range(answers_per_seq):
                stride = 2 + (sequence_index + query_id) % 7
                start = (anchor + candidate_index * stride + rng.randrange(9)) % 270
                width = 4 + (digest[(sequence_index + candidate_index) % len(digest)] % 22)
                row_starts.append(start)
                row_ends.append(start + width)
                numerator = 17 + (
                    digest[(sequence_index * answers_per_seq + candidate_index) % len(digest)]
                    + sequence_index * 19
                    + candidate_index * 23
                ) % 79
                row_probabilities.append(numerator / 101.0)

            starts.append(row_starts)
            ends.append(row_ends)
            probability_rows.append(row_probabilities)

        queries = [
            f"Which generated span belongs to query {index} with marker {digest[24 + index]:02x}?"
            for index in range(query_count)
        ]
        reader = ExtractiveReader.__new__(ExtractiveReader)
        nested_answers = reader._nest_answers(
            start=starts,
            end=ends,
            probabilities=torch.tensor(probability_rows, dtype=torch.float64),
            flattened_documents=documents,
            queries=queries,
            answers_per_seq=answers_per_seq,
            top_k=4 + digest[31] % 5,
            score_threshold=0.0,
            query_ids=query_ids,
            document_ids=document_ids,
            no_answer=True,
            overlap_threshold=(digest[23] % 31 + 20) / 100.0,
        )

        self.assertEqual(len(nested_answers), len(queries))
        self.assertTrue(all(len(group) > 1 for group in nested_answers))
        self.assertTrue(
            all(answer.query == queries[index] for index, group in enumerate(nested_answers) for answer in group)
        )
        self.assertTrue(all(any(answer.document is None for answer in group) for group in nested_answers))
        self.assertTrue(all(group == sorted(group, key=lambda answer: answer.score, reverse=True) for group in nested_answers))
