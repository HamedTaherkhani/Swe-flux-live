import random
import unittest

from haystack import Document
from haystack.components.preprocessors import RecursiveDocumentSplitter


class TestRecursiveSplitterOverlapState(unittest.TestCase):
    @staticmethod
    def _char_text(seed: int, count: int, separators: tuple[str, ...]) -> str:
        rng = random.Random(seed)
        pieces = []
        for index in range(count):
            width = 3 + ((rng.randrange(17) + index * 5) % 12)
            body = "".join(chr(97 + ((seed + index * 7 + offset * 11) % 26)) for offset in range(width))
            pieces.append(body)
        return "".join(piece + separators[index % len(separators)] for index, piece in enumerate(pieces)).rstrip(
            "".join(separators)
        )

    @staticmethod
    def _word_text(seed: int, count: int, separators: tuple[str, ...]) -> str:
        rng = random.Random(seed)
        groups = []
        for index in range(count):
            words = []
            for offset in range(1 + ((rng.randrange(11) + index) % 4)):
                width = 2 + ((seed + index * 3 + offset * 5) % 5)
                words.append(
                    "".join(chr(97 + ((seed * 3 + index * 5 + offset * 7 + pos * 9) % 26)) for pos in range(width))
                )
            groups.append(" ".join(words))
        return "".join(group + separators[index % len(separators)] for index, group in enumerate(groups)).rstrip(
            "".join(separators)
        )

    def _exercise(
        self, text: str, *, split_length: int, split_overlap: int, split_unit: str, separators: list[str]
    ) -> None:
        splitter = RecursiveDocumentSplitter(
            split_length=split_length,
            split_overlap=split_overlap,
            split_unit=split_unit,
            separators=separators,
        )
        source = Document(content=text, meta={"source_checksum": sum(map(ord, text)) % 997})
        documents = splitter.run([source])["documents"]

        self.assertGreater(len(documents), 1)
        self.assertTrue(all(document.content for document in documents))
        measure = len if split_unit == "char" else lambda value: len([part for part in value.split(" ") if part])
        self.assertTrue(all(measure(document.content) <= split_length for document in documents))
        self.assertTrue(all(document.meta["parent_id"] == source.id for document in documents))
        self.assertEqual([document.meta["split_id"] for document in documents], list(range(len(documents))))

    def test_01_char_alternating_markers(self) -> None:
        text = self._char_text(47, 17, ("|",))
        self._exercise(text, split_length=19, split_overlap=8, split_unit="char", separators=["|"])

    def test_02_char_recursive_markers(self) -> None:
        text = self._char_text(79, 17, (";", "|"))
        self._exercise(text, split_length=23, split_overlap=9, split_unit="char", separators=[";", "|"])

    def test_03_char_dense_boundaries(self) -> None:
        text = self._char_text(113, 18, ("::",))
        self._exercise(text, split_length=17, split_overlap=7, split_unit="char", separators=["::"])

    def test_04_char_large_overlap(self) -> None:
        text = self._char_text(145, 10, ("#",))
        self._exercise(text, split_length=18, split_overlap=13, split_unit="char", separators=["#"])

    def test_05_char_newline_hierarchy(self) -> None:
        text = self._char_text(181, 15, ("\n\n", "\n"))
        self._exercise(text, split_length=25, split_overlap=11, split_unit="char", separators=["\n\n", "\n"])

    def test_06_char_sparse_primary(self) -> None:
        text = self._char_text(223, 17, ("~", "."))
        self._exercise(text, split_length=21, split_overlap=9, split_unit="char", separators=["~", "."])

    def test_07_word_pipe_groups(self) -> None:
        text = self._word_text(263, 15, ("|",))
        self._exercise(text, split_length=12, split_overlap=5, split_unit="word", separators=["|"])

    def test_08_word_recursive_groups(self) -> None:
        text = self._word_text(293, 14, (";", "|"))
        self._exercise(text, split_length=14, split_overlap=6, split_unit="word", separators=[";", "|", " "])

    def test_09_word_newline_groups(self) -> None:
        text = self._word_text(343, 15, ("\n",))
        self._exercise(text, split_length=7, split_overlap=4, split_unit="word", separators=["\n", " "])

    def test_10_word_high_overlap(self) -> None:
        text = self._word_text(385, 12, ("#",))
        self._exercise(text, split_length=13, split_overlap=10, split_unit="word", separators=["#", " "])

    def test_11_word_double_colon(self) -> None:
        text = self._word_text(427, 14, ("::",))
        self._exercise(text, split_length=15, split_overlap=8, split_unit="word", separators=["::", " "])

    def test_12_word_mixed_boundaries(self) -> None:
        text = self._word_text(469, 16, ("!", "?"))
        self._exercise(text, split_length=16, split_overlap=6, split_unit="word", separators=["!", "?", " "])