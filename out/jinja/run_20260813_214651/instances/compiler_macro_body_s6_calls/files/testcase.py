import hashlib
import unittest

from jinja2 import Environment


def _macro_signature(seed: int, index: int) -> tuple[str, str]:
    digest = hashlib.blake2b(
        f"mb_s6:{seed}:{index}".encode(), digest_size=16
    ).hexdigest()
    kind = int(digest[0:2], 16) % 5
    arg_count = 3 + (int(digest[2:4], 16) % 12)
    args: list[str] = []
    for arg_idx in range(arg_count):
        arg_digest = hashlib.blake2b(
            f"mb_arg:{seed}:{index}:{arg_idx}".encode(), digest_size=8
        ).hexdigest()
        name = f"p{arg_idx}"
        if arg_idx == 0:
            args.append(name)
        else:
            default = int(arg_digest[0:2], 16)
            args.append(f"{name}={default}")
    signature = ", ".join(args)
    body_bits = int(digest[4:6], 16)
    body_lines: list[str] = []
    if body_bits & 1:
        body_lines.append("{{ caller() if caller is defined else '' }}")
    if body_bits & 2:
        body_lines.append("{{ kwargs if kwargs is defined else '' }}")
    if body_bits & 4:
        body_lines.append("{{ varargs if varargs is defined else '' }}")
    if body_bits & 8:
        body_lines.append("{% for item in range(3) %}{{ p0 }}{% endfor %}")
    if not body_lines:
        body_lines.append("{{ p0 }}")
    body = "\n".join(body_lines)
    macro_name = f"m{index}"
    return macro_name, f"{{% macro {macro_name}({signature}) %}}\n{body}\n{{% endmacro %}}"


def _build_template(seed: int, macro_count: int) -> str:
    macros = [_macro_signature(seed, idx) for idx in range(macro_count)]
    macro_blocks = "\n".join(block for _, block in macros)
    return macro_blocks + "\n{{ m0(p0=1) }}\n"


class CompilerMacroBodyS6CallsTest(unittest.TestCase):
    def test_compile_macro_rich_template(self) -> None:
        env = Environment()
        source = _build_template(seed=41, macro_count=18)
        compiled = env.compile(source)
        self.assertIsNotNone(compiled)
        self.assertTrue(hasattr(compiled, "co_code"))
