import unittest

from click.testing import CliRunner

from instructlab import lab


class TestGeneratedTrainHelp(unittest.TestCase):
    def test_programmatic_train_help(self):
        runner = CliRunner()
        command_path = ["model", "".join(chr(code) for code in (116, 114, 97, 105, 110))]
        arguments = [
            "--config="
            + "".join(chr(code) for code in (68, 69, 70, 65, 85, 76, 84))
        ]
        arguments.extend(command_path)
        arguments.append("--" + "".join(chr(code) for code in (104, 101, 108, 112)))

        result = runner.invoke(lab.ilab, arguments)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(result.exception)
        self.assertGreater(result.output.count("--"), len(command_path) * 12)
