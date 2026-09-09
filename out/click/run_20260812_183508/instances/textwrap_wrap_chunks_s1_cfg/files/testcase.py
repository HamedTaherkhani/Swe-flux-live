import random
import unittest

from click._textwrap import TextWrapper


class TestSeededChunkWrapping(unittest.TestCase):
    def test_three_direct_wrapping_profiles(self):
        rng = random.Random(62017)
        alphabet = "abcdefghijklmnpqrstuvwxyz"
        words = []

        for index in range(48):
            size = 3 + rng.randrange(24)
            letters = "".join(rng.choice(alphabet) for _ in range(size))
            if index % 7 == 2:
                letters = f"\x1b[{31 + index % 6}m{letters}\x1b[0m"
            words.append(letters)

        chunks = []
        for index, word in enumerate(words):
            chunks.append(word)
            if index + 1 < len(words):
                chunks.append(" " * (1 + rng.randrange(3)))

        invalid = TextWrapper(width=sum(len(word) for word in words[:0]))
        with self.assertRaises(ValueError):
            invalid._wrap_chunks(chunks[:])

        middle_chunks = chunks[:]
        exhaustive = TextWrapper(
            width=19 + rng.randrange(6),
            initial_indent="\x1b[36m>\x1b[0m ",
            subsequent_indent=" " * (1 + rng.randrange(3)),
            break_long_words=True,
            drop_whitespace=True,
        )
        lines = exhaustive._wrap_chunks(middle_chunks)

        self.assertTrue(lines)
        self.assertTrue(all(isinstance(line, str) for line in lines))
        self.assertGreater(len(lines), len(words) // 4)
        self.assertFalse(middle_chunks)

        limited_chunks = chunks[:]
        limited = TextWrapper(
            width=18 + rng.randrange(5),
            initial_indent="",
            subsequent_indent="  ",
            break_long_words=False,
            drop_whitespace=True,
            max_lines=3 + rng.randrange(3),
            placeholder=" [...]",
        )
        shortened = limited._wrap_chunks(limited_chunks)

        self.assertTrue(shortened)
        self.assertLessEqual(len(shortened), limited.max_lines)
        self.assertTrue(shortened[-1].rstrip().endswith(limited.placeholder.strip()))
