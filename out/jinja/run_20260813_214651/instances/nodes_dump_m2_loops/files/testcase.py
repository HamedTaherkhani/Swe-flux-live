import hashlib
import unittest

from jinja2 import Environment


def _digest(seed: int, tag: str, index: int = 0) -> str:
    return hashlib.blake2b(
        f"nodes_dump_m2:{seed}:{tag}:{index}".encode(), digest_size=20
    ).hexdigest()


def _output_expression_total(seed: int) -> int:
    return 11 + (int(_digest(seed, "count")[0:2], 16) % 12)


def _emit_outputs(seed: int, count: int) -> str:
    parts: list[str] = []
    for idx in range(count):
        d = _digest(seed, "out", idx)
        slot = int(d[0:2], 16) % 7
        parts.append(f"{{{{ slot{slot}_{idx} }}}}")
    return "".join(parts)


def _emit_for_body(seed: int, iterations: int) -> str:
    body: list[str] = []
    for idx in range(iterations):
        d = _digest(seed, "for", idx)
        choice = int(d[2:4], 16) % 5
        if choice == 0:
            body.append(f"{{% set loop_{idx} = {idx} %}}")
        elif choice == 1:
            body.append(f"{{{{ loop_{idx} }}}}")
        elif choice == 2:
            body.append(f"{{% if loop_{idx} %}}{idx}{{% endif %}}")
        elif choice == 3:
            body.append(f"{{% set pair_{idx}, tail_{idx} = {idx}, {idx + 2} %}}")
        else:
            body.append(f"{{% set ns.item{idx} = {idx} %}}")
    return "{% for walker in range(1) %}" + "".join(body) + "{% endfor %}"


def _emit_macro(seed: int, arg_count: int, default_count: int) -> str:
    required = max(0, arg_count - default_count)
    params: list[str] = []
    for idx in range(arg_count):
        if idx < required:
            params.append(f"m{idx}")
        else:
            params.append(f"m{idx}={idx + 1}")
    body = _emit_outputs(seed, 3 + (arg_count % 4))
    call_args = ", ".join("1" for _ in range(arg_count))
    return (
        f"{{% macro bundle({', '.join(params)}) %}}"
        f"{body}"
        f"{{% endmacro %}}"
        f"{{{{ bundle({call_args}) }}}}"
    )


def _emit_if_ladder(seed: int, branches: int) -> str:
    digest = _digest(seed, "if")
    clauses: list[str] = []
    for idx in range(branches):
        token = int(digest[idx * 2 : idx * 2 + 2], 16) % 9
        if idx == 0:
            clauses.append(f"{{% if pick == {token} %}}arm{idx}")
        else:
            clauses.append(f"{{% elif pick == {token + idx} %}}arm{idx}")
    clauses.append("{% else %}fallback{% endif %}")
    return "".join(clauses)


