import io
import random
import unittest

from rich.console import Console
from rich.text import Text


def _build_wrapped_document(seed: int, line_count: int) -> Text:
    """Build a multi-line styled document for word wrapping."""
    rng = random.Random(seed)
    vocabulary = (
        "alpha beta gamma delta epsilon zeta eta theta iota kappa "
        "lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega"
    ).split()
    document = Text()
    cursor = 0
    for index in range(line_count):
        word_total = rng.randint(4, 9)
        chosen = [rng.choice(vocabulary) for _ in range(word_total)]
        row = " ".join(chosen)
        row_start = cursor
        document.append(row + "\n")
        row_end = cursor + len(row)
        if index % 3 == 0:
            document.stylize("bold", row_start + 1, row_end - 1)
        elif index % 3 == 1:
            document.stylize("italic", row_start + 2, row_end - 2)
        cursor = row_end + 1
    return document


class TestTextWrapLoops(unittest.TestCase):
    def test_wrap_preserves_styled_lines(self) -> None:
        document = _build_wrapped_document(seed=42, line_count=25)
        console = Console(width=79, record=True, file=io.StringIO())
        wrapped = document.wrap(console, width=12)

        self.assertGreater(len(wrapped), 50)
        self.assertGreater(sum(len(line.plain) for line in wrapped), 500)
        self.assertTrue(all(line.plain for line in wrapped[:10]))
