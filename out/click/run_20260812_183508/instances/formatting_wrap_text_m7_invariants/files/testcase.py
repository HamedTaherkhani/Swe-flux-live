import unittest

from click.formatting import HelpFormatter


class TestGeneratedHelpLayouts(unittest.TestCase):
    def _make_text(
        self,
        seed,
        paragraph_count,
        width_factor,
        raw_period,
        indent_span,
        oversized=False,
    ):
        state = seed
        paragraphs = []
        for paragraph_index in range(paragraph_count):
            state = (state * 83 + paragraph_index * 47 + 31) % 4001
            is_raw = (state + paragraph_index) % raw_period == 0
            if oversized and paragraph_index == paragraph_count - 1:
                is_raw = True
            line_count = 1 + (state % 4)
            if oversized and paragraph_index == paragraph_count - 1:
                line_count = 1
            lines = []
            for line_index in range(line_count):
                state = (state * 97 + line_index * 29 + seed) % 8191
                word_count = 4 + (state % (3 + width_factor % 8))
                if (
                    oversized
                    and paragraph_index == paragraph_count - 1
                    and line_index == 0
                ):
                    word_count += 60
                words = []
                for word_index in range(word_count):
                    state = (state * 53 + word_index * 17 + paragraph_index) % 16381
                    words.append(f"x{state:x}")
                indentation = " " * ((state + line_index) % indent_span)
                lines.append(indentation + " ".join(words))
            if is_raw:
                paragraphs.append("\b\n" + "\n".join(lines))
            else:
                paragraphs.append("\n".join(lines))
        return "\n\n".join(paragraphs)

    def _exercise_text(self, seed, paragraphs, width, factor, period, span, depth):
        formatter = HelpFormatter(width=width, indent_increment=depth)
        text = self._make_text(seed, paragraphs, factor, period, span)
        for _ in range(depth % 3):
            formatter.indent()
        formatter.write_text(text)
        rendered = formatter.getvalue()
        self.assertTrue(rendered)
        self.assertIn("x", rendered)
        self.assertTrue(rendered.endswith("\n"))

    def _exercise_definition(self, seed, paragraphs, width, factor, period, span):
        formatter = HelpFormatter(width=width)
        text = self._make_text(seed, paragraphs, factor, period, span)
        label = f"option-{(seed * 37) % 997:x}"
        formatter.write_dl([(label, text)], col_max=18, col_spacing=3)
        rendered = formatter.getvalue()
        self.assertTrue(rendered)
        self.assertIn(label, rendered)
        self.assertGreater(len(rendered), len(label))

    def test_alpha_narrow_indented_text(self):
        self._exercise_text(137, 5, 42, 3, 7, 4, 2)

    def test_bravo_wide_mixed_text(self):
        self._exercise_text(191, 7, 67, 4, 9, 5, 3)

    def test_charlie_dense_definition(self):
        self._exercise_definition(251, 6, 58, 49, 5, 8)

    def test_delta_shallow_raw_text(self):
        self._exercise_text(313, 8, 51, 2, 6, 6, 4)

    def test_echo_compact_definition(self):
        self._exercise_definition(379, 4, 47, 38, 3, 5)

    def test_foxtrot_many_paragraphs(self):
        self._exercise_text(433, 9, 44, 6, 10, 3, 5)

    def test_golf_wide_definition(self):
        self._exercise_definition(499, 7, 76, 55, 4, 11)

    def test_hotel_even_raw_mix(self):
        self._exercise_text(557, 6, 59, 2, 12, 7, 3)

    def test_india_tight_definition(self):
        self._exercise_definition(619, 8, 43, 46, 7, 9)

    def test_juliet_long_lines(self):
        self._exercise_text(683, 5, 81, 5, 13, 8, 4)

    def test_kilo_irregular_definition(self):
        self._exercise_definition(751, 9, 64, 61, 3, 14)

    def test_zulu_single_oversized_raw_tail(self):
        formatter = HelpFormatter(width=53)
        text = self._make_text(823, 7, 73, 2, 10, oversized=True)
        formatter.write_text(text)
        rendered = formatter.getvalue()
        self.assertTrue(rendered)
        self.assertIn("x", rendered)
        self.assertTrue(rendered.endswith("\n"))
