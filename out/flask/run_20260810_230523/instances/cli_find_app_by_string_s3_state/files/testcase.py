import random
import sys
import types
import unittest

from flask import Flask
from flask.cli import ScriptInfo


class TestComputedFactoryImports(unittest.TestCase):
    def test_loads_generated_factory_expressions(self) -> None:
        rng = random.Random(734_921)
        module_name = "_".join(("qa", "state", "module"))
        factory_name = "_".join(("build", "app"))
        module = types.ModuleType(module_name)
        module.__dict__["Flask"] = Flask
        exec(
            """
def build_app(numbers, metadata, *, scale, offset, tags):
    weighted = sum((index + 1) * value for index, value in enumerate(numbers))
    folded = sum((value ^ metadata["mask"]) for value in numbers)
    tag_score = sum((index + scale) * ord(tag[-1]) for index, tag in enumerate(tags))
    app_code = (weighted * scale + folded + tag_score + offset) % 1000003
    return Flask(f"runtime-{app_code:06d}")
""",
            module.__dict__,
        )
        sys.modules[module_name] = module

        loaded = []
        try:
            for turn in range(24):
                numbers = [
                    (rng.randrange(40, 900) * (turn + 3) + index * index) % 997
                    for index in range(7)
                ]
                metadata = {
                    "mask": rng.randrange(100, 500),
                    "phase": (sum(numbers[::2]) + turn) % 31,
                }
                tags = tuple(
                    f"tag-{(value + turn * 7 + index) % 41:02d}"
                    for index, value in enumerate(numbers[:4])
                )
                scale = 2 + (sum(numbers[1::2]) % 13)
                offset = (metadata["phase"] * rng.randrange(17, 71) + turn) % 503
                expression = (
                    f"{factory_name}({numbers!r}, {metadata!r}, "
                    f"scale={scale!r}, offset={offset!r}, tags={tags!r})"
                )
                info = ScriptInfo(
                    app_import_path=f"{module_name}:{expression}",
                    set_debug_flag=False,
                    load_dotenv_defaults=False,
                )
                loaded.append(info.load_app())
        finally:
            sys.modules.pop(module_name, None)

        self.assertEqual(len(loaded), len({app.name for app in loaded}))
        self.assertTrue(all(isinstance(app, Flask) for app in loaded))
        self.assertTrue(all(app.name.startswith("runtime-") for app in loaded))
