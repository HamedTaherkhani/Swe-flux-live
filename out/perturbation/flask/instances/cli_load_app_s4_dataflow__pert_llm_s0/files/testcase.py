import random
import sys
import unittest
from pathlib import Path

from click.testing import CliRunner
from flask import Flask
from flask.cli import FlaskGroup, cli


def make_application(label: str) -> Flask:
    app = Flask(label, static_folder=None)

    for index in range(89):
        endpoint = f"generated_{index}_{(index * index + len(label)) % 127}"
        app.add_url_rule(
            f"/items/{index}/<int:value>",
            endpoint=endpoint,
            view_func=lambda value: str(value),
        )

        @app.cli.command(name=f"task-{index:02d}")
        def generated_command() -> None:
            pass

    return app


class LoadAppDataFlowTest(unittest.TestCase):
    def test_generated_cli_sessions(self) -> None:
        rng = random.Random(577_215)
        runner = CliRunner()
        successful_sessions = 0

        for session in range(96):
            mode = (rng.randrange(2000) + session * 17 + 3) % 4
            use_help = (rng.randrange(2000) ^ (session * 7)) % 5 == 0

            with runner.isolated_filesystem():
                for module_name in ("app", "wsgi"):
                    sys.modules.pop(module_name, None)

                module_source = (
                    "from testcase import make_application\n"
                    "def create_app():\n"
                    f"    return make_application('factory-{session}')\n"
                    f"application = make_application('module-{session}')\n"
                )
                Path("app.py").write_text(module_source, encoding="utf-8")

                if mode == 0:
                    Path("wsgi.py").write_text(module_source, encoding="utf-8")

                if mode == 1:
                    command = FlaskGroup(
                        create_app=lambda s=session: make_application(
                            f"factory-{s * s + 1}"
                        ),
                        set_debug_flag=(session % 5 != 2),
                    )
                    args = ["--help"] if use_help else ["routes"]
                elif mode == 2:
                    command = cli
                    args = ["--app", "app:application"]
                    args.append("--help" if use_help else "routes")
                else:
                    command = cli
                    args = ["--help"] if use_help else ["routes"]

                result = runner.invoke(command, args, catch_exceptions=False)
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertTrue(
                    "Usage:" in result.output or "Endpoint" in result.output
                )
                successful_sessions += bool(result.output)

        self.assertEqual(successful_sessions, session + 1)
