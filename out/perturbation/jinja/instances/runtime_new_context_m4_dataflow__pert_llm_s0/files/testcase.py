import random
import unittest

from jinja2 import DictLoader
from jinja2 import Environment
from jinja2 import pass_context
from jinja2.utils import missing


def _mix(seed: int, tag: str) -> int:
    digest = seed
    for ch in tag:
        digest = (digest * 127 + ord(ch)) % 9973
    return digest


@pass_context
def ctx_len(ctx, value: int = 0) -> int:
    return sum(1 for _ in ctx.parent)


@pass_context
def ctx_sum_keys(ctx, value: int = 0) -> int:
    total = 0
    for name in ctx.parent:
        if name.startswith("v"):
            total += int(ctx.parent[name])
    return total


@pass_context
def spawn_derived(ctx, width: int) -> int:
    locs: dict[str, object] = {}
    for idx in range(width):
        pick = (width + idx * 7) % 6
        key = f"z{idx}"
        if pick == 0:
            locs[key] = missing
        else:
            locs[key] = idx + pick
    child = ctx.derived(locs)
    return len(child.parent)


def _loop_filter_template(outer: int, sets: int, seed: int) -> str:
    lines: list[str] = [f"{{% for idx in range({outer}) %}}"]
    for slot in range(sets):
        offset = _mix(seed, f"s{slot}") % 4
        lines.append(f"{{% set v{slot} = idx + {offset} %}}")
    lines.append("{{ idx | ctx_len }}")
    lines.append("{% endfor %}")
    return "\n".join(lines)


def _nested_loop_template(outer: int, inner: int, seed: int) -> str:
    lines: list[str] = []
    for preamble in range(2):
        lines.append(f"{{% set boot{preamble} = {preamble + 1} %}}")
    lines.append(f"{{% for o in range({outer}) %}}")
    lines.append("{% set vo = o %}")
    lines.append(f"{{% for i in range({inner}) %}}")
    lines.append("{% set vi = i + vo %}")
    lines.append("{{ vi | ctx_len }}")
    lines.append("{% endfor %}")
    lines.append("{% endfor %}")
    return "\n".join(lines)


def _block_template(outer: int, seed: int) -> tuple[dict[str, str], str]:
    child = "\n".join(
        [
            "{% extends 'base_shell' %}",
            "{% block body %}",
            f"{{% for idx in range({outer}) %}}",
            "{% set vb = idx %}",
            "{{ idx | ctx_len }}",
            "{% endfor %}",
            "{% endblock %}",
        ]
    )
    base = "<div>{% block body %}{% endblock %}</div>"
    return {"base_shell": base, "child_page": child}, "child_page"


def _macro_template(loop_n: int, seed: int) -> str:
    tag = _mix(seed, "macro")
    return "\n".join(
        [
            "{% macro tally(limit) %}",
            "{% for k in range(limit) %}",
            f"{{% set vm = k + {tag % 3} %}}",
            "{{ k | ctx_len }}",
            "{% endfor %}",
            "{% endmacro %}",
            f"{{{{ tally({loop_n}) }}}}",
        ]
    )


def _branch_loop_template(outer: int, seed: int) -> str:
    pivot = _mix(seed, "branch") % 3
    lines = [f"{{% for idx in range({outer}) %}}"]
    lines.append(f"{{% if idx % {pivot + 2} == 0 %}}")
    lines.append("{% set va = idx %}")
    lines.append("{% else %}")
    lines.append("{% set vb = idx + 1 %}")
    lines.append("{% endif %}")
    lines.append("{{ idx | ctx_len }}")
    lines.append("{% endfor %}")
    return "\n".join(lines)


def _include_chain(depth: int, outer: int, seed: int) -> dict[str, str]:
    names = [f"layer_{tier}" for tier in range(depth)]
    body = _loop_filter_template(outer, 1, seed)
    templates: dict[str, str] = {names[-1]: body}
    for tier in range(depth - 2, -1, -1):
        templates[names[tier]] = f"{{% include '{names[tier + 1]}' %}}"
    return templates


def _kwargs_payload(seed: int, slots: int) -> dict[str, int]:
    return {f"k{idx}": _mix(seed, str(idx)) % 9 + 1 for idx in range(slots)}


