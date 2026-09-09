import random
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


for module_name, attribute_name in (
    ("git", "Repo"),
    ("github", "Github"),
    ("pydantic_ai", "Agent"),
    ("doc_parsing_utils", "check_translation"),
):
    if module_name not in sys.modules:
        stub = types.ModuleType(module_name)
        setattr(stub, attribute_name, type(attribute_name, (), {}))
        sys.modules[module_name] = stub

from scripts import translate


class GeneratedTranslationPath:
    def __init__(self, index, present):
        self.index = index
        self.present = present

    def exists(self):
        return self.present

    def __repr__(self):
        return f"GeneratedTranslationPath(index={self.index}, present={self.present})"


class GeneratedCommit:
    def __init__(self, committed_datetime):
        self.committed_datetime = committed_datetime


class GeneratedRepo:
    def __init__(self, english_values, translated_values):
        self.english_values = english_values
        self.translated_values = translated_values
        self.iter_calls = []

    def iter_commits(self, *, paths, max_count):
        self.iter_calls.append((paths, max_count))
        if isinstance(paths, GeneratedTranslationPath):
            value = self.translated_values[paths.index]
        else:
            value = self.english_values[int(paths.stem.split("_")[1])]
        return iter((GeneratedCommit(value),))


class TestTranslationMaintenanceInvariants(unittest.TestCase):
    def test_generated_translation_maintenance(self):
        rng = random.Random(sum(ord(char) for char in "translation-maintenance") * 97)
        item_count = rng.randrange(45, 56)
        scores = {
            index: rng.randrange(10_000, 1_000_000) ^ (index * 7919)
            for index in range(item_count)
        }
        english_paths = [
            Path(f"docs/en/docs/generated/page_{index}_{scores[index] % 997}.md")
            for index in range(item_count)
        ]
        present = {
            index: (scores[index] + index * index) % 9 not in (0, 4)
            for index in range(item_count)
        }
        present_indices = [index for index, value in present.items() if value]
        exceptional_index = present_indices[
            sum(scores[index] % 13 for index in present_indices) % len(present_indices)
        ]

        english_values = {
            index: 2_000_000 + scores[index] * 3 + index * 101
            for index in range(item_count)
        }
        translated_values = {
            index: english_values[index] + ((scores[index] % 11) - 5)
            for index in present_indices
        }
        translated_values[exceptional_index] += 37 + scores[exceptional_index] % 29

        generated_paths = {
            index: GeneratedTranslationPath(index, present[index])
            for index in range(item_count)
        }
        repo = GeneratedRepo(english_values, translated_values)
        translated = []

        def make_language_path(*, lang, path):
            self.assertEqual(lang, "zz")
            return generated_paths[int(path.stem.split("_")[1])]

        with (
            patch.object(translate.git, "Repo", return_value=repo),
            patch.object(
                translate,
                "iter_en_paths_to_translate",
                side_effect=lambda: iter(english_paths),
            ),
            patch.object(
                translate,
                "generate_lang_path",
                side_effect=make_language_path,
            ),
            patch.object(
                translate,
                "translate_page",
                side_effect=lambda **kwargs: translated.append(kwargs),
            ),
        ):
            translate.update_and_add(language="zz", max=item_count)

        self.assertGreater(len(translated), 2)
        self.assertTrue(all(item["language"] == "zz" for item in translated))
        self.assertGreater(len(repo.iter_calls), item_count)
        self.assertTrue(all(max_count == 1 for _, max_count in repo.iter_calls))
