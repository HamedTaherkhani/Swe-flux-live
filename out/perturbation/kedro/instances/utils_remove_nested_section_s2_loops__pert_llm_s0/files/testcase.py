"""Deterministic exercise of the kedro project-template TOML cleanup path.

The test programmatically builds one deeply nested TOML document, writes it
to a temporary file, and drives the same-module helper ``_remove_from_toml``
(two frames above the traced logic) with an ordered list of dotted section
keys.  Each key produces one invocation of the nested-section removal logic,
and earlier removals change what later removals cascade through.
"""

import tempfile
import unittest
from pathlib import Path

import toml

from kedro.templates.project.hooks.utils import _remove_from_toml


def _add_chain(cfg, prefix, depth, leaf, val, keep_at=None, keep_name=None, keep_val=None):
    """Add a linear chain of nested tables ``prefix0...prefix{depth-1}``.

    Returns the dotted key (as a string assembled from the chain segment
    names) pointing at ``leaf`` at the bottom of the chain.  Optionally
    places a surviving marker key inside one of the chain tables.
    """
    node = cfg
    names = []
    for i in range(depth):
        name = "%s%d" % (prefix, i)
        node[name] = {}
        node = node[name]
        names.append(name)
    node[leaf] = val
    if keep_at is not None:
        keeper = cfg
        for name in names[: keep_at + 1]:
            keeper = keeper[name]
        keeper[keep_name] = keep_val
    return ".".join(names + [leaf])


def _master_config():
    cfg = {}
    key_a = _add_chain(cfg, "a", 15, "leafA", 1, keep_at=0, keep_name="keepA", keep_val=10)
    key_b = _add_chain(cfg, "b", 12, "leafB", 2)
    key_d = _add_chain(cfg, "d", 14, "leafD", 5, keep_at=7, keep_name="keepD", keep_val=11)
    key_e = _add_chain(cfg, "e", 13, "leafE1", 6, keep_at=0, keep_name="keepE", keep_val=12)
    cfg["e0"]["leafE2"] = 7
    cfg["e0"]["leafE3"] = 8
    cfg["e0"]["leafE4"] = 9

    # c branch: a short shared chain holding two sibling sub-tables.
    node = cfg
    for i in range(7):
        name = "c%d" % i
        node[name] = {}
        node = node[name]
    node["x0"] = {"leafC1": 3, "extraC1": 30}
    node["y0"] = {"leafC2": 4, "extraC2": 40}
    node["z0"] = {"leafC3": 5, "extraC3": 50}
    node["w0"] = {"leafC4": 6, "extraC4": 60}
    node["v0"] = {"leafC5": 7}
    node["u0"] = {"leafC6": 8}

    cfg["project"] = {"name": "hard-demo", "version": "2.4.1", "authors": ["alice", "bob", "carol"]}

    sections = [
        "e0.leafE4",
        "e0.missing.leafX",
        key_b,
        key_a,
        "e0.leafE3",
        "e0.leafE2",
        "c0.c1.c2.c3.c4.c5.c6.x0.leafC1",
        "c0.c1.c2.c3.c4.c5.c6.x0.extraC1",
        "c0.c1.c2.c3.c4.c5.c6.y0.leafC2",
        "c0.c1.c2.c3.c4.c5.c6.y0.extraC2",
        "c0.c1.c2.c3.c4.c5.c6.z0.leafC3",
        "c0.c1.c2.c3.c4.c5.c6.z0.extraC3",
        "c0.c1.c2.c3.c4.c5.c6.w0.leafC4",
        "c0.c1.c2.c3.c4.c5.c6.w0.extraC4",
        "c0.c1.c2.c3.c4.c5.c6.v0.leafC5",
        "c0.c1.c2.c3.c4.c5.c6.u0.leafC6",
        "c0.ghost.leafG",
        "a0.keepA",
        "a0.a1.ghost.leafZ",
        "a0.a1.a2.ghost2.leafY",
        key_d,
        key_e,
        "d0.d1.d2.d3.d4.d5.d6.d7.keepD",
        "e0.keepE",
        "b0.ghost3.leafQ",
    ]
    return cfg, sections


class TestTomlSectionCleanupLoops(unittest.TestCase):
    def test_traced_run(self):
        cfg, sections = _master_config()
        survivor = {"project": dict(cfg["project"])}

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        toml_path = Path(tmp_dir.name) / "pyproject.toml"
        toml_path.write_text(toml.dumps(cfg))

        _remove_from_toml(toml_path, sections)

        final = toml.loads(toml_path.read_text())
        self.assertEqual(final, survivor)
        for prefix in "abcde":
            self.assertNotIn(prefix + "0", final)


if __name__ == "__main__":
    unittest.main()
