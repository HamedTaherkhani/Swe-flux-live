from __future__ import annotations

import argparse
import contextlib
import io
import os
import random
import string
import tempfile
import unittest
from pathlib import Path

from scrapy.commands.genspider import Command
from scrapy.exceptions import UsageError
from scrapy.settings import Settings


class TestGenspiderRunCallStructure(unittest.TestCase):
    def test_seeded_command_modes(self) -> None:
        rng = random.Random(8675309)
        modes = [mode for mode in range(9) for _ in range(5)]
        rng.shuffle(modes)
        alphabet = string.ascii_lowercase
        rolling = rng.randrange(1000, 10000)

        command = Command()
        command.settings = Settings(
            {
                "BOT_NAME": "benchmark_bot",
                "NEWSPIDER_MODULE": None,
                "TEMPLATES_DIR": None,
            }
        )

        generated_count = 0
        usage_errors = 0
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = Path.cwd()
            os.chdir(temp_dir)
            try:
                with contextlib.redirect_stdout(output):
                    for index, mode in enumerate(modes):
                        rolling = (
                            rolling * 73
                            + rng.randrange(17, 991)
                            + (index + 3) ** 2
                        ) % 104729
                        stem = "".join(
                            alphabet[
                                (rolling + index * 11 + offset * offset * 7)
                                % len(alphabet)
                            ]
                            for offset in range(6 + rolling % 7)
                        )
                        name = f"{stem}-{index}-{rolling % 97}"
                        domain = (
                            f"{stem}.{alphabet[(rolling // 7) % 26]}"
                            f"{alphabet[(rolling // 13) % 26]}.example/"
                            f"{(rolling * (index + 1)) % 1009}"
                        )

                        opts = argparse.Namespace(
                            list=mode == 0,
                            dump=(
                                "basic"
                                if mode == 1
                                else f"missing_{(rolling + index) % 113}"
                                if mode == 2
                                else None
                            ),
                            template=(
                                f"unknown_{(rolling * 3 + index) % 127}"
                                if mode == 8
                                else ("crawl" if rolling % 2 else "basic")
                            ),
                            force=mode in {6, 8},
                            edit=False,
                        )

                        if mode == 3:
                            args = [name] * (rolling % 2)
                        elif mode == 4:
                            args = [
                                "benchmark.bot" if rolling % 2 else "benchmark_bot",
                                domain,
                            ]
                        else:
                            args = [name, domain]

                        if mode == 7:
                            Path(name + ".py").write_text(
                                f"# occupied {(rolling + index) % 89}\n",
                                encoding="utf-8",
                            )

                        before = set(Path.cwd().glob("*.py"))
                        try:
                            command.run(args, opts)
                        except UsageError:
                            usage_errors += 1
                        after = set(Path.cwd().glob("*.py"))
                        generated_count += len(after - before)
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(usage_errors, modes.count(3))
        self.assertGreater(generated_count, len(modes) // 10)
        self.assertIn("template", output.getvalue().lower())

