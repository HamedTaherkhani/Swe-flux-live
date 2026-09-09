from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from kedro.framework.cli.jupyter import jupyter


class TestJupyterKernelExceptionEvents(unittest.TestCase):
    def test_mixed_kernel_setup_outcomes(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            invocation_counter = iter(range(24))

            def prepare_kernel(*, user, kernel_name, display_name):
                index = next(invocation_counter)
                kernel_directory = root / f"{index:02x}" / kernel_name
                kernel_directory.mkdir(parents=True)
                manifest = kernel_directory / "kernel.json"
                mode = index % len(range(8))

                if mode == 0:
                    manifest.write_text('{"argv": []}', encoding="utf-8")
                elif mode == 1:
                    manifest.write_text("{", encoding="utf-8")
                elif mode == 2:
                    pass
                elif mode == 3:
                    manifest.write_bytes(bytes([0x80 + (index % 32)]))
                elif mode == 4:
                    manifest.write_text("{}", encoding="utf-8")
                elif mode == 5:
                    manifest.write_text('{"argv": 9}', encoding="utf-8")
                elif mode == 6:
                    manifest.write_text("[]", encoding="utf-8")
                else:
                    manifest.mkdir()

                return str(kernel_directory)

            results = []
            runner = CliRunner()
            with (
                patch("ipykernel.kernelspec.install", side_effect=prepare_kernel),
                patch("kedro.framework.cli.jupyter._check_module_importable"),
                patch("kedro.framework.cli.jupyter.validate_settings"),
                patch("kedro.framework.cli.jupyter.shutil.copy", return_value=None),
            ):
                for index in range(24):
                    metadata = type(
                        "Metadata",
                        (),
                        {"package_name": f"pkg_{index * index + index:x}"},
                    )()
                    results.append(runner.invoke(jupyter, ["setup"], obj=metadata))

            exit_codes = [result.exit_code for result in results]
            self.assertEqual(len(exit_codes), len(range(24)))
            self.assertTrue(any(code == 0 for code in exit_codes))
            self.assertTrue(any(code != 0 for code in exit_codes))
            self.assertTrue(all(isinstance(result.output, str) for result in results))
