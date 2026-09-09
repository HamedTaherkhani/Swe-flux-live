import importlib
import os
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class TestSystemProfileDiscovery(unittest.TestCase):
    def test_seeded_profile_catalog_walk(self):
        rng = random.Random(781_337)
        module = importlib.import_module("instructlab.config." + "init")

        profiles = {}
        filenames = []
        for index in range(37):
            token = "".join(chr(ord("a") + rng.randrange(26)) for _ in range(5 + index % 6))
            filename = f"profile-{index:02d}-{token}.yaml"
            filenames.append(filename)

            if index % 13 == 0:
                metadata = SimpleNamespace(
                    cpu_info=None,
                    gpu_manufacturer=None,
                    gpu_family=None,
                    gpu_count=None,
                    gpu_sku=None,
                )
            elif index % 9 == 0:
                metadata = SimpleNamespace(
                    cpu_info=f"generated cpu {token}",
                    gpu_manufacturer=None,
                    gpu_family=None,
                    gpu_count=None,
                    gpu_sku=None,
                )
            else:
                sku_count = 1 + rng.randrange(5)
                skus = [
                    "".join(
                        chr(ord("a") + rng.randrange(26))
                        for _ in range(2 + (index + sku_index) % 7)
                    )
                    for sku_index in range(sku_count)
                ]
                metadata = SimpleNamespace(
                    cpu_info=None,
                    gpu_manufacturer=f"vendor{index % 7}",
                    gpu_family=f"family{(index * index + 3) % 11}",
                    gpu_count=1 + (index * 5) % 8,
                    gpu_sku=skus,
                )

            profiles[filename] = SimpleNamespace(
                metadata=metadata,
                train=SimpleNamespace(max_batch_len=2048 + index),
            )

        rng.shuffle(filenames)
        default_config = SimpleNamespace(marker=object())
        detected_name = " ".join(
            chr(ord("a") + rng.randrange(26)) for _ in range(23)
        )

        def generated_walk(_root):
            yield "/virtual/profile-catalog", ["ignored"], list(filenames)

        def generated_read_config(config_file):
            return profiles[os.path.basename(config_file)]

        with (
            patch.object(module, "get_default_config", return_value=default_config),
            patch.object(module, "ensure_storage_directories_exist", return_value=False),
            patch.object(module, "configs_exist", return_value=False),
            patch.object(module, "profiles_exist", return_value=False),
            patch.object(
                module,
                "get_gpu_or_cpu",
                return_value=(detected_name, 17 + len(filenames), 2 + len(profiles) % 5),
            ),
            patch.object(module.os, "walk", side_effect=generated_walk),
            patch.object(module, "read_config", side_effect=generated_read_config),
        ):
            config, catalog, used_default = module.initialize_config(write_to_disk=False)

        self.assertIs(config, default_config)
        self.assertTrue(used_default)
        self.assertGreater(len(catalog) ** 2, len(profiles))
        self.assertTrue(all(entries for entries in catalog.values()))
