"""Deterministic exercise of the KedroContext catalog-creation call chain.

The test builds a throwaway Kedro project under a fixed ``/tmp`` root and
accesses the ``catalog`` property of a single ``KedroContext`` instance
three times.  Before each access the project's ``conf/base/catalog.yml``
and ``conf/base/parameters.yml`` are regenerated programmatically by a
seeded random generator, so every access drives the catalog-creation chain
through a different configuration shape: dataset entries mix relative,
absolute, remote (``s3://``) and Windows-drive filepaths, nested metadata
dictionaries carrying deeper filepaths, scalar-only entries, and nested
parameter trees of varying depth merged with fixed nested runtime
parameters.
"""

import random
import shutil
import unittest
from pathlib import Path

import yaml

from kedro.config import OmegaConfigLoader
from kedro.framework.context import KedroContext
from kedro.framework.hooks import _create_hook_manager

FIXTURE_ROOT = Path("/tmp/kedro_qa_context_get_catalog_s6")

ROUNDS = [
    {"seed": 4242, "datasets": 6, "param_width": 3, "param_depth": 2},
    {"seed": 7373, "datasets": 13, "param_width": 4, "param_depth": 3},
    {"seed": 5151, "datasets": 5, "param_width": 2, "param_depth": 2},
]

RUNTIME_PARAMS = {"shared": {"leaf": 900, "deeper": {"extra": 7}}, "flat": 5}

PATH_KINDS = ("relative", "absolute", "remote", "windows", "nested", "bare")


def _write_yaml(filepath: Path, config: dict) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(yaml.dump(config))


def _gen_dataset_cfg(rng: random.Random, index: int) -> dict:
    kind = PATH_KINDS[rng.randrange(len(PATH_KINDS))]
    cfg = {"type": "MemoryDataset", "versioned": bool(rng.randrange(2))}
    if kind == "relative":
        cfg["filepath"] = "data/0%d_raw/ds_%02d.csv" % (1 + rng.randrange(3), index)
    elif kind == "absolute":
        cfg["filepath"] = "/srv/datasets/ds_%02d.parquet" % index
    elif kind == "remote":
        cfg["filepath"] = "s3://bucket-%d/exports/ds_%02d.csv" % (index % 4, index)
    elif kind == "windows":
        cfg["filepath"] = "C:\\exports\\ds_%02d.csv" % index
    elif kind == "nested":
        cfg["metadata"] = {
            "source": {
                "filepath": "meta/ds_%02d.json" % index,
                "owned": bool(rng.randrange(2)),
            }
        }
    if rng.randrange(2):
        cfg["save_args"] = {
            "index": bool(rng.randrange(2)),
            "sep": rng.choice([",", ";", "|"]),
        }
    return cfg


def _gen_params(rng: random.Random, width: int, depth: int, prefix: str) -> dict:
    node = {}
    for b in range(width):
        key = "%sp%d" % (prefix, b)
        if depth > 1 and rng.randrange(3):
            node[key] = _gen_params(rng, max(1, width - 1), depth - 1, key + ".")
        else:
            node[key] = rng.randrange(1000)
    return node


def _merge_nested(old: dict, new: dict) -> dict:
    merged = dict(old)
    for key, value in new.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def _param_paths(params: dict, prefix: str = "") -> set:
    names = set()
    for key, value in params.items():
        dotted = "%s%s" % (prefix, key)
        names.add("params:" + dotted)
        if isinstance(value, dict):
            names |= _param_paths(value, dotted + ".")
    return names


class TestCatalogCallChain(unittest.TestCase):
    def test_tracked_call_order(self):
        shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)
        self.addCleanup(shutil.rmtree, FIXTURE_ROOT, ignore_errors=True)

        conf_base = FIXTURE_ROOT / "conf" / "base"
        conf_local = FIXTURE_ROOT / "conf" / "local"
        conf_base.mkdir(parents=True)
        conf_local.mkdir(parents=True)
        _write_yaml(
            conf_local / "credentials.yml",
            {"svc": {"user": "svc_user", "token": "tok123"}},
        )

        config_loader = OmegaConfigLoader(
            conf_source=str(FIXTURE_ROOT / "conf"), env="local", base_env="base"
        )
        context = KedroContext(
            project_path=str(FIXTURE_ROOT),
            config_loader=config_loader,
            env="local",
            package_name="qa_s6_pkg",
            hook_manager=_create_hook_manager(),
            runtime_params=RUNTIME_PARAMS,
        )

        seen_dataset_names = set()
        for index, spec in enumerate(ROUNDS, start=1):
            rng = random.Random(spec["seed"])
            catalog_cfg = {
                "ds%d_%02d" % (index, i): _gen_dataset_cfg(rng, i)
                for i in range(spec["datasets"])
            }
            params = _gen_params(
                rng, spec["param_width"], spec["param_depth"], "r%d." % index
            )
            params["shared"] = {"leaf": index, "deeper": {"a": index}}

            _write_yaml(conf_base / "catalog.yml", catalog_cfg)
            _write_yaml(conf_base / "parameters.yml", params)

            catalog = context.catalog

            merged_params = _merge_nested(params, RUNTIME_PARAMS)
            expected_names = (
                set(catalog_cfg) | {"parameters"} | _param_paths(merged_params)
            )
            self.assertEqual(set(catalog.keys()), expected_names)

            resolved = catalog.config_resolver.config
            for name, cfg in catalog_cfg.items():
                filepath = cfg.get("filepath")
                if isinstance(filepath, str) and filepath.startswith("data/"):
                    self.assertTrue(
                        resolved[name]["filepath"].startswith(
                            FIXTURE_ROOT.as_posix() + "/"
                        )
                    )

            self.assertTrue(seen_dataset_names.isdisjoint(catalog_cfg))
            seen_dataset_names |= set(catalog_cfg)

            self.assertEqual(catalog.load("params:shared.leaf"), 900)
            self.assertEqual(catalog.load("params:shared.deeper.a"), index)


if __name__ == "__main__":
    unittest.main()
