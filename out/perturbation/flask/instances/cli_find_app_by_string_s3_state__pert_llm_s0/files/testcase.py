import random
import sys
import types
import unittest

from flask import Flask
from flask.cli import ScriptInfo


class TestComputedFactoryImports(unittest.TestCase):
    def test_loads_generated_factory_expressions(self) -> None:
        rng = random.Random(1_918_337)
        module_name = "_".join(("qa", "factory", "bench", "module"))
        factory_name = "_".join(("build", "app"))
        module = types.ModuleType(module_name)
        module.__dict__["Flask"] = Flask
        exec(
            """
def build_app(numbers, metadata, *, scale, offset, tags):
    weighted = sum((index + 1) * value for index, value in enumerate(numbers))
    folded = sum((value ^ metadata["mask"]) for value in numbers)
    tag_score = sum((index + scale) * ord(tag[-1]) for index, tag in enumerate(tags))
    app_code = (weighted * scale + folded + tag_score + offset) % 1000033
    return Flask(f"runtime-{app_code:06d}")
""",
            module.__dict__,
        )
        sys.modules[module_name] = module

        loaded = []
        try:
            for turn in range(56):
                numbers = [
                    (rng.randrange(17, 1200) * (turn + 5) + index * index * 3 - turn) % 1543
                    for index in range(14)
                ]
                metadata = {
                    "mask": rng.randrange(64, 900),
                    "phase": (sum(numbers[::3]) + turn * 2) % 47,
                    "seed": rng.randrange(0, 10000),
                    "checksum": sum(numbers[1::2]) % 8191,
                    "tier": (turn + sum(numbers[::4])) % 19,
                    "anchor": None if turn % 5 else rng.randrange(100),
                    "pairs": tuple(numbers[index] for index in range(turn % 4)),
                    "nested": {
                        "values": numbers[::2][:5],
                        "turn": turn,
                        "active": turn % 2 == 0,
                    },
                }
                tags = tuple(
                    f"tag-{(value + turn * 11 + index * 5) % 127:03d}"
                    for index, value in enumerate(numbers[:10])
                )
                scale = 3 + (sum(numbers[2::3]) % 17)
                offset = (metadata["phase"] * rng.randrange(23, 131) + turn * 3) % 1009
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
