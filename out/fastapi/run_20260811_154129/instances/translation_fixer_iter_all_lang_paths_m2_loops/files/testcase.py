import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.translation_fixer import fix_all


class TestGeneratedTranslationTrees(unittest.TestCase):
    def test_fix_all_across_variable_language_trees(self):
        rng = random.Random("variable-language-tree-volume")
        language_sizes = rng.sample(range(34, 70), 7)
        priority_dirs = ("learn", "tutorial", "advanced", "about", "how-to")

        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                created = []
                languages = [
                    f"lang_{index}_{rng.randrange(1000, 10000)}"
                    for index in range(len(language_sizes))
                ]
                for language_index, (language, file_count) in enumerate(
                    zip(languages, language_sizes)
                ):
                    docs_root = Path("docs") / language / "docs"
                    for file_index in range(file_count):
                        selector = (file_index * 7 + language_index * 11) % 13
                        if selector == 0:
                            parent = docs_root
                        elif selector <= len(priority_dirs):
                            parent = (
                                docs_root
                                / priority_dirs[selector - 1]
                                / f"unit-{(file_index + language_index) % 9}"
                            )
                        else:
                            parent = (
                                docs_root
                                / f"section-{selector}"
                                / f"topic-{(file_index * 3 + language_index) % 11}"
                            )
                        path = parent / (
                            f"page-{file_index:03d}-"
                            f"{(file_index * file_index + language_index) % 97}.md"
                        )
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(
                            f"# Generated {language_index}:{file_index}\n",
                            encoding="utf-8",
                        )
                        created.append(path)

                with patch(
                    "scripts.translation_fixer.process_one_page", return_value=True
                ) as worker:
                    for language in languages:
                        fix_all(None, language)

                self.assertEqual(worker.call_count, len(created))
                self.assertGreater(len({path.parent for path in created}), 20)
                self.assertTrue(all(path.suffix == ".md" for path in created))
            finally:
                os.chdir(previous_cwd)
