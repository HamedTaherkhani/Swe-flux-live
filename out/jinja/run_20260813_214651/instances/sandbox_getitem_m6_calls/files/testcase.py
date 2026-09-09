import hashlib
import types
import unittest

from jinja2.sandbox import SandboxedEnvironment


def _digest(seed: str) -> str:
    return hashlib.blake2b(seed.encode(), digest_size=16).hexdigest()


def _field_name(seed: str, index: int) -> str:
    token = _digest(f"{seed}:{index}")
    return f"k{int(token[:4], 16) % 17}"


def _build_records(seed: str, count: int) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for idx in range(count):
        key = _field_name(seed, idx)
        kind = int(_digest(f"kind:{seed}:{idx}")[:2], 16) % 4
        if kind == 0:
            value = idx
        elif kind == 1:
            value = {"inner": idx * 3}
        elif kind == 2:
            value = [idx, idx + 1]
        else:
            value = types.SimpleNamespace(public=idx, _hidden=idx + 9)
        records.append({key: value, "tag": idx % 5})
    return records


def _jinja_expr(python_expr: str) -> str:
    return "{{ " + python_expr + " }}"


class _BracketCarrier:
    def __init__(self, mapping: dict[str, object]) -> None:
        self._mapping = mapping

    def __getitem__(self, key: object) -> object:
        raise TypeError("carrier blocks direct subscript")

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._mapping.get(name, f"missing:{name}")


class SandboxGetitemM6CallsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = SandboxedEnvironment()

    def _render(self, template: str, **context: object) -> str:
        return self.env.from_string(template).render(**context)

    def test_dict_bracket_placeholders(self) -> None:
        records = _build_records("dict_bracket", 18)
        chunks: list[str] = []
        for record in records:
            key = next(k for k in record if k != "tag")
            chunks.append(_jinja_expr(f'"{{0[{key}]}}".format({record!r})'))
        template = "".join(chunks)
        output = self._render(template)
        self.assertGreater(len(output), 0)

    def test_attr_fallback_through_brackets(self) -> None:
        carriers = [
            _BracketCarrier({"alpha": idx, "beta": idx * 2})
            for idx in range(16)
        ]
        parts: list[str] = []
        for idx, name in enumerate(["alpha", "beta"] * 9):
            parts.append(
                _jinja_expr(
                    f'"{{0[{name}]}}".format(carriers[{idx % len(carriers)}])'
                )
            )
        output = self._render("".join(parts), carriers=carriers)
        self.assertTrue(output)
        self.assertIn("0", output)

    def test_nested_bracket_resolution(self) -> None:
        rows = [
            {"outer": {"inner": idx, "pair": [idx, idx + 4]}}
            for idx in range(15)
        ]
        parts = [
            _jinja_expr(
                '"{0[outer][inner]}-{0[outer][pair][0]}".format(rows['
                + str(idx)
                + "])"
            )
            for idx in range(len(rows))
        ]
        output = self._render("".join(parts), rows=rows)
        self.assertGreater(len(output), len(rows))

    def test_format_map_with_bracket_fields(self) -> None:
        payload = {f"n{idx}": {"value": idx % 7} for idx in range(20)}
        parts = [
            _jinja_expr(
                f'"v{{0[{key}][value]}}".format({{"{key}": payload["{key}"]}})'
            )
            for key in payload
        ]
        output = self._render("".join(parts), payload=payload)
        self.assertTrue(all(ch.isdigit() or ch in "v" for ch in output))

    def test_list_index_brackets(self) -> None:
        lists = [[idx, idx + 1, idx + 2] for idx in range(17)]
        parts = [
            _jinja_expr(f'"{{0[{idx % 3}]}}".format(lists[{idx}])')
            for idx in range(len(lists))
        ]
        output = self._render("".join(parts), lists=lists)
        self.assertGreater(len(output), len(lists))

    def test_unsafe_bracket_names(self) -> None:
        unsafe_count = int(_digest("unsafe_bracket_names")[:2], 16) % 5 + 9
        parts = [
            _jinja_expr(f'"{{0[__class__]}}".format({value})')
            for value in range(unsafe_count)
        ]
        output = self._render("".join(parts))
        self.assertEqual(output, "")

    def test_private_bracket_names(self) -> None:
        carriers = [_BracketCarrier({"public": idx}) for idx in range(15)]
        parts = [
            _jinja_expr(f'"{{0[_hidden]}}".format(carriers[{idx}])')
            for idx in range(len(carriers))
        ]
        output = self._render("".join(parts), carriers=carriers)
        self.assertEqual(output, "")

    def test_missing_bracket_lookup(self) -> None:
        rows = [{"present": idx} for idx in range(15)]
        parts = [
            _jinja_expr(f'"{{0[absent]}}".format(rows[{idx}])')
            for idx in range(len(rows))
        ]
        output = self._render("".join(parts), rows=rows)
        self.assertEqual(output, "")

    def test_mixed_dot_and_bracket_fields(self) -> None:
        rows = [{"node": types.SimpleNamespace(score=idx)} for idx in range(16)]
        parts = [
            _jinja_expr(
                '"{0[node].score}-{0[node][score]}".format(rows[' + str(idx) + "])"
            )
            for idx in range(len(rows))
        ]
        output = self._render("".join(parts), rows=rows)
        self.assertGreater(len(output), len(rows))

    def test_markup_safe_format_brackets(self) -> None:
        parts = [
            _jinja_expr(f'(("safe{{0[v]}}"|safe).format({{"v": {idx}}}))')
            for idx in range(15)
        ]
        output = self._render("".join(parts))
        self.assertIn("safe", output)

    def test_seed_driven_field_batch(self) -> None:
        seed = "seed_batch"
        specs = [
            (f"{{0[{_field_name(seed, idx)}]}}", {_field_name(seed, idx): idx})
            for idx in range(22)
        ]
        parts = [
            _jinja_expr(f'"{pattern}".format({mapping!r})')
            for pattern, mapping in specs
        ]
        output = self._render("".join(parts))
        self.assertGreaterEqual(len(output), len(specs))

    def test_chained_format_map_nested_keys(self) -> None:
        nested = {
            f"bucket{idx}": {f"leaf{idx}": idx % 6}
            for idx in range(18)
        }
        parts = [
            _jinja_expr(f'"{{0[{key}][leaf{idx}]}}".format(nested)')
            for idx, key in enumerate(nested)
        ]
        output = self._render("".join(parts), nested=nested)
        self.assertTrue(output)

    def test_public_namespace_brackets(self) -> None:
        nodes = [
            types.SimpleNamespace(**{f"slot{idx % 4}": idx})
            for idx in range(19)
        ]
        parts = [
            _jinja_expr(f'"{{0[slot{idx % 4}]}}".format(nodes[{idx}])')
            for idx in range(len(nodes))
        ]
        output = self._render("".join(parts), nodes=nodes)
        self.assertGreater(len(output), 0)

    def test_multi_placeholder_format_strings(self) -> None:
        table = {f"c{idx}": {"m": idx, "n": idx + 2} for idx in range(17)}
        parts = [
            _jinja_expr(f'"{{0[{key}][m]}}:{{0[{key}][n]}}".format(table)')
            for key in table
        ]
        output = self._render("".join(parts), table=table)
        self.assertIn(":", output)
