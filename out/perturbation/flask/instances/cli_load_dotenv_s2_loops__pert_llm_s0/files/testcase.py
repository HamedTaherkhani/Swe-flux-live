import os
import random
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner
from flask.cli import cli


class TestLoadDotenvLoopBehavior(unittest.TestCase):
    def test_cli_merges_generated_env_files(self) -> None:
        rng = random.Random(90421)
        prefix = "REPOBEHAVE_DOTENV_"

        def build_lines(salt: int) -> list[tuple[str, str | None]]:
            rows: list[tuple[str, str | None]] = []

            for position in range(331):
                index = (rng.randrange(503) + salt * position + position**2) % 503
                key = f"{prefix}{index:03d}"
                value = None if (index + position + salt) % 4 == 0 else (
                    f"v_{salt}_{position}_{(index * 23 + position) % 1597}"
                )
                rows.append((key, value))

            return rows

        generated = [build_lines(salt) for salt in (5, 17, 23)]
        all_keys = {key for rows in generated for key, _ in rows}
        protected_key = sorted(all_keys)[len(all_keys) // 7]
        old_cwd = os.getcwd()

        try:
            for key in all_keys:
                os.environ.pop(key, None)

            os.environ[protected_key] = "kept-from-process"

            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)

                for path, rows in zip(
                    (root / ".flaskenv", root / ".env", root / "selected.env"),
                    generated,
                ):
                    path.write_text(
                        "\n".join(
                            key if value is None else f"{key}={value}"
                            for key, value in rows
                        )
                        + "\n",
                        encoding="utf-8",
                    )

                os.chdir(root)
                result = CliRunner().invoke(
                    cli, ["--env-file", str(root / "selected.env"), "--help"]
                )

                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(os.environ[protected_key], "kept-from-process")
                self.assertIn("Usage:", result.output)
                self.assertTrue(any(key in os.environ for key in all_keys))
        finally:
            os.chdir(old_cwd)

            for key in all_keys:
                os.environ.pop(key, None)


