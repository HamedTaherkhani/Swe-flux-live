import hashlib
import random
import string
import unittest
from pathlib import Path
from unittest.mock import patch

import typer

from scripts import translation_fixer


class TestTranslationFixAllInvariants(unittest.TestCase):
    def test_seeded_page_outcomes(self):
        rng = random.Random(987654321)
        page_count = 230 + rng.randrange(20)
        alphabet = string.ascii_lowercase + string.ascii_uppercase + string.digits
        pages = []
        for index in range(page_count):
            width = 3 + rng.randrange(30)
            token = "".join(rng.choice(alphabet) for _ in range(width))
            pages.append(f"section-{index % 17}/sub-{index % 7}/{token}-{index:x}.md")

        observed_paths = []

        def seeded_result(path: Path) -> bool:
            observed_paths.append(path)
            digest = hashlib.blake2s(
                path.as_posix().encode("utf-8"), digest_size=8
            ).digest()
            score = int.from_bytes(digest, "big") ^ len(observed_paths) ** 3
            return score % 11 not in {0, 1, 4, 6}

        with (
            patch.object(translation_fixer, "get_all_paths", return_value=pages),
            patch.object(
                translation_fixer, "process_one_page", side_effect=seeded_result
            ),
        ):
            with self.assertRaises(typer.Exit):
                translation_fixer.fix_all(object(), "zz")

        self.assertEqual(
            [path.relative_to(Path("docs") / "zz" / "docs").as_posix() for path in observed_paths],
            pages,
        )
