from datetime import date
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import scripts.add_latest_release_date as release_dates


class TestAddLatestReleaseDateDataFlow(unittest.TestCase):
    def test_generated_release_note_variants(self) -> None:
        seed = sum(ord(char) for char in "release-note-dataflow-variant-hard")
        rng = random.Random(seed)
        entry_count = seed % 200 + 500

        def generated_entries(tag: str) -> list[str]:
            return [
                (
                    f"{'#' * rng.choice((1, 2, 3, 4, 5, 6, 7, 8))} "
                    f"{tag}-{index:x}-{rng.randrange(100, 99999)}\n"
                )
                for index in range(entry_count)
            ]

        version_parts = [rng.randrange(10, 99) for _ in range(3)]
        version = ".".join(str(part) for part in version_parts)
        dated_header = (
            f"## {version} "
            f"({2000 + len('extended')}-0{len('variant')}-0{len('benchmark')})\n"
        )
        undated_header = f"## {version}\n"

        dated_notes = generated_entries("dated")
        dated_notes.insert((entry_count * 19) // 20, dated_header)
        undated_notes = generated_entries("undated")
        undated_notes.insert((entry_count * 17) // 20, undated_header)
        headerless_notes = generated_entries("headerless")

        class FixedDate(date):
            @classmethod
            def today(cls) -> "FixedDate":
                return cls(
                    2000 + len("heterogeneous-input"),
                    len("complexity"),
                    len("trace-depth"),
                )

        with tempfile.TemporaryDirectory() as directory:
            notes_path = Path(directory) / "release-notes.md"
            with (
                patch.object(release_dates, "RELEASE_NOTES_FILE", str(notes_path)),
                patch.object(release_dates, "date", FixedDate),
            ):
                notes_path.write_text("".join(dated_notes), encoding="utf-8")
                with self.assertRaises(SystemExit) as dated_exit:
                    release_dates.main()
                self.assertEqual(dated_exit.exception.code, 0)
                self.assertEqual(
                    notes_path.read_text(encoding="utf-8"),
                    "".join(dated_notes),
                )

                notes_path.write_text("".join(undated_notes), encoding="utf-8")
                with self.assertRaises(SystemExit) as undated_exit:
                    release_dates.main()
                self.assertEqual(undated_exit.exception.code, 0)
                rewritten = notes_path.read_text(encoding="utf-8")
                self.assertNotEqual(rewritten, "".join(undated_notes))
                self.assertEqual(len(rewritten.splitlines()), len(undated_notes))

                notes_path.write_text("".join(headerless_notes), encoding="utf-8")
                with self.assertRaises(SystemExit) as missing_exit:
                    release_dates.main()
                self.assertNotEqual(missing_exit.exception.code, 0)
                self.assertEqual(
                    notes_path.read_text(encoding="utf-8"),
                    "".join(headerless_notes),
                )
