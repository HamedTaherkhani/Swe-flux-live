import hashlib
import unittest

from jinja2 import DictLoader, Environment


def _digest(seed: str) -> str:
    return hashlib.blake2b(seed.encode(), digest_size=16).hexdigest()


def _set_batch(seed: str, count: int) -> str:
    lines: list[str] = []
    for idx in range(count):
        token = _digest(f"{seed}:set:{idx}")
        name = f"a{int(token[:4], 16) % 37}"
        value = int(token[4:8], 16) % 97
        lines.append(f"{{% set {name} = {value} %}}")
    return "\n".join(lines)


def _macro_batch(seed: str, count: int) -> str:
    blocks: list[str] = []
    outer_sets: list[str] = []
    for idx in range(count):
        token = _digest(f"{seed}:macro:{idx}")
        macro_name = f"m{int(token[:3], 16) % 29}"
        arg = int(token[3:6], 16) % 11
        inner = int(token[6:9], 16) % 5
        shadow = f"s{int(token[9:12], 16) % 17}"
        outer_sets.append(f"{{% set {shadow} = {idx} %}}")
        blocks.append(
            f"{{% macro {macro_name}(p{idx}={arg}) %}}\n"
            f"{{% set {shadow} = {inner} %}}\n"
            f"{{% set inner_{idx} = {inner + 1} %}}\n"
            f"{{{{ p{idx} }}}}\n"
            f"{{% endmacro %}}"
        )
    return "\n".join(outer_sets) + "\n" + "\n".join(blocks)


def _branch_template(seed: str, branch_count: int) -> str:
    parts = ["{% set anchor = 0 %}"]
    for idx in range(branch_count):
        token = _digest(f"{seed}:branch:{idx}")
        var_name = f"b{int(token[:3], 16) % 23}"
        value = int(token[3:7], 16) % 41
        if idx == 0:
            parts.append(f"{{% if idx == {idx} %}}{{% set {var_name} = {value} %}}")
        else:
            parts.append(f"{{% elif idx == {idx} %}}{{% set {var_name} = {value} %}}")
    parts.append("{% else %}{% set fallback = 1 %}{% endif %}")
    return "\n".join(parts)


