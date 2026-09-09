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
        rng = random.Random(1234567)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs_root = root / "localized"
            index_path = docs_root / "docs" / "index.md"
            data_path = docs_root / "data"
            index_path.parent.mkdir(parents=True)
            data_path.mkdir(parents=True)

            sponsor_rows = []
            for position in range(36):
                tier = ("keystone", "gold", "silver", "gold", "silver")[
                    position % 5
                ]
                token = rng.randrange(50_000, 9_999_999)
                sponsor_rows.append(
                    (
                        tier,
                        f"Partner {position}-{token}-tier-{tier[0]}",
                        f"https://partner.invalid/{position}/{token}",
                        f"/img/sponsors/{token % 10000}.svg",
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
                    for invocation in range(38):
                        selector = (
                            invocation * 31 + rng.randrange(0, 251)
                        ) % 9
                        include_sponsors = selector not in {0, 4}
                        include_style = selector not in {2, 4}
                        nonce = rng.randrange(10_000_000, 99_999_999)

                        sections = [
                            f"# Generated {invocation} {{#generated-{nonce}}}",
                            f"## Track {invocation % 7} {{#track-{nonce % 8191}}}",
                            f"### Node {nonce % 137} {{#node-{invocation ^ (nonce & 0xFFFF)}}}",
                            f"#### Leaf {nonce % 53} {{#leaf-{invocation * 3 + nonce % 997}}}",
                            f"Prelude {nonce}",
                        ]
                        if include_style:
                            sections.extend(
                                (
                                    "<style>",
                                    f"body {{ color: rgb({nonce % 256}, {(nonce >> 8) % 256}, {(nonce >> 16) % 256}); }}",
                                    f".banner-{{invocation}} {{ margin: {nonce % 17}px; }}",
                                    "</style>",
                                    "",
                                )
                            )
                        sections.append(
                            f"Narrative {nonce ^ (invocation << 5)} slice {nonce % 9973}"
                        )
                        if include_sponsors:
                            sections.extend(
                                (
                                    "<!-- sponsors -->",
                                    f"stale sponsor block {nonce % 7919} alt {invocation * 13}",
                                    f"backup line {nonce // 29} marker {invocation % 23}",
                                    "<!-- /sponsors -->",
                                )
                            )
                        sections.extend(
                            (
                                "<!-- only-mkdocs -->",
                                f"private navigation {nonce // 13} lane {invocation % 11}",
                                f"hidden route {nonce % 1543} depth {invocation // 4}",
                                "<!-- /only-mkdocs -->",
                                f"Closing {nonce + invocation * invocation} tail {nonce % 3571}",
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
            self.assertEqual(observed_exits + observed_errors, 38)
            self.assertGreater(observed_exits, observed_errors)