class TestNewContextDataFlowIndirect(unittest.TestCase):
    """Exercise context derivation through template rendering."""

    def _make_env(self, mapping: dict[str, str]) -> Environment:
        env = Environment(loader=DictLoader(mapping))
        env.filters["ctx_len"] = ctx_len
        env.filters["ctx_sum_keys"] = ctx_sum_keys
        env.filters["spawn_derived"] = spawn_derived
        return env

    def _assert_rendered_digits(self, text: str) -> None:
        self.assertIsInstance(text, str)
        digit_sum = sum(int(ch) for ch in text if ch.isdigit())
        self.assertGreater(digit_sum, 0)

    def test_loop_single_set(self) -> None:
        seed = 241
        outer = 24 + _mix(seed, "a") % 13
        env = self._make_env({"probe": _loop_filter_template(outer, 1, seed)})
        self._assert_rendered_digits(env.get_template("probe").render())

    def test_loop_dual_set(self) -> None:
        seed = 352
        outer = 26 + _mix(seed, "b") % 11
        env = self._make_env({"probe": _loop_filter_template(outer, 5, seed)})
        self._assert_rendered_digits(env.get_template("probe").render())

    def test_loop_wide(self) -> None:
        seed = 463
        outer = 28 + _mix(seed, "c") % 15
        env = self._make_env({"probe": _loop_filter_template(outer, 3, seed)})
        self._assert_rendered_digits(env.get_template("probe").render())

    def test_nested_loops(self) -> None:
        seed = 574
        outer = 14 + _mix(seed, "d") % 9
        inner = 11 + _mix(seed, "e") % 8
        env = self._make_env({"probe": _nested_loop_template(outer, inner, seed)})
        self._assert_rendered_digits(env.get_template("probe").render())

    def test_block_loop(self) -> None:
        seed = 685
        outer = 23 + _mix(seed, "f") % 11
        mapping, name = _block_template(outer, seed)
        env = self._make_env(mapping)
        self._assert_rendered_digits(env.get_template(name).render())

    def test_macro_loop(self) -> None:
        seed = 796
        loop_n = 19 + _mix(seed, "g") % 12
        env = self._make_env({"probe": _macro_template(loop_n, seed)})
        self._assert_rendered_digits(env.get_template("probe").render())

    def test_spawn_derived_wide(self) -> None:
        seed = 907
        width = 34 + _mix(seed, "h") % 13
        tpl = "\n".join(
            [
                "{% for idx in range(9) %}",
                f"{{{{ {width} | spawn_derived }}}}",
                "{% endfor %}",
            ]
        )
        env = self._make_env({"probe": tpl})
        text = env.get_template("probe").render()
        self.assertTrue(any(ch.isdigit() for ch in text))

    def test_spawn_derived_tight(self) -> None:
        seed = 1018
        width = 37 + _mix(seed, "i") % 11
        tpl = f"{{{{ {width} | spawn_derived }}}}"
        env = self._make_env({"probe": tpl})
        text = env.get_template("probe").render()
        self.assertTrue(text.strip().isdigit())

    def test_render_sparse_kwargs(self) -> None:
        seed = 1129
        env = self._make_env({"probe": "{{ 0 | ctx_len }}"})
        payload = _kwargs_payload(seed, 14)
        self._assert_rendered_digits(env.get_template("probe").render(**payload))

    def test_render_dense_kwargs(self) -> None:
        seed = 1240
        slots = 20 + _mix(seed, "j") % 12
        env = self._make_env({"probe": "{{ 0 | ctx_len }}"})
        payload = _kwargs_payload(seed, slots)
        self._assert_rendered_digits(env.get_template("probe").render(**payload))

    def test_branch_loop(self) -> None:
        seed = 1351
        outer = 27 + _mix(seed, "k") % 13
        env = self._make_env({"probe": _branch_loop_template(outer, seed)})
        self._assert_rendered_digits(env.get_template("probe").render())

    def test_include_chain(self) -> None:
        seed = 1462
        outer = 22 + _mix(seed, "l") % 11
        mapping = _include_chain(7, outer, seed)
        env = self._make_env(mapping)
        self._assert_rendered_digits(env.get_template("layer_0").render())
