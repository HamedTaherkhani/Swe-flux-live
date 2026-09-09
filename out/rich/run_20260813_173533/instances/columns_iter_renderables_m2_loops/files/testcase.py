import hashlib
import unittest

from rich.columns import Columns
from rich.console import Console


def _seed_bytes(label: str, count: int) -> bytes:
    return hashlib.sha256(f"columns-iter-renderables-m2-{label}".encode()).digest() * (
        (count // 32) + 1
    )


def _build_labels(seed: str, count: int) -> list[str]:
    raw = _seed_bytes(seed, count)
    return [
        f"cell-{seed[:5]}-{index}-{raw[index] % 23}"
        for index in range(count)
    ]


def _digest_renderables(renderables: list) -> str:
    payload = "|".join(repr(item) for item in renderables)
    return hashlib.sha256(payload.encode()).hexdigest()


def _invoke_iter_renderables(
    columns: Columns,
    console_width: int,
) -> list:
    """Exercise Columns.__rich_console__.iter_renderables via __rich_console__."""
    console = Console(
        width=console_width,
        force_terminal=False,
        color_system=None,
    )
    return list(columns.__rich_console__(console, console.options))


class ColumnsIterRenderablesLoopsTest(unittest.TestCase):
    def _assert_columns_digest(
        self,
        seed: str,
        item_count: int,
        console_width: int,
        *,
        equal: bool = False,
        width: int | None = None,
    ) -> None:
        labels = _build_labels(seed, item_count)
        columns = Columns(
            labels,
            column_first=True,
            equal=equal,
            width=width,
            padding=(0, 1),
        )
        rendered = _invoke_iter_renderables(columns, console_width)
        digest = _digest_renderables(rendered)
        self.assertEqual(len(digest), 64)
        self.assertTrue(rendered)

    def test_alpha_sparse_grid(self) -> None:
        self._assert_columns_digest("alpha", 12, 72)

    def test_beta_wide_console(self) -> None:
        self._assert_columns_digest("beta", 15, 120)

    def test_gamma_narrow_console(self) -> None:
        self._assert_columns_digest("gamma", 18, 36)

    def test_delta_equal_widths(self) -> None:
        self._assert_columns_digest("delta", 20, 64, equal=True)

    def test_epsilon_fixed_column_width(self) -> None:
        self._assert_columns_digest("epsilon", 22, 80, width=8)

    def test_zeta_medium_burst(self) -> None:
        self._assert_columns_digest("zeta", 25, 48)

    def test_eta_large_fanout(self) -> None:
        self._assert_columns_digest("eta", 28, 96)

    def test_theta_tight_padding(self) -> None:
        labels = _build_labels("theta", 30)
        columns = Columns(labels, column_first=True, padding=(1, 2))
        rendered = _invoke_iter_renderables(columns, 52)
        self.assertGreaterEqual(len(rendered), 1)

    def test_iota_repeated_render(self) -> None:
        labels = _build_labels("iota", 33)
        columns = Columns(labels, column_first=True)
        first = _invoke_iter_renderables(columns, 60)
        second = _invoke_iter_renderables(columns, 60)
        self.assertEqual(len(first), len(second))
        self.assertTrue(first and second)

    def test_kappa_mixed_width_and_equal(self) -> None:
        self._assert_columns_digest("kappa", 36, 44, equal=True, width=6)

    def test_lambda_high_item_count(self) -> None:
        self._assert_columns_digest("lambda", 39, 88)

    def test_mu_maximum_volume(self) -> None:
        self._assert_columns_digest("mu", 42, 40)
