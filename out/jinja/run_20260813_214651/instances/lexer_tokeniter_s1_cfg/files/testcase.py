import random
import unittest

from jinja2 import Environment


def _build_sources(seed: int, template_count: int, segment_count: int) -> list[str]:
    rng = random.Random(seed)
    sources: list[str] = []
    for template_index in range(template_count):
        segments: list[str] = []
        for segment_index in range(segment_count):
            variant = rng.randint(0, 6)
            if variant == 0:
                segments.append(f"plain segment {template_index}-{segment_index}")
            elif variant == 1:
                segments.append(f"{{{{ value_{segment_index} + {segment_index} }}}}")
            elif variant == 2:
                segments.append(
                    f"{{% if cond_{segment_index} %}}A{{% else %}}B{{% endif %}}"
                )
            elif variant == 3:
                segments.append(
                    f"{{% for n in seq_{segment_index} %}}{{{{ n }}}}{{% endfor %}}"
                )
            elif variant == 4:
                segments.append(
                    f"{{{{ (left_{segment_index} + right_{segment_index}) "
                    f"* scale_{segment_index} }}}}"
                )
            elif variant == 5:
                segments.append(f"{{% raw %}}{{{{ literal }}}}{{% endraw %}}")
            else:
                segments.append(
                    f"{{{{ dict_{segment_index}['key'] if flag_{segment_index} "
                    f"else 'alt' }}}}"
                )
        sources.append("\n".join(segments))
    return sources


class TestLexerTokenizeBatch(unittest.TestCase):
    def test_sequential_tokenize(self) -> None:
        env = Environment(
            lstrip_blocks=True,
            trim_blocks=True,
            keep_trailing_newline=False,
        )
        lexer = env.lexer
        sources = _build_sources(
            seed=20240814,
            template_count=7,
            segment_count=18,
        )
        checksum = 0
        for index, source in enumerate(sources):
            stream = lexer.tokenize(source, name=f"tpl_{index}")
            token_count = sum(1 for _ in stream)
            checksum ^= token_count * (index + 3)
        self.assertEqual(checksum, 400)
        self.assertEqual(len(sources), 7)
