import random
import unittest

from jinja2 import DictLoader
from jinja2 import Environment


def _stable_mix(seed: int, tag: str) -> int:
    digest = seed
    for char in tag:
        digest = (digest * 131 + ord(char)) % 10007
    return digest


def _boom_factory(tag: str):
    def _boom() -> None:
        raise ValueError(f"probe-{tag}")

    return _boom


def _nested_loop_template(outer: int, inner: int, preamble_sets: int) -> str:
    lines: list[str] = []
    for idx in range(preamble_sets):
        lines.append(f"{{% set pre{idx} = {idx + 1} %}}")
    lines.append(f"{{% for i in range({outer}) %}}")
    lines.append("{% set x = i * 3 %}")
    lines.append(f"{{% for j in range({inner}) %}}")
    lines.append("{% set y = j + x %}")
    lines.append("{% set z = y * 2 %}")
    lines.append("{{ boom() }}")
    lines.append("{% endfor %}")
    lines.append("{% endfor %}")
    return "\n".join(lines)


def _macro_loop_template(loop_count: int, macro_name: str) -> str:
    return "\n".join(
        [
            f"{{% macro {macro_name}(limit) %}}",
            "{% for k in range(limit) %}",
            "{% set mk = k + 1 %}",
            "{{ boom() }}",
            "{% endfor %}",
            "{% endmacro %}",
            f"{{{{ {macro_name}({loop_count}) }}}}",
        ]
    )


def _extends_block_template(outer: int) -> tuple[dict[str, str], str]:
    child = "\n".join(
        [
            "{% extends 'base_layout' %}",
            "{% block content %}",
            f"{{% for i in range({outer}) %}}",
            "{% set bi = i %}",
            "{% set bj = bi + 2 %}",
            "{{ boom() }}",
            "{% endfor %}",
            "{% endblock %}",
        ]
    )
    base = (
        "<html>{% block content %}{% endblock %}</html>"
    )
    return {"base_layout": base, "derived": child}, "derived"


def _include_chain_templates(depth: int, outer: int, inner: int) -> dict[str, str]:
    names = [f"layer_{idx}" for idx in range(depth)]
    templates: dict[str, str] = {}
    body = _nested_loop_template(outer, inner, preamble_sets=2)
    templates[names[-1]] = body
    for idx in range(depth - 2, -1, -1):
        templates[names[idx]] = f"{{% include '{names[idx + 1]}' %}}"
    return templates


def _trigger_rewrite(env: Environment, template_name: str, seed: int) -> str:
    boom = _boom_factory(f"s{seed}")
    try:
        env.get_template(template_name).render(boom=boom)
    except ValueError as exc:
        return type(exc).__name__
    except Exception as exc:
        return type(exc).__name__
    return "none"


class TestGetTemplateLocalsIndirect(unittest.TestCase):
  """Exercise template traceback rewriting (handle_exception path)."""

  def _assert_rewrite_happened(self, outcome: str) -> None:
    self.assertEqual(outcome, "ValueError")

  def test_nested_loops_small(self) -> None:
    env = Environment(
      loader=DictLoader({"probe": _nested_loop_template(12, 4, 1)})
    )
    self._assert_rewrite_happened(_trigger_rewrite(env, "probe", 11))

  def test_nested_loops_medium(self) -> None:
    env = Environment(
      loader=DictLoader({"probe": _nested_loop_template(18, 6, 2)})
    )
    self._assert_rewrite_happened(_trigger_rewrite(env, "probe", 22))

  def test_nested_loops_wide(self) -> None:
    env = Environment(
      loader=DictLoader({"probe": _nested_loop_template(28, 5, 3)})
    )
    self._assert_rewrite_happened(_trigger_rewrite(env, "probe", 33))

  def test_triple_nested_loops(self) -> None:
    source = "\n".join(
      [
        "{% for a in range(10) %}",
        "{% set sa = a %}",
        "{% for b in range(6) %}",
        "{% set sb = b + sa %}",
        "{% for c in range(4) %}",
        "{% set sc = c + sb %}",
        "{{ boom() }}",
        "{% endfor %}",
        "{% endfor %}",
        "{% endfor %}",
      ]
    )
    env = Environment(loader=DictLoader({"probe": source}))
    self._assert_rewrite_happened(_trigger_rewrite(env, "probe", 44))

  def test_macro_loop_burst(self) -> None:
    env = Environment(
      loader=DictLoader({"probe": _macro_loop_template(22, "burst")})
    )
    self._assert_rewrite_happened(_trigger_rewrite(env, "probe", 55))

  def test_macro_loop_deep(self) -> None:
    env = Environment(
      loader=DictLoader({"probe": _macro_loop_template(16, "deep")})
    )
    self._assert_rewrite_happened(_trigger_rewrite(env, "probe", 66))

  def test_include_single_child(self) -> None:
    env = Environment(
      loader=DictLoader(
        {
          "parent": "{% include 'child' %}",
          "child": _nested_loop_template(14, 5, 1),
        }
      )
    )
    self._assert_rewrite_happened(_trigger_rewrite(env, "parent", 77))

  def test_include_chain_three(self) -> None:
    templates = _include_chain_templates(depth=3, outer=15, inner=5)
    env = Environment(loader=DictLoader(templates))
    self._assert_rewrite_happened(_trigger_rewrite(env, "layer_0", 88))

  def test_include_chain_four(self) -> None:
    templates = _include_chain_templates(depth=4, outer=12, inner=7)
    env = Environment(loader=DictLoader(templates))
    self._assert_rewrite_happened(_trigger_rewrite(env, "layer_0", 99))

  def test_extends_block_failure(self) -> None:
    templates, entry = _extends_block_template(20)
    env = Environment(loader=DictLoader(templates))
    self._assert_rewrite_happened(_trigger_rewrite(env, entry, 101))

  def test_extends_block_heavy_sets(self) -> None:
    templates, _ = _extends_block_template(8)
    templates["derived"] = templates["derived"].replace(
      "{% set bj = bi + 2 %}",
      "{% set bj = bi + 2 %}{% set bk = bj + 3 %}{% set bl = bk + 1 %}",
    )
    env = Environment(loader=DictLoader(templates))
    self._assert_rewrite_happened(_trigger_rewrite(env, "derived", 112))

  def test_programmatic_batch(self) -> None:
    rng = random.Random(20240814)
    checksum = 0
    for batch in range(4):
      outer = 8 + rng.randint(3, 9)
      inner = 3 + rng.randint(2, 6)
      preamble = 1 + batch % 3
      name = f"batch_{batch}"
      env = Environment(
        loader=DictLoader({name: _nested_loop_template(outer, inner, preamble)})
      )
      outcome = _trigger_rewrite(env, name, 120 + batch)
      self._assert_rewrite_happened(outcome)
      checksum ^= _stable_mix(120 + batch, name) * (outer + inner)
    self.assertGreater(checksum, 0)

  def test_mixed_include_macro(self) -> None:
    macro_body = _macro_loop_template(10, "inline")
    env = Environment(
      loader=DictLoader(
        {
          "wrapper": "{% include 'inner' %}",
          "inner": macro_body,
        }
      )
    )
    self._assert_rewrite_happened(_trigger_rewrite(env, "wrapper", 130))
