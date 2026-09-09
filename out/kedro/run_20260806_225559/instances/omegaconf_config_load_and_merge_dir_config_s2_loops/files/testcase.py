"""Deterministic exercise of OmegaConfigLoader.load_and_merge_dir_config.

The test programmatically builds three configuration directory trees
(``phase_a``, ``phase_b``, ``phase_c``) under a temporary conf source,
mixing YAML and JSON config files with sub-directories, plain-text files
and hidden paths.  It then invokes ``load_and_merge_dir_config`` directly
once per phase with a list of overlapping glob patterns, so individual
paths can be produced by more than one pattern before de-duplication.
"""

import json
import random
import tempfile
import unittest
from pathlib import Path

from kedro.config.omegaconf_config import OmegaConfigLoader

PATTERNS = ["catalog*", "catalog*/**", "**/catalog*"]


def _write_yaml(path: Path, key: str, payload: int) -> None:
    lines = [
        f"{key}:",
        f"  seed: {payload}",
        "  tags:",
        f"    - {payload + 1}",
        f"    - {payload + 2}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(path: Path, key: str, payload: int) -> None:
    doc = {key: {"seed": payload, "tags": [payload + 1, payload + 2]}}
    path.write_text(json.dumps(doc), encoding="utf-8")


def _populate(phase: Path, tag: str, rng: random.Random) -> set:
    """Create a deterministic tree of config and non-config files.

    Returns the set of top-level config keys that should appear in the
    merged result for this phase.
    """
    keys = set()
    counter = 0

    def emit(path: Path, fmt: str) -> None:
        nonlocal counter
        key = f"{tag}_{counter:03d}"
        counter += 1
        value = rng.randint(100, 999)
        if fmt == "json":
            _write_json(path, key, value)
        else:
            _write_yaml(path, key, value)
        keys.add(key)

    n_top = 5 + rng.randint(0, 4)
    for i in range(n_top):
        fmt = "json" if i % 3 == 2 else "yml"
        emit(phase / f"catalog_{tag}_{i:02d}.{fmt}", fmt)

    n_packs = 2 + rng.randint(0, 2)
    for p in range(n_packs):
        pack = phase / f"catalog_pack_{tag}_{p}"
        pack.mkdir()
        n_deep = 2 + rng.randint(0, 3)
        for j in range(n_deep):
            emit(pack / f"layer_{j:02d}.yml", "yml")
        (pack / f"notes_{p}.txt").write_text("not a config file\n", encoding="utf-8")
        if p == 0:
            cache = pack / ".cache"
            cache.mkdir()
            (cache / "stash.yml").write_text("ghost: 1\n", encoding="utf-8")

    (phase / f"catalog_{tag}_README.txt").write_text("docs only\n", encoding="utf-8")
    (phase / f".catalog_{tag}_hidden.yml").write_text("ghost: 2\n", encoding="utf-8")
    return keys


class TestOmegaConfDirMergeLoops(unittest.TestCase):
    def test_traced_run(self):
        rng = random.Random(20260807)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "conf_root"
        root.mkdir()

        loader = OmegaConfigLoader(conf_source=str(root))

        phases = {}
        expected = {}
        for phase_name, tag in (("phase_a", "aa"), ("phase_b", "bb"), ("phase_c", "cc")):
            phase_dir = root / phase_name
            phase_dir.mkdir()
            phases[phase_name] = phase_dir
            expected[phase_name] = _populate(phase_dir, tag, rng)

        seen = set()
        results = {}
        for phase_name in ("phase_a", "phase_b", "phase_c"):
            results[phase_name] = loader.load_and_merge_dir_config(
                str(phases[phase_name]), PATTERNS, "catalog", seen, False
            )

        for phase_name in ("phase_a", "phase_b", "phase_c"):
            self.assertEqual(set(results[phase_name]), expected[phase_name])
            self.assertTrue(
                all(isinstance(v, dict) for v in results[phase_name].values())
            )
        self.assertEqual(len(seen), sum(len(v) for v in expected.values()))


if __name__ == "__main__":
    unittest.main()
