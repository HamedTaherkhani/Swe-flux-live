import contextlib
import io
import os
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

slugify_module = types.ModuleType("slugify")
slugify_module.slugify = lambda value: str(value)  # type: ignore[attr-defined]
sys.modules.setdefault("slugify", slugify_module)

from scripts import docs


class TestGeneratedReadmeDataFlow(unittest.TestCase):
    def test_generated_docs_variants_through_readme_command(self) -> None:
        rng = random.Random(581304)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs_root = root / "localized"
            index_path = docs_root / "docs" / "index.md"
            data_path = docs_root / "data"
            index_path.parent.mkdir(parents=True)
            data_path.mkdir(parents=True)

            sponsor_rows = []
            for position in range(18):
                tier = ("keystone", "gold", "silver")[position % 3]
                token = rng.randrange(100_000, 1_000_000)
                sponsor_rows.append(
                    (
                        tier,
                        f"Partner {position}-{token}",
                        f"https://partner.invalid/{token}",
                        f"/img/{token}.svg",
                    )
                )

            yaml_lines = []
            for tier in ("keystone", "gold", "silver"):
                yaml_lines.append(f"{tier}:")
                for row_tier, title, url, image in sponsor_rows:
                    if row_tier == tier:
                        yaml_lines.extend(
                            (
                                f"  - title: {title}",
                                f"    url: {url}",
                                f"    img: {image}",
                            )
                        )
            (data_path / "sponsors.yml").write_text(
                "\n".join(yaml_lines) + "\n", encoding="utf-8"
            )
            (root / "README.md").write_text("bootstrap\n", encoding="utf-8")

            observed_exits = 0
            observed_errors = 0
            expected_exits = 0
            expected_errors = 0
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(docs, "en_docs_path", docs_root):
                    for invocation in range(24):
                        selector = (
                            invocation * 17 + rng.randrange(0, 97)
                        ) % 9
                        include_sponsors = selector not in {0, 4}
                        include_style = selector not in {2, 4}
                        nonce = rng.randrange(10_000_000, 99_999_999)

                        sections = [
                            f"# Generated {invocation} {{#generated-{nonce}}}",
                            f"Prelude {nonce}",
                        ]
                        if include_style:
                            sections.extend(("<style>", "body { color: navy; }", "</style>", ""))
                        sections.append(f"Narrative {nonce ^ (invocation << 5)}")
                        if include_sponsors:
                            sections.extend(
                                (
                                    "<!-- sponsors -->",
                                    f"stale sponsor block {nonce % 7919}",
                                    "<!-- /sponsors -->",
                                )
                            )
                        sections.extend(
                            (
                                "<!-- only-mkdocs -->",
                                f"private navigation {nonce // 13}",
                                "<!-- /only-mkdocs -->",
                                f"Closing {nonce + invocation * invocation}",
                            )
                        )
                        index_path.write_text(
                            "\n".join(sections) + "\n", encoding="utf-8"
                        )

                        if include_sponsors and include_style:
                            expected_exits += 1
                        else:
                            expected_errors += 1

                        try:
                            with contextlib.redirect_stdout(io.StringIO()):
                                docs.generate_readme()
                        except Exception as exc:
                            if hasattr(exc, "exit_code"):
                                observed_exits += 1
                            else:
                                observed_errors += 1
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(observed_exits, expected_exits)
            self.assertEqual(observed_errors, expected_errors)
            self.assertEqual(observed_exits + observed_errors, 24)
            self.assertGreater(observed_exits, observed_errors)
