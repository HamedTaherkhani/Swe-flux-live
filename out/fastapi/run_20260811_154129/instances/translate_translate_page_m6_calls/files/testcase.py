import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


for module_name, exported_name in (
    ("doc_parsing_utils", "check_translation"),
    ("git", None),
    ("github", "Github"),
    ("pydantic_ai", "Agent"),
):
    if importlib.util.find_spec(module_name) is None:
        stub = types.ModuleType(module_name)
        if exported_name is not None:
            setattr(stub, exported_name, object)
        sys.modules[module_name] = stub

from scripts import translate


class TestIndirectTranslationBatch(unittest.TestCase):
    def test_generated_update_and_add_batch(self) -> None:
        class DeterministicAgent:
            total_runs = 0

            def __init__(self, model: str) -> None:
                self.model = model

            def run_sync(self, prompt: str):
                type(self).total_runs += 1
                prompt_score = len(prompt) * 31 + type(self).total_runs * 17
                output = (
                    f"# Generated {prompt_score % 10007}\n\n"
                    f"Batch pass {type(self).total_runs}.\n"
                )
                return type("AgentResult", (), {"output": output})()

        validation_counts: dict[str, int] = {}

        def deterministic_check(**kwargs) -> None:
            path = kwargs["path"]
            validation_counts[path] = validation_counts.get(path, 0) + 1
            required_attempts = (sum(map(ord, path)) % 3) + 1
            if validation_counts[path] < required_attempts:
                raise ValueError(
                    f"generated validation retry {validation_counts[path]}"
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            old_cwd = Path.cwd()
            try:
                os.chdir(temporary_directory)
                docs_root = Path("docs")
                (docs_root / "en" / "docs" / "generated").mkdir(parents=True)
                (docs_root / "zz").mkdir(parents=True)
                (docs_root / "language_names.yml").write_text(
                    "en: English\nzz: Test Language\n", encoding="utf-8"
                )
                (docs_root / "zz" / "llm-prompt.md").write_text(
                    "Preserve generated markers and heading depth.\n",
                    encoding="utf-8",
                )

                source_paths = []
                for index in range(8):
                    shard = (index * 17 + index * index) % 29
                    source_path = (
                        docs_root
                        / "en"
                        / "docs"
                        / "generated"
                        / f"page-{index:02d}-{shard:02d}.md"
                    )
                    source_path.write_text(
                        "\n".join(
                            [
                                f"# Generated page {index}",
                                "",
                                *[
                                    f"Section {row}: {(index + 3) * (row + 5) % 97}"
                                    for row in range(7)
                                ],
                            ]
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    source_paths.append(source_path)

                for source_path in source_paths[:4]:
                    translated_path = Path(
                        str(source_path).replace("docs/en/docs", "docs/zz/docs")
                    )
                    translated_path.parent.mkdir(parents=True, exist_ok=True)
                    translated_path.write_text(
                        f"# Previous {source_path.stem}\n", encoding="utf-8"
                    )

                translate.get_langs.cache_clear()
                with (
                    mock.patch.object(
                        translate, "list_outdated", return_value=source_paths[:4]
                    ),
                    mock.patch.object(
                        translate, "list_missing", return_value=source_paths[4:]
                    ),
                    mock.patch.object(translate, "Agent", DeterministicAgent),
                    mock.patch.object(
                        translate, "check_translation", deterministic_check
                    ),
                ):
                    translate.update_and_add(language="zz", max=4)

                translated_files = sorted(
                    (docs_root / "zz" / "docs" / "generated").glob("*.md")
                )
                self.assertEqual(len(translated_files), len(source_paths))
                self.assertTrue(
                    all(path.read_text(encoding="utf-8").endswith("\n") for path in translated_files)
                )
                self.assertGreater(DeterministicAgent.total_runs, len(source_paths))
                self.assertEqual(set(validation_counts), {str(path).replace("docs/en/docs", "docs/zz/docs") for path in source_paths})
            finally:
                os.chdir(old_cwd)
