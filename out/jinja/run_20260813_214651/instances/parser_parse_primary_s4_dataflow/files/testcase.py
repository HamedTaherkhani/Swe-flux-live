import hashlib
import unittest

from jinja2 import Environment


def _primary_fragment(seed: int, index: int) -> str:
    """Return one Jinja primary-expression fragment for list/set targets."""
    digest = hashlib.blake2b(
        f"pp_s4_df:{seed}:{index}".encode(), digest_size=16
    ).hexdigest()
    choice = int(digest[0:2], 16) % 9
    if choice == 0:
        return "true"
    if choice == 1:
        return "false"
    if choice == 2:
        return "none"
    if choice == 3:
        return "None"
    if choice == 4:
        return str((int(digest[2:4], 16) % 97) + 3)
    if choice == 5:
        whole = int(digest[4:6], 16)
        frac = int(digest[6:8], 16)
        return f"{whole}.{frac}"
    if choice == 6:
        piece_count = 2 + (int(digest[8:10], 16) % 5)
        pieces = [
            f"'seg{index}{part}'"
            for part in range(piece_count)
        ]
        return " ".join(pieces)
    if choice == 7:
        inner = ", ".join(str((int(digest[i], 16) % 11) + 1) for i in range(4))
        return f"({inner})"
    return f"sym{index}"


def _namespace_assignments(seed: int, count: int) -> list[str]:
    lines: list[str] = []
    for idx in range(count):
        digest = hashlib.blake2b(
            f"ns-assign:{seed}:{idx}".encode(), digest_size=8
        ).hexdigest()
        if int(digest[0:2], 16) % 4 != 0:
            continue
        fragment = _primary_fragment(seed, idx + 500)
        lines.append(f"{{% set ns.slot{idx} = {fragment} %}}")
    return lines


def _build_template(seed: int) -> str:
    primary_count = 32
    fragments = [_primary_fragment(seed, idx) for idx in range(primary_count)]
    list_literal = ", ".join(fragments)
    ns_lines = _namespace_assignments(seed, 14)
    return (
        "{% set ns = namespace() %}\n"
        + "\n".join(ns_lines)
        + "\n{% set payload = ["
        + list_literal
        + "] %}\n{{ payload|length }}"
    )


class ParserParsePrimaryS4DataflowTest(unittest.TestCase):
    def test_environment_parse_exercises_primary_literals(self) -> None:
        env = Environment()
        template_source = _build_template(seed=23)
        parsed = env.parse(template_source)

        self.assertIsNotNone(parsed)
        rendered = env.from_string(template_source).render()
        length_text = rendered.strip()
        self.assertTrue(length_text.isdigit())
        self.assertGreater(int(length_text), 0)
