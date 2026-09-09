import logging
import random
import unittest

from flask import Blueprint
from flask import Flask
from flask import request
from flask.debughelpers import explain_template_loading_attempts
from jinja2 import FileSystemLoader
from werkzeug.routing import Rule


class _MessageCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class TestGeneratedTemplateLoadingAttempts(unittest.TestCase):
    def test_three_generated_diagnostic_runs(self) -> None:
        rng = random.Random(418_763)
        app = Flask("qa_template_diagnostics")
        blueprints = [
            Blueprint(f"section_{index}", f"qa_section_{index}")
            for index in range(7)
        ]
        collector = _MessageCollector()
        app.logger.addHandler(collector)
        app.logger.setLevel(logging.INFO)

        def build_attempts(size: int, phase: int):
            attempts = []
            rolling = rng.randrange(1_000, 9_000)
            for index in range(size):
                sample = rng.randrange(10_000, 90_000)
                rolling = (rolling * 37 + sample + index * (phase + 11)) % 104_729
                loader = FileSystemLoader(
                    [
                        f"/virtual/{phase}/{(rolling + offset * sample) % 9973:04d}"
                        for offset in range(1 + rolling % 4)
                    ],
                    encoding=("utf-8", "latin-1", "ascii")[
                        (rolling + phase) % 3
                    ],
                    followlinks=bool((sample ^ rolling) & 1),
                )
                selector = (sample + rolling + index + phase) % 5
                if selector < 2:
                    source = app
                elif selector < 4:
                    source = blueprints[(rolling + index) % len(blueprints)]
                else:
                    source = f"generated-source-{(sample ^ rolling) % 8191:04x}"

                matched = (rolling + sample * (index + 1) + phase) % 6 != 1
                triple = None
                if matched:
                    origin = (
                        None
                        if (rolling + index) % 4 == 0
                        else f"/generated/{phase}/{rolling % 65521:05d}.html"
                    )
                    triple = (
                        f"candidate-{(sample + phase) % 113}",
                        origin,
                        lambda value=rolling: bool(value & 1),
                    )
                attempts.append((loader, source, triple))
            return attempts

        plans = [
            (17 + rng.randrange(3), 3),
            (31 + rng.randrange(5), 11),
            (19 + rng.randrange(4), 23),
        ]
        generated = [build_attempts(size, phase) for size, phase in plans]

        with app.app_context():
            explain_template_loading_attempts(
                app, f"summary-{sum(plans[0]) % 101}.html", generated[0]
            )

        with app.test_request_context("/diagnostics"):
            request.url_rule = Rule(
                "/diagnostics",
                endpoint=f"{blueprints[(sum(plans[1]) + len(generated[1])) % 7].name}.view",
            )
            explain_template_loading_attempts(
                app, f"summary-{sum(plans[1]) % 101}.html", generated[1]
            )

        explain_template_loading_attempts(
            app, f"summary-{sum(plans[2]) % 101}.html", generated[2]
        )

        app.logger.removeHandler(collector)
        self.assertEqual(len(collector.messages), len(generated))
        self.assertTrue(all(message.startswith("Locating template ") for message in collector.messages))
        self.assertGreater(len(set(map(len, collector.messages))), 1)
