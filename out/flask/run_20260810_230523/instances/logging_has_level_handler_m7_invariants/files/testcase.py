import logging
import random
import string
import unittest

from flask import Flask


class TestLoggerHierarchyInvariants(unittest.TestCase):
    def test_seeded_indirect_logger_resolution(self):
        rng = random.Random(0x5A17C0DE)
        root = logging.getLogger()
        saved_root_handlers = list(root.handlers)
        saved_root_level = root.level

        try:
            root.handlers.clear()
            root.setLevel(logging.WARNING)

            depth = sum(rng.randrange(2, 6) for _ in "runtimechain")
            segments = [
                "".join(rng.choice(string.ascii_lowercase) for _ in range(4))
                + format(index, "x")
                for index in range(depth)
            ]

            prefixes = [".".join(segments[:stop]) for stop in range(1, depth + 1)]
            hierarchy = [logging.getLogger(name) for name in prefixes]
            for logger in hierarchy:
                logger.handlers.clear()
                logger.propagate = True
                logger.setLevel(logging.NOTSET)
            hierarchy[-1].setLevel(logging.INFO)

            primary_app = Flask(prefixes[-1])
            primary_logger = primary_app.logger

            accepting_name = ".".join(
                "".join(rng.choice(string.ascii_lowercase) for _ in range(7))
                for _ in range(3)
            )
            accepting_logger = logging.getLogger(accepting_name)
            accepting_logger.handlers.clear()
            accepting_logger.propagate = True
            accepting_logger.setLevel(logging.ERROR)
            accepting_logger.addHandler(logging.NullHandler(logging.NOTSET))
            accepted_app_logger = Flask(accepting_name).logger

            isolated_name = "".join(
                rng.choice(string.ascii_lowercase) for _ in range(19)
            )
            isolated_logger = logging.getLogger(isolated_name)
            isolated_logger.handlers.clear()
            isolated_logger.propagate = False
            isolated_logger.setLevel(logging.CRITICAL)
            isolated_app_logger = Flask(isolated_name).logger

            self.assertEqual(primary_logger.name, prefixes[-1])
            self.assertEqual(accepted_app_logger.name, accepting_name)
            self.assertEqual(isolated_app_logger.name, isolated_name)
            self.assertTrue(primary_logger.handlers)
            self.assertTrue(accepted_app_logger.handlers)
            self.assertTrue(isolated_app_logger.handlers)
            self.assertEqual(len({logger.name for logger in hierarchy}), depth)
        finally:
            root.handlers[:] = saved_root_handlers
            root.setLevel(saved_root_level)
