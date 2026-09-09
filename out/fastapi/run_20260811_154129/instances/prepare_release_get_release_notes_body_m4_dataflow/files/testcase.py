import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_release


class TestReleaseNotesBodyDataFlow(unittest.TestCase):
    def test_generated_release_note_layouts(self):
        rng = random.Random(314159)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            version_file = root / "version.py"
            release_notes_file = root / "release-notes.md"
            successful_outputs = []
            rejected_layouts = 0

            for index in range(32):
                components = (
                    20 + index,
                    (index * 7 + rng.randrange(11)) % 31,
                    (index * index + rng.randrange(17)) % 37,
                )
                version = ".".join(str(component) for component in components)
                version_file.write_text(
                    f'__version__ = "{version}"\n', encoding="utf-8"
                )
                words = [
                    "".join(
                        chr(ord("a") + rng.randrange(26))
                        for _ in range(5 + (word_index % 6))
                    )
                    for word_index in range(18 + index)
                ]
                heading = f"## {version}"
                mode = index % 4
                if mode == 0:
                    notes = (
                        "# Generated\n\n"
                        + heading
                        + "\n\n"
                        + "\n".join(words)
                        + f"\n\n## {components[0] - 1}.0.0\n\nOlder material\n"
                    )
                elif mode == 1:
                    notes = (
                        "# Generated\n\n"
                        + heading
                        + "\n\n"
                        + "\n".join(reversed(words))
                        + "\n"
                    )
                elif mode == 2:
                    notes = (
                        "# Generated\n\n"
                        + f"## {components[0] + 1}.0.0\n\n"
                        + "\n".join(words)
                        + "\n"
                    )
                else:
                    notes = (
                        "# Generated\n\n"
                        + heading
                        + "\n \n\t\n"
                        + f"## {components[0] - 1}.0.0\n\nOlder material\n"
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
