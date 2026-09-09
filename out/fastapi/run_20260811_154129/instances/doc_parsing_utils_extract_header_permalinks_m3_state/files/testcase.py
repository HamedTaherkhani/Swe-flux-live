import unittest

from scripts.doc_parsing_utils import check_translation


class TestGeneratedTranslation(unittest.TestCase):
    def test_generated_fenced_sections(self) -> None:
        lines: list[str] = []
        for section in range(7):
            seed = sum((section + offset) ** 3 for offset in range(1, 6))

            def generated_header(slot: int) -> str:
                level = 1 + ((seed + slot * 11) % 6)
                token = (seed * (slot + 3) + section * 29) % 10007
                title = "".join(
                    chr(65 + ((token + step * step + section) % 26))
                    for step in range(6)
                )
                return f"{'#' * level} {title} {{#part-{token:x}}}"

            lines.extend(
                [
                    generated_header(0),
                    f"prose-{(seed * 7 + section) % 4099:x}",
                    f"```lang{section % 3}",
                    generated_header(1),
                    f"sample({(seed ^ (section * 41)) % 2053})",
                    "```",
                    generated_header(2),
                    f"bridge-{(seed * 13 + section) % 4093:x}",
                    f"````dialect{section % 4}",
                    generated_header(3),
                    f"value = {(seed * seed + section) % 8191}",
                    "````",
                    generated_header(4),
                ]
            )

        result = check_translation(
            doc_lines=lines,
            en_doc_lines=list(lines),
            lang_code="zz",
            auto_fix=False,
            path="generated.md",
        )

        self.assertIs(result, lines)
        self.assertGreater(len(result), len(range(64)))