def _emit_call_args(seed: int, arg_total: int) -> str:
    args = ", ".join(str(int(_digest(seed, "arg", idx)[0:2], 16) % 6) for idx in range(arg_total))
    return (
        "{% call caller() %}"
        + _emit_outputs(seed + 1, arg_total // 2 + 1)
        + "{% endcall %}"
    )


def _emit_with_targets(seed: int, pairs: int) -> str:
    bindings = ", ".join(
        f"w{idx}={int(_digest(seed, 'with', idx)[0:2], 16) % 8}"
        for idx in range(pairs)
    )
    inner = _emit_outputs(seed + 3, pairs + 2)
    return f"{{% with {bindings} %}}{inner}{{% endwith %}}"


def _emit_filter_chain(seed: int, filters: int) -> str:
    parts = []
    for idx in range(filters):
        d = _digest(seed, "flt", idx)
        token = int(d[0:2], 16) % 4
        if token == 0:
            parts.append("{{ value | upper }}")
        elif token == 1:
            parts.append("{{ value | trim }}")
        elif token == 2:
            parts.append("{{ value | default('x') }}")
        else:
            parts.append("{{ value | replace('a', 'b') }}")
    return "".join(parts)


class NodesDumpM2LoopsTest(unittest.TestCase):
    """Exercise AST serialization through Environment.parse and Node.dump."""

    def setUp(self) -> None:
        self.env = Environment()

    def _serialize(self, source: str) -> str:
        parsed = self.env.parse(source)
        serialized = parsed.dump()
        self.assertTrue(serialized.startswith("nodes."))
        self.assertGreater(len(serialized), 8)
        return serialized

    def test_empty_template_body(self) -> None:
        payload = self._serialize("")
        self.assertIn("nodes.Template(", payload)
        self.assertTrue(payload.endswith(")"))

    def test_single_output_expression(self) -> None:
        payload = self._serialize("{{ lone }}")
        self.assertIn("nodes.Name(", payload)

    def test_many_output_expressions(self) -> None:
        source = _emit_outputs(seed=3, count=_output_expression_total(3))
        payload = self._serialize(source)
        self.assertGreater(len(payload), 400)

    def test_for_loop_with_assignments(self) -> None:
        source = _emit_for_body(seed=5, iterations=19)
        payload = self._serialize(source)
        self.assertIn("nodes.For(", payload)

    def test_macro_with_defaults(self) -> None:
        source = _emit_macro(seed=7, arg_count=5, default_count=3)
        payload = self._serialize(source)
        self.assertIn("nodes.Macro(", payload)

    def test_if_elif_else_ladder(self) -> None:
        source = _emit_if_ladder(seed=9, branches=6)
        payload = self._serialize(source)
        self.assertIn("nodes.If(", payload)

    def test_nested_for_ranges(self) -> None:
        outer = 4
        inner_blocks = []
        for outer_idx in range(outer):
            inner_blocks.append(
                "{% for inner_idx in range(3) %}{{ outer_idx }}-{{ inner_idx }}{% endfor %}"
            )
        source = "{% for outer_idx in range(" + str(outer) + ") %}" + "".join(inner_blocks) + "{% endfor %}"
        payload = self._serialize(source)
        self.assertGreater(payload.count("nodes.For("), 2)

    def test_filter_block_statements(self) -> None:
        source = (
            "{% filter upper %}"
            + _emit_outputs(seed=11, count=14)
            + "{% endfilter %}"
        )
        payload = self._serialize(source)
        self.assertIn("nodes.FilterBlock(", payload)

    def test_with_multiple_bindings(self) -> None:
        source = _emit_with_targets(seed=13, pairs=7)
        payload = self._serialize(source)
        self.assertIn("nodes.With(", payload)

    def test_call_expression_argument_list(self) -> None:
        source = (
            "{% macro caller() %}ok{% endmacro %}"
            + _emit_call_args(seed=17, arg_total=8)
        )
        payload = self._serialize(source)
        self.assertIn("nodes.Call(", payload)

    def test_set_block_multiline_capture(self) -> None:
        lines = [
            "{% set captured %}",
            _emit_outputs(seed=19, count=11),
            "{% for tick in range(5) %}{{ tick }}{% endfor %}",
            "{% endset %}",
            "{{ captured | length }}",
        ]
        payload = self._serialize("\n".join(lines))
        self.assertIn("nodes.AssignBlock(", payload)

    def test_mixed_template_features(self) -> None:
        source = (
            "{% macro helper(val) %}{{ val | trim }}{% endmacro %}"
            + _emit_if_ladder(seed=21, branches=4)
            + _emit_filter_chain(seed=23, filters=9)
            + _emit_for_body(seed=25, iterations=8)
            + "{{ helper(' payload ') }}"
        )
        payload = self._serialize(source)
        self.assertGreater(len(payload), 600)
        self.assertGreater(sum(1 for ch in payload if ch == "("), 40)
