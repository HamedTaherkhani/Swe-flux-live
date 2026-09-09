"""Exercise template loading indirectly through public Environment entry points."""

from __future__ import annotations

import random
import unittest

from jinja2 import Environment, TemplatesNotFound
from jinja2.loaders import DictLoader


class _JoiningEnvironment(Environment):
    """Environment whose join_path resolves child names relative to a parent directory."""

    def join_path(self, template: str, parent: str) -> str:
        parent_dir = parent.rsplit("/", 1)[0] if "/" in parent else ""
        if parent_dir and not template.startswith(parent_dir):
            return f"{parent_dir}/{template}"
        return template


class TestEnvironmentLoadTemplateIndirect(unittest.TestCase):
    """Reach template loading through get_template, select_template, and get_or_select_template."""

    SEED = 31415926

    @staticmethod
    def _template_source(token: str, width: int) -> str:
        return (
            "{% set acc = namespace(total=0) %}"
            "{% for item in range(" + str(width) + ") %}"
            "{% set acc.total = acc.total + item * " + str(len(token)) + " %}"
            "{% endfor %}"
            "{{ acc.total }}-{{ token }}"
        )

    @classmethod
    def _build_mapping(cls, prefix: str, count: int, rng: random.Random) -> dict[str, str]:
        return {
            f"{prefix}-{idx:03d}.jinja": cls._template_source(
                f"{prefix}{idx}", (idx % 7) + 3 + rng.randint(0, 2)
            )
            for idx in range(count)
        }

    def _env_with_loader(
        self, mapping: dict[str, str], *, cache_size: int = 400, auto_reload: bool = True
    ) -> Environment:
        return Environment(
            loader=DictLoader(mapping),
            cache_size=cache_size,
            auto_reload=auto_reload,
        )

    def test_no_loader_via_get_or_select_string(self) -> None:
        bare = Environment()
        with self.assertRaises(TypeError):
            bare.get_or_select_template("missing.jinja")

    def test_no_loader_via_select_template(self) -> None:
        bare = Environment()
        with self.assertRaises(TypeError):
            bare.select_template(["alpha.jinja", "beta.jinja"])

    def test_initial_unique_loads(self) -> None:
        rng = random.Random(self.SEED + 3)
        mapping = self._build_mapping("init", 24, rng)
        env = self._env_with_loader(mapping)
        names = sorted(mapping.keys())
        for repeat in range(22):
            name = names[(repeat * 5 + 1) % len(names)]
            tpl = env.get_template(name)
            rendered = tpl.render()
            self.assertRegex(rendered, r"^\d+-")
            self.assertEqual(tpl.name, name)

    def test_cache_hits_without_globals(self) -> None:
        rng = random.Random(self.SEED + 11)
        mapping = self._build_mapping("warm", 18, rng)
        env = self._env_with_loader(mapping)
        names = list(mapping.keys())
        for name in names:
            env.get_template(name)
        for repeat in range(36):
            name = names[(repeat * 7 + 2) % len(names)]
            tpl = env.get_template(name)
            self.assertTrue(hasattr(tpl, "render"))

    def test_cache_hits_with_globals_overlay(self) -> None:
        rng = random.Random(self.SEED + 19)
        mapping = self._build_mapping("overlay", 14, rng)
        env = self._env_with_loader(mapping)
        names = list(mapping.keys())
        for repeat in range(28):
            name = names[(repeat * 3 + 4) % len(names)]
            marker = f"g-{repeat}"
            tpl = env.get_template(name, globals={"marker": marker, "slot": repeat % 5})
            self.assertEqual(tpl.globals.get("marker"), marker)

    def test_select_template_probe_chain(self) -> None:
        rng = random.Random(self.SEED + 27)
        mapping = self._build_mapping("probe", 12, rng)
        env = self._env_with_loader(mapping)
        present = sorted(mapping.keys())
        absent = [f"ghost-{idx}.jinja" for idx in range(16)]
        for repeat in range(30):
            target = present[(repeat * 4 + 1) % len(present)]
            candidates = [
                absent[(repeat + offset) % len(absent)]
                for offset in range(3)
            ]
            candidates.append(target)
            tpl = env.select_template(candidates)
            self.assertIn(target, tpl.name)

    def test_zero_cache_reload_path(self) -> None:
        rng = random.Random(self.SEED + 31)
        mapping = self._build_mapping("nocache", 16, rng)
        env = self._env_with_loader(mapping, cache_size=0)
        names = list(mapping.keys())
        for repeat in range(26):
            name = names[(repeat * 6 + 3) % len(names)]
            tpl = env.get_or_select_template(name)
            self.assertTrue(callable(tpl.render))

    def test_get_or_select_list_routing(self) -> None:
        rng = random.Random(self.SEED + 37)
        mapping = self._build_mapping("route", 10, rng)
        env = self._env_with_loader(mapping)
        names = list(mapping.keys())
        for repeat in range(20):
            choices = [
                names[(repeat + step) % len(names)]
                for step in range(4)
            ]
            tpl = env.get_or_select_template(choices)
            self.assertIn(tpl.name, mapping)

    def test_parent_joined_names(self) -> None:
        mapping = {
            "layouts/base.jinja": self._template_source("base", 4),
            "layouts/panels/card.jinja": self._template_source("card", 5),
            "layouts/panels/list.jinja": self._template_source("list", 6),
        }
        for idx in range(8):
            mapping[f"layouts/extra-{idx}.jinja"] = self._template_source(
                f"extra{idx}", (idx % 4) + 2
            )
        env = _JoiningEnvironment(
            loader=DictLoader(mapping),
            cache_size=400,
            auto_reload=True,
        )
        child_names = ["panels/card.jinja", "panels/list.jinja", "extra-3.jinja"]
        for repeat in range(18):
            child = child_names[repeat % len(child_names)]
            tpl = env.get_template(child, parent="layouts/base.jinja")
            self.assertTrue(tpl.name.endswith(child.split("/")[-1]))

    def test_bulk_distinct_names(self) -> None:
        rng = random.Random(self.SEED + 47)
        mapping = self._build_mapping("bulk", 32, rng)
        env = self._env_with_loader(mapping)
        ordered = sorted(mapping.keys())
        for repeat in range(34):
            name = ordered[(repeat * 9 + 5) % len(ordered)]
            tpl = env.select_template([name])
            self.assertEqual(tpl.name, name)

    def test_mixed_globals_and_plain_hits(self) -> None:
        rng = random.Random(self.SEED + 53)
        mapping = self._build_mapping("mix", 15, rng)
        env = self._env_with_loader(mapping)
        names = list(mapping.keys())
        for repeat in range(32):
            name = names[(repeat * 11 + 7) % len(names)]
            if repeat % 3 == 0:
                tpl = env.get_or_select_template(
                    name, globals={"phase": repeat, "tag": f"t-{repeat % 4}"}
                )
            else:
                tpl = env.get_or_select_template(name)
            self.assertIsNotNone(tpl)

    def test_select_raises_after_exhaustion(self) -> None:
        rng = random.Random(self.SEED + 59)
        mapping = self._build_mapping("final", 6, rng)
        env = self._env_with_loader(mapping)
        missing = [f"void-{idx}.jinja" for idx in range(12)]
        with self.assertRaises(TemplatesNotFound):
            env.select_template(missing)
        present = list(mapping.keys())
        for repeat in range(14):
            name = present[repeat % len(present)]
            tpl = env.get_template(name)
            self.assertIn("final", tpl.name)
