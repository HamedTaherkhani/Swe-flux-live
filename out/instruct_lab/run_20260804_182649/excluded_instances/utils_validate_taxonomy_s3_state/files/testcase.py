import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from instructlab import lab


class TestTaxonomyState(unittest.TestCase):
    def test_generated_directory_via_cli(self):
        runner = CliRunner()

        with runner.isolated_filesystem():
            root = Path("generated-taxonomy")
            for index in range(23):
                branch = "".join(
                    chr(97 + ((index * 7 + offset * 11) % 26))
                    for offset in range(9)
                )
                destination = root / f"compositional_skills/{branch}/qna.yaml"
                destination.parent.mkdir(parents=True, exist_ok=True)
                coefficients = [
                    (index * index + position * 13 + index * position * 3) % 97
                    for position in range(31)
                ]
                destination.write_text(
                    "\n".join(
                        f"{position:02x}:{value:02x}:{(value * (position + 5)) % 101:02x}"
                        for position, value in enumerate(coefficients)
                    ),
                    encoding="utf-8",
                )

            def discover(directory):
                base = Path(directory)
                return sorted(
                    str(path.relative_to(base))
                    for path in base.rglob("qna.yaml")
                )

            def inspect_file(file_path, _rules):
                payload = Path(file_path).read_bytes()
                weighted = sum(
                    (position + 1) * byte for position, byte in enumerate(payload)
                )
                warnings = (weighted ^ len(payload)) % 7
                errors = ((weighted // 11) + payload[0]) % 5
                return warnings, errors

            with (
                mock.patch("instructlab.utils.get_taxonomy", side_effect=discover),
                mock.patch(
                    "instructlab.utils.validate_taxonomy_file",
                    side_effect=inspect_file,
                ) as validator,
            ):
                result = runner.invoke(
                    lab.ilab,
                    [
                        "--config=DEFAULT",
                        "taxonomy",
                        "diff",
                        "--quiet",
                        "--taxonomy-base",
                        "empty",
                        "--taxonomy-path",
                        str(root),
                    ],
                )

            self.assertNotEqual(result.exit_code, 0)
            self.assertEqual(validator.call_count, len(discover(root)))
