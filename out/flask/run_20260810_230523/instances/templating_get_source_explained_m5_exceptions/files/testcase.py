import random
from pathlib import Path
import unittest

from flask import Blueprint
from flask import Flask
from flask.templating import DispatchingJinjaLoader
from jinja2 import BaseLoader
from jinja2 import DictLoader
from jinja2 import Environment


class _OperationLoader(BaseLoader):
    def __init__(self, selector: int, marker: str) -> None:
        self.selector = selector
        self.marker = marker

    def get_source(self, environment: Environment, template: str):
        selector = self.selector
        if selector == 0:
            return [][selector]
        if selector == 1:
            return {}[self.marker]
        if selector == 2:
            return selector // (selector - selector)
        if selector == 3:
            octet = bytes([(selector * 73 + 36) % 256])
            return octet.decode("ascii")
        if selector == 4:
            return getattr(object(), self.marker)
        if selector == 5:
            return selector(template)
        if selector == 6:
            assert selector < len(template) - len(template)
        if selector == 7:
            return next(iter(range(selector - selector)))
        return Path(__file__).with_name(self.marker).read_bytes()


class TestGeneratedExplainedLoadingExceptions(unittest.TestCase):
    @staticmethod
    def _build_app(
        rng: random.Random, template: str, loader_count: int, allow_matches: bool
    ) -> Flask:
        nonce = rng.randrange(100_000, 999_999)
        app = Flask(f"qa_explained_{nonce}")
        app.logger.disabled = True
        app.jinja_loader = DictLoader(
            {
                f"decoy-{(nonce * 17) % 104_729}.html": (
                    f"root-{(nonce * 31) % 65_537}"
                )
            }
        )

        rolling = nonce
        for index in range(loader_count):
            sample = rng.randrange(10_000, 90_000)
            rolling = (rolling * 41 + sample * (index + 3)) % 1_000_003
            blueprint = Blueprint(
                f"section_{index}_{rolling}", f"qa_section_{sample}_{rolling}"
            )
            candidate = (
                template
                if allow_matches and (rolling + sample + index) % 7 in (1, 4)
                else f"other-{index}-{(rolling ^ sample) % 99_991}.html"
            )
            blueprint.jinja_loader = DictLoader(
                {candidate: f"payload-{(rolling + sample * 13) % 999_983}"}
            )
            app.register_blueprint(blueprint)
        return app

    def test_generated_loader_outcomes(self) -> None:
        rng = random.Random(731_942)
        environment = Environment()
        pieces = [rng.randrange(36**5, 36**6) for _ in range(5)]
        template = "-".join(format(piece, "x") for piece in pieces) + ".html"

        successful_app = self._build_app(rng, template, 24, True)
        successful_loader = DispatchingJinjaLoader(successful_app)
        result = successful_loader._get_source_explained(environment, template)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        self.assertTrue(result[0])

        missing_app = self._build_app(rng, template, 19, False)
        missing_loader = DispatchingJinjaLoader(missing_app)
        with self.assertRaises(Exception):
            missing_loader._get_source_explained(environment, template)

        selectors = [index % 9 for index in range(27)]
        rng.shuffle(selectors)
        markers = [
            f"probe-{index}-{rng.randrange(1_000_000, 9_999_999)}.bin"
            for index in range(len(selectors))
        ]
        for selector, marker in zip(selectors, markers):
            app = Flask(f"qa_operation_{rng.randrange(10**8, 10**9)}")
            app.logger.disabled = True
            app.jinja_loader = _OperationLoader(selector, marker)
            loader = DispatchingJinjaLoader(app)
            with self.assertRaises(Exception):
                loader._get_source_explained(environment, template)
