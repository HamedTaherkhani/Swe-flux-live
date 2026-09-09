import hashlib
import unittest

from jinja2 import Environment
from jinja2.ext import InternationalizationExtension


def _header_tokens(seed: int) -> list[str]:
    """Build a deterministic trans-tag header with many loop-driving tokens."""
    digest = hashlib.blake2b(
        f"ext_parse_s2_loops:{seed}".encode(), digest_size=32
    ).hexdigest()
    tokens: list[str] = []
    seen_names: set[str] = set()
    trim_keyword_used = False

    for idx in range(28):
        choice = int(digest[idx * 2 : idx * 2 + 2], 16) % 6
        if choice == 0:
            name = f"fld{idx}"
            if name in seen_names:
                continue
            seen_names.add(name)
            tokens.append(name)
        elif choice == 1:
            name = f"fld{idx}"
            if name in seen_names:
                continue
            seen_names.add(name)
            tokens.append(f"{name}=payload{idx}")
        elif choice == 2 and not trim_keyword_used:
            trim_keyword_used = True
            tokens.append("trimmed" if int(digest[idx], 16) % 2 == 0 else "notrimmed")
        elif choice == 3:
            target = f"fld{idx % 9}"
            alias = f"alias{idx}"
            if alias in seen_names or target not in seen_names:
                continue
            seen_names.add(alias)
            tokens.append(f"{alias}={target}")
        else:
            name = f"slot{idx}"
            if name in seen_names:
                continue
            seen_names.add(name)
            tokens.append(name)

    if not trim_keyword_used:
        tokens.insert(len(tokens) // 2, "trimmed")
    return tokens


def _build_template(seed: int) -> str:
    header = ", ".join(_header_tokens(seed))
    body_vars = " ".join(f"{{{{ fld{i} }}}}" for i in range(7))
    return (
        f"{{% trans {header} %}}"
        f"segment-{seed}: {body_vars}"
        f"{{% endtrans %}}"
    )


class ExtParseS2LoopsTest(unittest.TestCase):
    def test_extract_translations_drives_trans_header_loop(self) -> None:
        env = Environment(extensions=[InternationalizationExtension])
        template_source = _build_template(seed=17)
        extracted = list(env.extract_translations(template_source))

        self.assertGreaterEqual(len(extracted), 1)
        message = extracted[0][2]
        self.assertIn("segment-17", message)
        self.assertTrue(message.strip())
