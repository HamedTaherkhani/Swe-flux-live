import random
import unittest

from haystack import Document
from haystack.components.preprocessors.document_cleaner import DocumentCleaner


class TestDocumentCleanerInvocationCounts(unittest.TestCase):
    def _exercise(self, *, seed: int, document_count: int, mode: int) -> None:
        rng = random.Random(seed)
        tokens = [
            (rng.randrange(1000, 100_000) * (index + 5) + seed * (index + 1))
            for index in range(document_count)
        ]
        documents = []
        for index, token in enumerate(tokens):
            if (token + index + mode) % 11 == 0:
                content = None
            else:
                pages = []
                page_count = 5 + token % 3 if mode & (1 << 5) else 1 + token % 4
                line_count = 4 + (token // 7) % 6
                for page_index in range(page_count):
                    lines = [
                        "  ".join(
                            [
                                "COMMON HEADER BLOCK",
                                f"café-{(token + line_index) % 97}",
                                "DROP" if (token + line_index + page_index) % 3 == 0 else "keep",
                                f"marker-{seed % 29}",
                                str((token * (line_index + 3) + page_index) % 1009),
                            ]
                        )
                        for line_index in range(line_count)
                    ]
                    if (token + page_index) % 2 == 0:
                        lines.insert((page_index + mode) % (len(lines) + 1), "   ")
                    lines.append("COMMON FOOTER BLOCK")
                    pages.append("\n".join(lines))
                content = "\f".join(pages)

            documents.append(
                Document(
                    id=f"doc-{seed}-{index}",
                    content=content,
                    meta={"token": token, "position": index, "mode_parity": mode % 2},
                    score=(token % 101) / 101,
                )
            )

        cleaner = DocumentCleaner(
            remove_empty_lines=bool(mode & (1 << 3)),
            remove_extra_whitespaces=bool(mode & (1 << 2)),
            remove_repeated_substrings=bool(mode & (1 << 5)),
            keep_id=bool(mode & (1 << 6)),
            remove_substrings=["DROP", f"marker-{seed % 29}"] if mode & (1 << 4) else None,
            remove_regex=None,
            unicode_normalization="NFC" if mode & 1 else None,
            ascii_only=bool(mode & 2),
        )
        result = cleaner.run(documents=documents)

        self.assertEqual(len(result["documents"]), len(documents))
        self.assertTrue(all(cleaned.meta == original.meta for cleaned, original in zip(result["documents"], documents)))
        self.assertTrue(
            all(
                cleaned.content is None or isinstance(cleaned.content, str)
                for cleaned in result["documents"]
            )
        )
        self.assertTrue(all(cleaned is original for cleaned, original in zip(result["documents"], documents) if original.content is None))

    def test_unicode_and_ascii_short_batch(self):
        self._exercise(seed=103, document_count=2, mode=3)

    def test_whitespace_only_three_documents(self):
        self._exercise(seed=211, document_count=3, mode=4)

    def test_empty_line_filter_varied_pages(self):
        self._exercise(seed=307, document_count=4, mode=8)

    def test_substring_removal_wide_batch(self):
        self._exercise(seed=401, document_count=5, mode=(1 << 4))

    def test_repeated_sections_without_other_cleaning(self):
        self._exercise(seed=503, document_count=2, mode=(1 << 5))

    def test_normalization_ascii_and_whitespace(self):
        self._exercise(seed=601, document_count=6, mode=7)

    def test_normalization_whitespace_empty_lines(self):
        self._exercise(seed=709, document_count=3, mode=13)

    def test_ascii_empty_lines_and_substrings(self):
        self._exercise(seed=809, document_count=5, mode=26)

    def test_repeated_sections_with_text_normalization(self):
        self._exercise(seed=907, document_count=4, mode=39)

    def test_repeated_sections_whitespace_and_empty_lines(self):
        self._exercise(seed=1009, document_count=6, mode=(1 << 5) | (1 << 3) | (1 << 2))

    def test_repeated_sections_with_substring_mix(self):
        self._exercise(seed=1103, document_count=3, mode=55)

    def test_all_cleaning_branches_except_regex(self):
        self._exercise(seed=1201, document_count=5, mode=63)
