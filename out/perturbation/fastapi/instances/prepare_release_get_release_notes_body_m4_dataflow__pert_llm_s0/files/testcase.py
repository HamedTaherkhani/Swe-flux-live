import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_release


class TestReleaseNotesBodyDataFlow(unittest.TestCase):
    def test_generated_release_note_layouts(self):
        rng = random.Random(0xC0FFEE42)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            version_file = root / "version.py"
            release_notes_file = root / "release-notes.md"
            successful_outputs = []
            rejected_layouts = 0

            for index in range(192):
                components = (
                    137 + index * 5,
                    (index * 13 + rng.randrange(47)) % 163,
                    (index * index * 3 + rng.randrange(71)) % 307,
                )
                version = ".".join(str(component) for component in components)
                version_file.write_text(
                    f'__version__ = "{version}"\n', encoding="utf-8"
                )
                words = [
                    "".join(
                        chr(ord("a") + rng.randrange(26))
                        for _ in range(3 + (word_index % 13))
                    )
                    for word_index in range(31 + index * 3)
                ]
                release_year = 2017 + (index % 9)
                release_month = (index % 12) + 1
                release_day = (index % 27) + 1
                dated_heading = (
                    f"## {version} ({release_year}-{release_month:02d}-{release_day:02d})"
                )
                plain_heading = f"## {version}"
                heading = dated_heading if index % 3 else plain_heading
                mode = index % 4
                if mode == 0:
                    notes = (
                        "# Generated\n\n"
                        + heading
                        + "\n\n"
                        + "\n".join(words)
                        + f"\n\n## {components[0] - 1}.0.0 ({release_year - 1}-11-30)\n\nOlder material\n"
                    )
                elif mode == 1:
                    trailing = (
                        f"\n\n## {components[0] + 2}.{components[1]}.{components[2]} ({release_year}-01-01)\n\nTrailing section\n"
                        if index % 2
                        else "\n"
                    )
                    notes = (
                        "# Generated\n\n"
                        + heading
                        + "\n\n"
                        + "\n".join(reversed(words))
                        + trailing
                    )
                elif mode == 2:
                    notes = (
                        "# Generated\n\n"
                        + f"## {components[0] + 1}.0.0 ({release_year}-03-14)\n\n"
                        + "\n".join(words)
                        + "\n"
                    )
                else:
                    notes = (
                        "# Generated\n\n"
                        + heading
                        + "\n \n\t\n"
                        + f"## {components[0] - 1}.0.0 ({release_year - 2}-07-04)\n\nOlder material\n"
                    )
                release_notes_file.write_text(notes, encoding="utf-8")

                with patch.object(prepare_release.typer, "echo") as echo:
                    if mode < 2:
                        prepare_release.release_notes(
                            version_file, release_notes_file
                        )
                        successful_outputs.append(echo.call_args.args[0])
                    else:
                        with self.assertRaises(RuntimeError):
                            prepare_release.release_notes(
                                version_file, release_notes_file
                            )
                        rejected_layouts += 1

            self.assertEqual(len(successful_outputs), rejected_layouts)
            self.assertTrue(all(output.endswith("\n") for output in successful_outputs))
            self.assertGreater(sum(map(len, successful_outputs)), len(successful_outputs))
