import importlib.metadata
import unittest
from unittest.mock import patch

from click import decorators


class GeneratedContext:
    def __init__(self, info_name, resilient_parsing):
        self.info_name = info_name
        self.resilient_parsing = resilient_parsing
        self.color = False

    def find_root(self):
        return self

    def exit(self):
        return None


class TestGeneratedVersionCallbacks(unittest.TestCase):
    def test_programmatic_package_resolution_paths(self):
        state = 73
        mappings = {}
        versions = {}
        scenarios = []

        for index in range(36):
            state = (state * 109 + index * 47 + 31) % 10007
            stem = "".join(
                chr(97 + ((state >> shift) + index * (shift + 3)) % 26)
                for shift in range(0, 12, 2)
            )
            package = f"pkg_{index:x}_{stem}"
            width = (state ^ (state >> 4) ^ (index * 5)) % 4
            if index == 35:
                width = 3

            distributions = [
                f"dist_{(state * (slot + 7) + index * 19) % 65521:x}_{slot:x}"
                for slot in range(width)
            ]
            mappings[package] = distributions
            if width == 1:
                versions[distributions[0]] = (
                    f"{1 + state % 9}.{(state // 7) % 17}.{(state + index) % 29}"
                )
            scenarios.append((package, index, state))

        def generated_version(name):
            if name in versions:
                return versions[name]
            raise importlib.metadata.PackageNotFoundError(name)

        def generated_packages_distributions():
            return mappings

        caught = []
        completed = 0
        with patch.object(importlib.metadata, "version", generated_version), patch.object(
            importlib.metadata,
            "packages_distributions",
            generated_packages_distributions,
        ):
            for package, index, scenario_state in scenarios:
                def command_body():
                    return None

                decorated = decorators.version_option(package_name=package)(command_body)
                option = decorated.__click_params__[-1]
                callback = option.callback
                context = GeneratedContext(
                    f"tool_{scenario_state:x}", resilient_parsing=index % 13 == 0
                )
                requested = index % 11 != 0

                try:
                    callback(context, option, requested)
                    completed += 1
                except Exception as error:
                    caught.append(error)

        self.assertEqual(completed + len(caught), len(scenarios))
        self.assertGreater(completed, len(scenarios) // 4)
        self.assertGreater(len(caught), len(scenarios) // 4)
