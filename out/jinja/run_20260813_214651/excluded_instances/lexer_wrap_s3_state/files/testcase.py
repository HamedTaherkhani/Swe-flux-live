"""Indirect exercise of Lexer.wrap via Environment.from_string compilation."""

from __future__ import annotations

import hashlib
import random
import unittest

from jinja2 import Environment


class TestLexerWrapProgramState(unittest.TestCase):
    """Compile a seeded, programmatic Jinja template through the environment."""

    SEED = 20260814
    SEGMENTS = 40

    @classmethod
    def _build_source(cls) -> str:
        rng = random.Random(cls.SEED)
        parts: list[str] = []
        for i in range(cls.SEGMENTS):
            mod = (i * 3 + rng.randint(0, 6)) % 11
            if mod == 0:
                parts.append(f"{{{{ {i} + {i*2} }}}}")
            elif mod == 1:
                esc = rng.choice(["\\n", "\\t", "\\r"])
                parts.append(f"{{{{ 'v{i}{esc}tail' }}}}")
            elif mod == 2:
                parts.append(f"{{{{ 0x{(i * 7 + 13):x} }}}}")
            elif mod == 3:
                parts.append(f"{{{{ {i}.{i % 10} }}}}")
            elif mod == 4:
                parts.append(f"{{{{ {i} ** 2 }}}}")
            elif mod == 5:
                parts.append(f"{{{{ item_{i} }}}}")
            elif mod == 6:
                parts.append(f"{{{{ {i} if {i} > 0 else 1 }}}}")
            elif mod == 7:
                parts.append("{# comment " + str(i * 17) + " #}")
            elif mod == 8:
                parts.append("{% raw %}" + f"raw{i}" + "{% endraw %}")
            elif mod == 9:
                parts.append(f"data{i}\r\n")
            else:
                parts.append(f"{{{{ '{i}'|length }}}}")
        return "".join(parts)

    def test_compile_programmatic_template(self) -> None:
        env = Environment(newline_sequence="\n", keep_trailing_newline=True)
        source = self._build_source()
        template = env.from_string(source)

        self.assertGreater(len(source), 400)
        self.assertLess(len(source), 900)
        digest = hashlib.sha256(source.encode()).hexdigest()[:16]
        self.assertEqual(digest, "63e5aa483179e5e3")
        self.assertIsNotNone(template)
