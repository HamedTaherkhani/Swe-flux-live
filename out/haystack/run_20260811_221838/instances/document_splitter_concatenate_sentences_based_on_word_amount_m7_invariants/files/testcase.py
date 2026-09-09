import random
import unittest

from haystack import Document
from haystack.components.preprocessors.document_splitter import DocumentSplitter


class TestDocumentSplitterRuntimeInvariants(unittest.TestCase):
    def _exercise(
        self,
        seed: int,
        count_offset: int,
        length_offset: int,
        overlap_offset: int,
        page_mod: int,
    ) -> None:
        rng = random.Random(seed)
        sentence_count = 17 + count_offset
        split_length = 9 + length_offset
        split_overlap = overlap_offset % max(1, split_length // 2)
        sentences = []

        for sentence_index in range(sentence_count):
            baseline = 1 + ((sentence_index * (seed + 3) + rng.randrange(0, 7)) % (split_length + 4))
            if sentence_index == (seed * 3 + count_offset) % sentence_count:
                baseline += split_length
            words = [f"token{seed}_{sentence_index}_{word_index}" for word_index in range(baseline)]
            separator = "\f" if (sentence_index + seed) % page_mod == 0 else " "
            sentences.append(" ".join(words) + "." + separator)

        text = "".join(sentences).rstrip()
        splitter = DocumentSplitter(
            split_by="word",
            split_length=split_length,
            split_overlap=split_overlap,
            respect_sentence_boundary=True,
            use_split_rules=False,
            extend_abbreviations=False,
        )
        splitter.warm_up()
        result = splitter.run(documents=[Document(content=text, meta={"seed": seed})])

        documents = result["documents"]
        self.assertTrue(documents)
        self.assertTrue(all(document.content for document in documents))
        self.assertTrue(all(document.meta["seed"] == seed for document in documents))
        self.assertTrue(all(document.meta["split_id"] == index for index, document in enumerate(documents)))

    def test_dense_short_sentences(self) -> None:
        self._exercise(1, 0, 0, 0, 5)

    def test_overlap_with_varied_lengths(self) -> None:
        self._exercise(2, 1, 2, 3, 6)

    def test_small_limit_frequent_flushes(self) -> None:
        self._exercise(3, 2, -2, 1, 4)

    def test_larger_limit_sparse_pages(self) -> None:
        self._exercise(4, 3, 5, 4, 8)

    def test_even_length_zero_overlap(self) -> None:
        self._exercise(5, 4, 3, 0, 7)

    def test_high_overlap_mixed_sentences(self) -> None:
        self._exercise(6, 5, 1, 7, 5)

    def test_compact_chunks_many_pages(self) -> None:
        self._exercise(7, 6, -1, 2, 3)

    def test_broad_chunks_low_overlap(self) -> None:
        self._exercise(8, 7, 6, 1, 9)

    def test_irregular_medium_chunks(self) -> None:
        self._exercise(9, 8, 4, 5, 6)

    def test_shifted_rng_stream(self) -> None:
        self._exercise(101, 9, 2, 4, 7)

    def test_longer_sequence_tight_limit(self) -> None:
        self._exercise(103, 10, -3, 2, 4)

    def test_longer_sequence_wide_limit(self) -> None:
        self._exercise(107, 11, 7, 6, 8)
