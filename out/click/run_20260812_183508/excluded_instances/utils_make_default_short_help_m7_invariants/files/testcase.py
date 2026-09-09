import unittest

from click.utils import _make_default_short_help


class TestGeneratedShortHelp(unittest.TestCase):
    def _build_help(
        self,
        seed,
        word_count,
        sentence_period,
        whitespace_cycle,
        paragraph_at=None,
        marker=False,
        unicode_at=None,
    ):
        state = seed
        words = []
        for index in range(word_count):
            state = (state * 109 + index * 37 + 41) % 65521
            width = 2 + state % 11
            chars = []
            for offset in range(width):
                state = (state * 73 + offset * 21 + seed) % 65521
                chars.append(chr(ord("a") + state % 26))
            if index == unicode_at:
                chars[len(chars) // 2] = chr(0x400 + state % 64)
            word = "".join(chars)
            if sentence_period and (index + seed) % sentence_period == 0:
                word += "."
            words.append(word)

        separators = (" ", "  ", "\t", "\n")
        pieces = []
        for index, word in enumerate(words):
            if index:
                pieces.append(separators[(index + whitespace_cycle) % len(separators)])
            pieces.append(word)
            if paragraph_at is not None and index == paragraph_at:
                pieces.append("\n\nignored-" + str((state * 17) % 1009))
                break
        text = "".join(pieces)
        if marker:
            text = "\b \t" + text
        return text

    def _exercise(self, **kwargs):
        max_length = kwargs.pop("max_length")
        help_text = self._build_help(**kwargs)
        result = _make_default_short_help(help_text, max_length=max_length)
        self.assertIsInstance(result, str)
        self.assertTrue(result)
        self.assertNotIn("\n", result)
        self.assertLessEqual(len(result), max_length)

    def test_alpha_dense_truncation(self):
        self._exercise(seed=127, word_count=47, sentence_period=17, whitespace_cycle=1, max_length=39)

    def test_bravo_late_sentence(self):
        self._exercise(seed=211, word_count=53, sentence_period=23, whitespace_cycle=2, max_length=71)

    def test_charlie_marker_prefix(self):
        self._exercise(seed=307, word_count=41, sentence_period=18, whitespace_cycle=3, marker=True, max_length=52)

    def test_delta_first_paragraph(self):
        self._exercise(seed=401, word_count=59, sentence_period=29, whitespace_cycle=0, paragraph_at=33, max_length=83)

    def test_echo_tight_limit(self):
        self._exercise(seed=503, word_count=37, sentence_period=13, whitespace_cycle=2, max_length=24)

    def test_foxtrot_wide_limit(self):
        self._exercise(seed=601, word_count=67, sentence_period=32, whitespace_cycle=1, max_length=96)

    def test_golf_frequent_sentences(self):
        self._exercise(seed=709, word_count=43, sentence_period=11, whitespace_cycle=3, max_length=63)

    def test_hotel_paragraph_marker(self):
        self._exercise(seed=809, word_count=71, sentence_period=37, whitespace_cycle=0, paragraph_at=38, marker=True, max_length=78)

    def test_india_long_words(self):
        self._exercise(seed=907, word_count=61, sentence_period=26, whitespace_cycle=2, max_length=46)

    def test_juliet_exactish_boundary(self):
        self._exercise(seed=1009, word_count=49, sentence_period=21, whitespace_cycle=1, max_length=57)

    def test_kilo_short_first_paragraph(self):
        self._exercise(seed=1103, word_count=73, sentence_period=34, whitespace_cycle=3, paragraph_at=22, max_length=69)

    def test_zulu_unicode_tail_run(self):
        self._exercise(seed=1201, word_count=79, sentence_period=47, whitespace_cycle=0, unicode_at=2, max_length=168)
