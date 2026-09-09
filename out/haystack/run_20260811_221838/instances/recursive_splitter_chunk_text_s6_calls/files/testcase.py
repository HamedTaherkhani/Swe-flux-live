import random
import unittest

from haystack import Document
from haystack.components.preprocessors.recursive_splitter import RecursiveDocumentSplitter


class TestRecursiveSplitterCalls(unittest.TestCase):
    def test_generated_hierarchical_document(self):
        rng = random.Random(73129)
        alphabet = "abcdefghijkmnpqrstuvwxyz"
        sections = []
        for section_index in range(18):
            lines = []
            for line_index in range(1 + section_index % 3):
                words = []
                for word_index in range(3 + (section_index * 3 + line_index) % 5):
                    width = 5 + rng.randrange(17)
                    if (section_index * 7 + line_index * 3 + word_index) % 11 == 0:
                        width += 37
                    word = "".join(rng.choice(alphabet) for _ in range(width))
                    if (section_index + line_index + word_index) % 3 == 0:
                        pivot = 2 + rng.randrange(width - 3)
                        word = word[:pivot] + "~" + word[pivot:]
                    words.append(word)
                lines.append(" ".join(words))
            sections.append("\n".join(lines))

        splitter = RecursiveDocumentSplitter(
            split_length=37,
            split_overlap=6,
            split_unit="char",
            separators=["||", "\n", " ", "~"],
        )
        result = splitter.run([Document(content="||".join(sections))])
        documents = result["documents"]

        self.assertGreater(len(documents), len(sections))
        self.assertTrue(all(document.content for document in documents))
        self.assertEqual(
            [document.meta["split_id"] for document in documents],
            list(range(len(documents))),
        )