class IdtrackingStoreM6CallsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Environment()

    def _compile(self, source: str) -> None:
        compiled = self.env.compile(source)
        self.assertIsNotNone(compiled)
        self.assertTrue(hasattr(compiled, "co_code"))

    def test_seed_driven_assignment_batch(self) -> None:
        self._compile(_set_batch("assign_batch", 28))

    def test_repeated_name_assignments(self) -> None:
        lines: list[str] = []
        for idx in range(24):
            token = _digest(f"repeat:{idx}")
            slot = int(token[:2], 16) % 6
            value = int(token[2:6], 16) % 53
            lines.append(f"{{% set slot{slot} = {value} %}}")
        self._compile("\n".join(lines))

    def test_load_before_assign_same_symbol(self) -> None:
        chunks: list[str] = []
        for idx in range(18):
            token = _digest(f"load_assign:{idx}")
            name = f"x{int(token[:3], 16) % 14}"
            left = int(token[3:5], 16) % 17
            right = int(token[5:9], 16) % 29
            chunks.append(f"{{{{ {name} if {name} is defined else {left} }}}}")
            chunks.append(f"{{% set {name} = {right} %}}")
        self._compile("\n".join(chunks))

    def test_if_branch_symbol_merging(self) -> None:
        templates = [
            _branch_template("merge_a", 4),
            _branch_template("merge_b", 5),
            _branch_template("merge_c", 3),
        ]
        for idx, source in enumerate(templates):
            self._compile(source.replace("idx", str(idx % 3)))

    def test_macro_definition_batch(self) -> None:
        self._compile(_macro_batch("macro_batch", 16))

    def test_nested_scope_shadow_assignments(self) -> None:
        outer_names = [f"outer_{idx}" for idx in range(12)]
        source_lines = [f"{{% set {name} = {idx} %}}" for idx, name in enumerate(outer_names)]
        for idx, name in enumerate(outer_names):
            token = _digest(f"shadow:{idx}")
            inner_val = int(token[:4], 16) % 31
            source_lines.append(
                f"{{% macro shadow_{idx}() %}}"
                f"{{% set {name} = {inner_val} %}}"
                f"{{% endmacro %}}"
            )
        self._compile("\n".join(source_lines))

    def test_import_namespace_variants(self) -> None:
        loader = DictLoader(
            {
                f"part_{idx}.jinja": (
                    "{% macro helper() %}{{ idx }}{% endmacro %}"
                    "{% set exported = idx * 2 %}"
                )
                for idx in range(8)
            }
        )
        env = Environment(loader=loader)
        chunks: list[str] = []
        for idx in range(14):
            alias = f"ns{idx}"
            chunks.append(f"{{% import 'part_{idx % 8}.jinja' as {alias} %}}")
        compiled = env.compile("\n".join(chunks))
        self.assertTrue(hasattr(compiled, "co_code"))

    def test_from_import_name_variants(self) -> None:
        loader = DictLoader(
            {
                "shared.jinja": (
                    "{% macro alpha() %}a{% endmacro %}"
                    "{% macro beta() %}b{% endmacro %}"
                    "{% macro gamma() %}c{% endmacro %}"
                )
            }
        )
        env = Environment(loader=loader)
        macro_names = ["alpha", "beta", "gamma"]
        chunks: list[str] = []
        for idx in range(20):
            picked = macro_names[int(_digest(f"from:{idx}")[:2], 16) % len(macro_names)]
            alias = f"alias{idx % 7}"
            chunks.append(f"{{% from 'shared.jinja' import {picked} as {alias} %}}")
        compiled = env.compile("\n".join(chunks))
        self.assertIsNotNone(compiled)

    def test_call_block_assignments(self) -> None:
        lines: list[str] = []
        for idx in range(12):
            token = _digest(f"callblock:{idx}")
            target = f"cb{int(token[:3], 16) % 19}"
            value = int(token[3:7], 16) % 43
            lines.append(
                f"{{% macro helper_{idx}() %}}{{{{ caller() }}}}{{% endmacro %}}"
            )
            lines.append(
                f"{{% call helper_{idx}() %}}"
                f"{{% set {target} = {value} %}}"
                f"{{{{ {target} }}}}"
                f"{{% endcall %}}"
            )
        self._compile("\n".join(lines))

    def test_filter_block_assignments(self) -> None:
        lines: list[str] = []
        for idx in range(15):
            token = _digest(f"filterblock:{idx}")
            target = f"fb{int(token[:3], 16) % 17}"
            value = int(token[3:7], 16) % 37
            lines.append(
                f"{{% filter upper %}}"
                f"{{% set {target} = {value} %}}"
                f"{{{{ {target} }}}}"
                f"{{% endfilter %}}"
            )
        self._compile("\n".join(lines))

    def test_with_context_assignments(self) -> None:
        lines: list[str] = []
        for idx in range(16):
            token = _digest(f"withctx:{idx}")
            bind_name = f"w{int(token[:3], 16) % 13}"
            assign_name = f"t{int(token[3:6], 16) % 11}"
            bind_val = int(token[6:10], 16) % 47
            assign_val = int(token[10:14], 16) % 59
            lines.append(
                f"{{% with {bind_name}={bind_val} %}}"
                f"{{% set {assign_name} = {assign_val} %}}"
                f"{{{{ {assign_name} }}}}"
                f"{{% endwith %}}"
            )
        self._compile("\n".join(lines))

    def test_assign_block_targets(self) -> None:
        lines: list[str] = []
        for idx in range(11):
            token = _digest(f"assignblock:{idx}")
            block_name = f"blk{idx}"
            target = f"ab{int(token[:3], 16) % 15}"
            value = int(token[3:7], 16) % 33
            lines.append(f"{{% block {block_name} scoped %}}")
            lines.append(f"{{% set {target} = {value} %}}")
            lines.append("{{ self._TemplateReference__context }}")
            lines.append("{% endblock %}")
        self._compile("\n".join(lines))

    def test_namespace_reference_assignments(self) -> None:
        loader = DictLoader(
            {
                "nslib.jinja": (
                    "{% set ns.field_a = 1 %}"
                    "{% set ns.field_b = 2 %}"
                    "{% set ns.field_c = 3 %}"
                )
            }
        )
        env = Environment(loader=loader)
        chunks = ["{% import 'nslib.jinja' as ns %}"]
        for idx in range(13):
            token = _digest(f"nsref:{idx}")
            field = ["field_a", "field_b", "field_c"][idx % 3]
            local = f"n{int(token[:3], 16) % 12}"
            value = int(token[3:7], 16) % 27
            chunks.append(f"{{% set {local} = ns.{field} + {value} %}}")
        compiled = env.compile("\n".join(chunks))
        self.assertTrue(hasattr(compiled, "co_code"))

    def test_for_loop_body_assignments(self) -> None:
        lines: list[str] = []
        for outer in range(6):
            token = _digest(f"forloop:{outer}")
            span = 3 + int(token[:2], 16) % 5
            body_sets: list[str] = []
            for inner in range(span):
                inner_token = _digest(f"forloop:{outer}:{inner}")
                name = f"f{int(inner_token[:3], 16) % 18}"
                value = int(inner_token[3:7], 16) % 35
                body_sets.append(f"{{% set {name} = {value} %}}")
            lines.append(
                "{% for item in range("
                + str(span)
                + ") %}"
                + "".join(body_sets)
                + "{{ item }}"
                + "{% endfor %}"
            )
        self._compile("\n".join(lines))
