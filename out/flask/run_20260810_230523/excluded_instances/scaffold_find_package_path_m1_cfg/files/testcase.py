from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from flask.sansio.scaffold import find_package


class FindPackagePathControlFlowTest(TestCase):
    def test_generated_import_layouts(self) -> None:
        layout_kinds = (
            "missing",
            "broken",
            "regular",
            "module",
            "nswide",
            "nsfallback",
        )
        import_names = [
            (
                f"{layout_kinds[index % len(layout_kinds)]}_{index:x}"
                f".branch_{(index * index + 3 * index) % 17:x}"
            )
            for index in range(5 * len(layout_kinds))
        ]

        def fake_find_spec(import_name: str):
            root_name, separator, _ = import_name.partition(".")
            kind = root_name.rsplit("_", 1)[0]

            if kind == "missing":
                return None

            if kind == "broken":
                raise ImportError(root_name[::-1])

            if kind == "regular":
                return SimpleNamespace(
                    submodule_search_locations=[f"/opt/generated/{root_name}"],
                    origin=f"/opt/generated/{root_name}/__init__.py",
                )

            if kind == "module":
                return SimpleNamespace(
                    submodule_search_locations=None,
                    origin=f"/srv/generated/{root_name}.py",
                )

            locations = [
                f"/mnt/generated/alpha/{root_name}",
                f"/mnt/generated/omega/{root_name}",
            ]
            root_spec = SimpleNamespace(
                submodule_search_locations=locations,
                origin=None,
            )

            if not separator:
                return root_spec

            if kind == "nswide":
                return SimpleNamespace(
                    submodule_search_locations=[
                        f"{locations[(len(root_name) + 1) % len(locations)]}/"
                        f"{import_name.rpartition('.')[2]}"
                    ],
                    origin=None,
                )

            return None

        with patch(
            "flask.sansio.scaffold.importlib.util.find_spec",
            side_effect=fake_find_spec,
        ) as mocked_find_spec:
            results = [find_package(name) for name in import_names]

        self.assertEqual(len(results), len(import_names))
        self.assertTrue(all(isinstance(item, tuple) and len(item) == 2 for item in results))
        self.assertGreater(mocked_find_spec.call_count, len(import_names))
        self.assertTrue(all(isinstance(path, str) and path for _, path in results))
