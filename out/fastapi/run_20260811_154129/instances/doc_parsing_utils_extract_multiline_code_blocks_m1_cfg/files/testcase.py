import random
import unittest

from scripts.doc_parsing_utils import check_translation


class TestDocumentParsingControlFlow(unittest.TestCase):
    @staticmethod
    def _prose(rng: random.Random, label: str, count: int) -> list[str]:
        alphabet = "abcdefghijkmnopqrstuvwxyz"
        return [
            f"{label}-{index}-"
            + "".join(rng.choice(alphabet) for _ in range(11 + index % 7))
            + "\n"
            for index in range(count)
        ]

    @classmethod
    def _closed_document(
        cls,
        seed: int,
        prefix_size: int,
        unusual_triple_content: bool,
        unusual_quad_content: bool,
    ) -> list[str]:
        rng = random.Random(seed)
        lines = cls._prose(rng, "opening", prefix_size)
        lines.append(" " * (seed % 3) + "```python\n")
        triple_content = cls._prose(rng, "py-body", 19)
        if unusual_triple_content:
            triple_content[(seed * 7) % len(triple_content)] = "  ````shadow-fence\n"
        lines.extend(triple_content)
        lines.append("```\n")
        lines.extend(cls._prose(rng, "middle", 13 + seed % 4))
        lines.append(" " * (seed % 2) + "````json\n")
        quad_content = cls._prose(rng, "json-body", 18)
        if unusual_quad_content:
            quad_content[(seed * 5) % len(quad_content)] = " ```shadow-fence\n"
        lines.extend(quad_content)
        lines.append("````` trailing-close\n" if seed % 2 else "````\n")
        lines.extend(cls._prose(rng, "ending", 16 + seed % 5))
        return lines

    @classmethod
    def _unclosed_document(cls, seed: int, fence_width: int) -> list[str]:
        rng = random.Random(seed)
        lines = cls._prose(rng, "before-open", 17 + seed % 6)
        lines.append("`" * fence_width + "yaml\n")
        body = cls._prose(rng, "unterminated-body", 27 + seed % 5)
        marker_width = 4 if fence_width == 3 else 3
        body[(seed * 3) % len(body)] = " " + "`" * marker_width + "not-a-close\n"
        lines.extend(body)
        return lines

    def test_generated_documents_follow_distinct_fence_paths(self) -> None:
        english_closed = self._closed_document(104729, 18, False, True)
        translated_closed = self._closed_document(130363, 23, True, False)

        first_result = check_translation(
            translated_closed,
            english_closed,
            lang_code="es",
            auto_fix=False,
            path="generated-closed.md",
        )
        self.assertIs(first_result, translated_closed)

        english_unclosed = self._unclosed_document(155921, 3)
        translated_unclosed = self._unclosed_document(196613, 4)

        second_result = check_translation(
            translated_unclosed,
            english_unclosed,
            lang_code="fr",
            auto_fix=False,
            path="generated-unclosed.md",
        )
        self.assertIs(second_result, translated_unclosed)
