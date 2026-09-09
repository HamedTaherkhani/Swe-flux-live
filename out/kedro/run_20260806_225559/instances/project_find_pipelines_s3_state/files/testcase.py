"""Deterministic pytest test for instance project_find_pipelines_s3_state.

Programmatically builds a synthetic Kedro project package on disk (a top-level
``pipeline.py`` plus a ``pipelines/`` package mixing valid pipeline
subpackages, a plain file, a hidden directory, a subpackage without
``create_pipeline``, one whose ``create_pipeline`` returns a dict, and one
with a syntax error), registers it with ``configure_project`` and calls
``find_pipelines`` directly, once.
"""

import random
import shutil
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

from kedro.framework.project import configure_project, find_pipelines

SEED = 20260807
PACKAGE = "kedroqa_dynproj"
NUM_GOOD = 11

_GOOD_TEMPLATE = (
    "from kedro.pipeline import Pipeline, node, pipeline\n"
    "\n"
    "\n"
    "def _produce():\n"
    "    return 1\n"
    "\n"
    "\n"
    "def create_pipeline(**kwargs) -> Pipeline:\n"
    "    return pipeline([\n"
    "{nodes}\n"
    "    ])\n"
)


def _node_lines(tag: str, count: int) -> str:
    return ",\n".join(
        f'        node(_produce, None, "{tag}_out_{j}", name="{tag}_task_{j}")'
        for j in range(count)
    )


def _root_source() -> str:
    return _GOOD_TEMPLATE.format(nodes=_node_lines("root", 2))


def _drop_project_modules() -> None:
    for mod in list(sys.modules):
        if mod == PACKAGE or mod.startswith(PACKAGE + "."):
            del sys.modules[mod]


def _build_project(root: Path) -> dict:
    pkg = root / PACKAGE
    pipelines_dir = pkg / "pipelines"
    pipelines_dir.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pipelines_dir / "__init__.py").write_text("")
    (pkg / "pipeline.py").write_text(_root_source())

    good_order = list(range(NUM_GOOD))
    random.Random(SEED).shuffle(good_order)
    bad_slots = {
        2: ("nofunc", "stale_module"),
        5: ("badtype", "wrong_shape"),
        8: ("broken", "explodes"),
    }

    (pipelines_dir / "notes.txt").write_text("not a pipeline\n")
    hidden = pipelines_dir / ".hidden_cache"
    hidden.mkdir()
    (hidden / "__init__.py").write_text(
        _GOOD_TEMPLATE.format(nodes=_node_lines("hidden_cache", 3))
    )

    expected = {}
    gi = 0
    for step in range(NUM_GOOD + len(bad_slots)):
        if step in bad_slots:
            kind, name = bad_slots[step]
            target = pipelines_dir / name
            target.mkdir()
            if kind == "nofunc":
                (target / "__init__.py").write_text("")
            elif kind == "badtype":
                (target / "__init__.py").write_text(
                    "def create_pipeline(**kwargs):\n"
                    "    return {'a': 1, 'b': 2}\n"
                )
            else:
                (target / "__init__.py").write_text("def broken(:\n")
            continue
        i = good_order[gi]
        gi += 1
        tag = f"alpha_{i:02d}"
        count = 1 + (i + SEED) % 4
        target = pipelines_dir / tag
        target.mkdir()
        (target / "__init__.py").write_text(
            _GOOD_TEMPLATE.format(nodes=_node_lines(tag, count))
        )
        expected[tag] = count
    return expected


class TestFindPipelinesProgramState(unittest.TestCase):
    def test_find_pipelines_state(self):
        workdir = Path(tempfile.mkdtemp(prefix="kedroqa_fp_"))
        self.addCleanup(shutil.rmtree, workdir, True)
        expected_nodes = _build_project(workdir)
        sys.path.insert(0, str(workdir))
        self.addCleanup(self._restore_sys_path, str(workdir))
        _drop_project_modules()
        self.addCleanup(_drop_project_modules)

        configure_project(PACKAGE)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = find_pipelines()

        texts = [str(item.message) for item in caught]
        self.assertGreaterEqual(len(caught), 3)
        self.assertTrue(any("does not" in t for t in texts))
        self.assertTrue(any("got 'dict'" in t for t in texts))
        self.assertTrue(any("importing" in t for t in texts))

        self.assertEqual(set(result), set(expected_nodes) | {"__default__"})
        self.assertEqual(len(result["__default__"].nodes), 2)
        for tag, count in expected_nodes.items():
            self.assertEqual(len(result[tag].nodes), count)

    def _restore_sys_path(self, entry: str) -> None:
        if entry in sys.path:
            sys.path.remove(entry)


if __name__ == "__main__":
    unittest.main()
