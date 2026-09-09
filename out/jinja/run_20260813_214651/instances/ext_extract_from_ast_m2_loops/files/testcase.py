"""Exercise gettext AST extraction loop dynamics via public i18n entry points."""

from __future__ import annotations

import random
import unittest
from io import BytesIO
from typing import Any, Sequence

from jinja2 import Environment
from jinja2.ext import GETTEXT_FUNCTIONS, InternationalizationExtension, babel_extract


class TestExtractFromAstLoopDynamics(unittest.TestCase):
    """Drive gettext AST extraction loop dynamics via i18n entry points."""

    SEED = 31415926

    def setUp(self) -> None:
        self.rng = random.Random(self.SEED)

    def _babel(
        self,
        source: str,
        keywords: Sequence[str] = GETTEXT_FUNCTIONS,
        options: dict[str, Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        payload = source.encode("utf-8")
        return list(babel_extract(BytesIO(payload), keywords, [], options or {}))

    def _i18n_extract(
        self,
        source: str,
        keywords: Sequence[str] = GETTEXT_FUNCTIONS,
    ) -> list[tuple[Any, ...]]:
        env = Environment(extensions=[InternationalizationExtension])
        ext = env.extensions["jinja2.ext.InternationalizationExtension"]
        return list(ext._extract(source, keywords))

    def _assert_nonempty_extraction(self, rows: list[tuple[Any, ...]]) -> None:
        self.assertTrue(rows)
        self.assertTrue(all(isinstance(row[0], int) for row in rows))

    def test_gettext_positional_width_sweep(self) -> None:
        lines: list[str] = []
        for idx in range(24):
            width = (idx % 5) + 1
            parts = ", ".join(f"'g{idx}_{part}'" for part in range(width))
            lines.append(f"{{{{ gettext({parts}) }}}}")
        rows = self._babel("\n".join(lines))
        self._assert_nonempty_extraction(rows)
        self.assertGreaterEqual(len({row[1] for row in rows}), 1)

    def test_ngettext_triplet_grid(self) -> None:
        lines = []
        for idx in range(20):
            lines.append(
                f"{{{{ ngettext('one{idx}', 'many{idx}', {idx % 9 + 1}) }}}}"
            )
        rows = self._babel("\n".join(lines))
        self._assert_nonempty_extraction(rows)
        self.assertEqual(len(rows), 20)

    def test_npgettext_quartet_mix(self) -> None:
        lines = []
        for idx in range(18):
            lines.append(
                "{% set n = "
                + str(idx % 7 + 2)
                + " %}"
                f"{{{{ npgettext('ctx{idx}', 'solo{idx}', 'plural{idx}', n) }}}}"
            )
        rows = self._babel("\n".join(lines))
        self._assert_nonempty_extraction(rows)
        self.assertGreater(len(rows), 10)

    def test_pgettext_pairs_with_noise(self) -> None:
        lines = []
        for idx in range(22):
            if idx % 3 == 0:
                lines.append(f"{{{{ range({idx % 6}) | list }}}}")
            lines.append(f"{{{{ pgettext('domain{idx % 4}', 'pair{idx}') }}}}")
        rows = self._babel("\n".join(lines))
        self._assert_nonempty_extraction(rows)

    def test_underscore_alias_variants(self) -> None:
        lines = []
        for idx in range(26):
            width = (idx * 3 + 1) % 4 + 1
            parts = ", ".join(f"'u{idx}_{w}'" for w in range(width))
            lines.append(f"{{{{ _({parts}) }}}}")
        rows = self._babel("\n".join(lines))
        self._assert_nonempty_extraction(rows)

    def test_trans_block_batch(self) -> None:
        chunks = []
        for idx in range(14):
            label = f"block{idx}"
            chunks.append(
                "{% trans %}" + label + " visible{% endtrans %}"
            )
        rows = self._babel("\n".join(chunks))
        self._assert_nonempty_extraction(rows)
        self.assertGreaterEqual(len(rows), 8)

    def test_trans_pluralize_blocks(self) -> None:
        chunks = []
        for idx in range(12):
            chunks.append(
                "{% trans %}{{ count }} item"
                "{% pluralize %}{{ count }} items{% endtrans %}"
            )
        rows = self._babel("\n".join(chunks))
        self._assert_nonempty_extraction(rows)

    def test_keyword_and_dyn_kwargs(self) -> None:
        lines = []
        for idx in range(16):
            lines.append(
                f"{{{{ gettext('kw{idx}', name='ignored{idx}') }}}}"
            )
            if idx % 4 == 0:
                lines.append(f"{{{{ gettext('dyn{idx}', *[]) }}}}")
        rows = self._babel("\n".join(lines))
        self._assert_nonempty_extraction(rows)

    def test_mixed_call_noise_field(self) -> None:
        lines = []
        for idx in range(30):
            kind = (idx * 5 + 2) % 8
            if kind == 0:
                lines.append(f"{{{{ gettext('m{idx}') }}}}")
            elif kind == 1:
                lines.append(f"{{{{ dict(a={idx}, b={idx+1}) }}}}")
            elif kind == 2:
                lines.append(f"{{{{ range({idx % 5}) | sum }}}}")
            elif kind == 3:
                lines.append(
                    f"{{{{ ngettext('a{idx}', 'b{idx}', {idx % 3 + 1}) }}}}"
                )
            elif kind == 4:
                lines.append(f"{{% if {idx} % 2 == 0 %}}{{{{ idx }}}}{{% endif %}}")
            elif kind == 5:
                lines.append(f"{{{{ pgettext('d{idx}', 'p{idx}') }}}}")
            elif kind == 6:
                lines.append(f"{{{{ namespace(x={idx}) }}}}")
            else:
                lines.append(
                    f"{{{{ npgettext('d{idx}', 's{idx}', 'p{idx}', {idx % 4 + 1}) }}}}"
                )
        rows = self._babel("\n".join(lines))
        self._assert_nonempty_extraction(rows)

    def test_i18n_extract_programmatic_grid(self) -> None:
        lines = []
        for idx in range(28):
            arity = (idx % 6) + 1
            parts = ", ".join(f"'i{idx}_{a}'" for a in range(arity))
            fn = ["gettext", "ngettext", "pgettext", "_"][idx % 4]
            if fn == "ngettext":
                lines.append(
                    f"{{{{ ngettext('i{idx}_s', 'i{idx}_p', {idx % 5 + 1}) }}}}"
                )
            elif fn == "pgettext":
                lines.append(f"{{{{ pgettext('c{idx}', 'i{idx}_m') }}}}")
            else:
                lines.append(f"{{{{ {fn}({parts}) }}}}")
        rows = self._i18n_extract("\n".join(lines))
        self._assert_nonempty_extraction(rows)

    def test_babel_custom_keyword_subset(self) -> None:
        keywords = ("gettext", "ngettext")
        lines = []
        for idx in range(20):
            if idx % 2 == 0:
                lines.append(f"{{{{ gettext('c{idx}') }}}}")
            else:
                lines.append(
                    f"{{{{ ngettext('cs{idx}', 'cp{idx}', {idx % 6 + 1}) }}}}"
                )
            if idx % 5 == 0:
                lines.append(f"{{{{ _('skipped{idx}') }}}}")
        rows = self._babel("\n".join(lines), keywords=keywords)
        self._assert_nonempty_extraction(rows)
        self.assertTrue(all(row[1] in keywords for row in rows))

    def test_seeded_wide_positional_fanout(self) -> None:
        local = random.Random(self.SEED + 404)
        lines = []
        for idx in range(32):
            width = local.randint(1, 6)
            fn = ["gettext", "_", "pgettext"][idx % 3]
            if fn == "pgettext":
                lines.append(
                    f"{{{{ pgettext('fan{idx % 7}', 'msg{idx}') }}}}"
                )
            else:
                parts = ", ".join(f"'f{idx}_{w}'" for w in range(width))
                lines.append(f"{{{{ {fn}({parts}) }}}}")
            if idx % 7 == 0:
                lines.append(f"{{{{ max({idx}, {idx + 1}) }}}}")
        rows = self._babel("\n".join(lines))
        self._assert_nonempty_extraction(rows)
        self.assertGreater(len(rows), 20)

    def test_i18n_extract_nested_expression_calls(self) -> None:
        lines = []
        for idx in range(18):
            inner = f"'inner{idx}'"
            lines.append(f"{{{{ gettext({inner}) if {idx} % 2 == 0 else _('alt{idx}') }}}}")
            lines.append(
                f"{{{{ ngettext('n{idx}a', 'n{idx}b', {idx % 8 + 1}) }}}}"
            )
        rows = self._i18n_extract("\n".join(lines))
        self._assert_nonempty_extraction(rows)

    def test_trimmed_trans_via_babel_options(self) -> None:
        chunks = []
        for idx in range(10):
            chunks.append(
                "{% trans trimmed %}\n  spaced "
                + str(idx)
                + "\n{% endtrans %}"
            )
        rows = self._babel(
            "\n".join(chunks),
            options={"trimmed": "true"},
        )
        self._assert_nonempty_extraction(rows)
