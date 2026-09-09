from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from unittest import TestCase

from kedro.framework.context import KedroContext


class _ConfigLoader:
    def __init__(self, catalog: dict[str, object]) -> None:
        self._catalog = catalog

    def __getitem__(self, key: str) -> dict[str, object]:
        values = {
            "catalog": self._catalog,
            "credentials": {},
            "parameters": {},
        }
        return deepcopy(values[key])


class _Catalog(dict):
    @classmethod
    def from_config(cls, **kwargs: object) -> "_Catalog":
        return cls()


class _HookRelay:
    def after_catalog_created(self, **kwargs: object) -> None:
        return None


class _HookManager:
    hook = _HookRelay()


class TestContextPathExceptions(TestCase):
    def test_generated_catalog_then_invalid_root(self) -> None:
        catalog: dict[str, object] = {}
        for index in range(24):
            token = hashlib.sha256(f"dataset-{index * index + 17}".encode()).hexdigest()
            selector = index % 4
            if selector == 0:
                filepath = f"data/{token[:9]}/{index}.bin"
            elif selector == 1:
                filepath = f"/archive/{token[9:18]}/{index}.bin"
            elif selector == 2:
                filepath = f"R:\\vault\\{token[18:27]}\\{index}.bin"
            else:
                filepath = f"https://example.invalid/{token[27:36]}/{index}.bin"
            catalog[f"asset_{token[:7]}"] = {
                "type": "example.Dataset",
                "filepath": filepath,
                "metadata": {
                    "path": f"metadata/{token[36:45]}",
                    "rank": index,
                    "label": token[45:],
                },
            }

        context = KedroContext(
            project_path=Path.cwd(),
            config_loader=_ConfigLoader(catalog),
            env=None,
            package_name="generated_project",
            hook_manager=_HookManager(),
        )

        first_catalog = context._get_catalog(catalog_class=_Catalog)
        self.assertGreater(len(first_catalog), 0)

        digest = hashlib.blake2s(
            "|".join(sorted(catalog)).encode(), digest_size=12
        ).hexdigest()
        context.__dict__["project_path"] = Path(digest[:11]) / digest[11:]

        caught: BaseException | None = None
        try:
            context._get_catalog(catalog_class=_Catalog)
        except BaseException as exc:
            caught = exc

        self.assertIsNotNone(caught)
        self.assertGreater(len(str(caught)), len(digest))
