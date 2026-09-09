import importlib.util
import os
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask.helpers import get_root_path


class FilenameLoader:
    def __init__(self, filename: str) -> None:
        self.filename = filename

    def get_filename(self, import_name: str) -> str:
        return os.path.join(os.path.dirname(self.filename), f"{import_name}.py")


class BareLoader:
    pass


class TestGetRootPathDataFlow(unittest.TestCase):
    def test_generated_module_scenarios(self) -> None:
        rng = random.Random(90421)
        jobs = [(index % 8, index) for index in range(64)]
        rng.shuffle(jobs)
        created_names: list[str] = []
        returned_paths: list[str] = []
        failures: list[int] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            old_path = list(sys.path)
            sys.path.insert(0, temp_dir)

            try:
                for kind, index in jobs:
                    token = (index * index + rng.randrange(100000)) ^ rng.getrandbits(12)
                    import_name = f"rb_root_{index:x}_{token:x}"
                    created_names.append(import_name)
                    generated_file = base / f"{import_name}.py"

                    if kind == 0:
                        module = types.ModuleType(import_name)
                        module.__file__ = str(generated_file)
                        sys.modules[import_name] = module
                        result = get_root_path(import_name)
                    elif kind == 1:
                        with patch.object(importlib.util, "find_spec", return_value=None):
                            result = get_root_path(import_name)
                    elif kind == 2:
                        with patch.object(
                            importlib.util, "find_spec", side_effect=ImportError
                        ):
                            result = get_root_path(import_name)
                    elif kind == 3:
                        with patch.object(
                            importlib.util, "find_spec", side_effect=ValueError
                        ):
                            result = get_root_path(import_name)
                    elif kind == 4:
                        spec = types.SimpleNamespace(
                            loader=FilenameLoader(str(generated_file))
                        )
                        with patch.object(importlib.util, "find_spec", return_value=spec):
                            result = get_root_path(import_name)
                    elif kind == 5:
                        spec = types.SimpleNamespace(loader=BareLoader())
                        generated_file.parent.mkdir(exist_ok=True)
                        generated_file.write_text(
                            f"MARKER = {token ^ index}\n", encoding="utf-8"
                        )
                        importlib.invalidate_caches()
                        with patch.object(importlib.util, "find_spec", return_value=spec):
                            result = get_root_path(import_name)
                    elif kind == 6:
                        spec = types.SimpleNamespace(loader=BareLoader())
                        generated_file.parent.mkdir(exist_ok=True)
                        generated_file.write_text("__file__ = None\n", encoding="utf-8")
                        importlib.invalidate_caches()
                        with patch.object(importlib.util, "find_spec", return_value=spec):
                            with self.assertRaises(RuntimeError):
                                get_root_path(import_name)
                            failures.append(kind)
                            continue
                    else:
                        spec = types.SimpleNamespace(loader=None)
                        with patch.object(importlib.util, "find_spec", return_value=spec):
                            result = get_root_path(import_name)

                    returned_paths.append(result)
            finally:
                sys.path[:] = old_path

                for name in created_names:
                    sys.modules.pop(name, None)

        self.assertEqual(len(returned_paths) + len(failures), len(jobs))
        self.assertEqual(len(failures), sum(kind == 6 for kind, _ in jobs))
        self.assertTrue(all(os.path.isabs(path) for path in returned_paths))
