import shutil
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

if "slugify" not in sys.modules:
    slugify_module = types.ModuleType("slugify")
    slugify_module.slugify = lambda value, **_kwargs: value
    sys.modules["slugify"] = slugify_module

import scripts.docs as docs


class GeneratedStylesheet:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def lstrip(self, characters: str) -> str:
        return {}[self.payload]


class TestZensicalDocsFailure(unittest.TestCase):
    def test_programmatic_translation_failure(self) -> None:
        runtime_root = Path.cwd() / ".qa_runtime" / "zensical_exception_case"
        shutil.rmtree(runtime_root, ignore_errors=True)

        docs_root = runtime_root / "documentation"
        english_root = docs_root / "en"
        english_docs = english_root / "docs"
        language = "".join(chr(value) for value in (102, 114))
        translated_docs = docs_root / language / "docs"
        stage_root = runtime_root / "stage"

        english_docs.mkdir(parents=True)
        translated_docs.mkdir(parents=True)
        (stage_root / "docs_src").mkdir(parents=True)
        for asset_directory in ("data", "overrides"):
            asset_path = english_root / asset_directory
            asset_path.mkdir(parents=True)
            (asset_path / "generated.txt").write_text(
                f"{asset_directory}:{sum(range(9))}",
                encoding="utf-8",
            )
        (docs_root / "missing-translation.md").write_text(
            "This page still needs translation.", encoding="utf-8"
        )
        (english_docs / "translation-banner.md").write_text(
            "Read the source at ENGLISH_VERSION_URL.", encoding="utf-8"
        )

        relative_paths = [
            Path("guides") / f"topic_{index:02d}.md" for index in range(36)
        ]
        for index, relative_path in enumerate(relative_paths):
            source = english_docs / relative_path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                f"# Topic {index}\n\nEnglish body {index * index + 3}.",
                encoding="utf-8",
            )
            if (index * 7 + 5) % 4 != 0:
                translated = translated_docs / relative_path
                translated.parent.mkdir(parents=True, exist_ok=True)
                translated.write_text(
                    f"# Sujet {index}\n\nCorps traduit {index * 13 + 9}.",
                    encoding="utf-8",
                )

        for index in range(6):
            reference = english_docs / "reference" / f"generated_{index}.md"
            reference.parent.mkdir(parents=True, exist_ok=True)
            reference.write_text(f"# Reference {index}\n", encoding="utf-8")

        payload = bytes(
            97 + ((position * 11 + 7) % 26) for position in range(29)
        ).decode("ascii")

        def generated_config() -> dict:
            return {
                "theme": {
                    "logo": "assets/logo.svg",
                    "favicon": "assets/favicon.png",
                },
                "extra_css": [GeneratedStylesheet(payload)],
                "extra_javascript": [
                    f"assets/generated-{index}.js" for index in range(4)
                ],
            }

        caught = None
        with (
            mock.patch.object(docs, "docs_path", docs_root),
            mock.patch.object(docs, "en_docs_path", english_root),
            mock.patch.object(docs, "zensical_src_path", stage_root),
            mock.patch.object(docs, "render_banner_sponsors", return_value=None),
            mock.patch.object(
                docs, "get_updated_config_content", side_effect=generated_config
            ),
            mock.patch.object(docs, "build_zensical_config") as build_command,
        ):
            try:
                docs.build_lang(language)
            except BaseException as error:
                caught = error

        self.assertIsNotNone(caught)
        self.assertFalse(build_command.called)
        staged_markdown = list((stage_root / language / "content").rglob("*.md"))
        self.assertGreater(len(staged_markdown), len(relative_paths))
        shutil.rmtree(runtime_root)


if __name__ == "__main__":
    unittest.main()
