import random
import unittest

from click.formatting import HelpFormatter


class MeasureTableNestedLoopScenarios(unittest.TestCase):
    def _exercise(
        self, seed: int, rounds: int, omission_modulus: int, flavor: str
    ) -> None:
        rng = random.Random(seed * 7919 + rounds * 104729)
        batch_count = 2 + rng.randrange(3)

        for batch in range(batch_count):
            row_count = (
                22
                + rng.randrange(rounds + 18)
                + sum(rng.randrange(97) for _ in range(rounds)) % (rounds + 5)
                + batch
            )
            rows = []

            for index in range(row_count):
                token = rng.getrandbits(32)
                first = f"{flavor}-{index:x}-{token & 0xFFFF:04x}"
                second = (
                    f"detail {token >> 7:x} "
                    f"{''.join(chr(97 + ((token >> shift) % 26)) for shift in range(0, 25, 5))}"
                )

                if flavor == "wide":
                    first = f"項目-{first}"
                    second = f"説明 {second}"
                elif flavor == "styled":
                    first = f"\033[3{token % 7}m{first}\033[0m"
                elif flavor == "spaced":
                    second = " ".join(second.split())

                has_second = index == 0 or (
                    (token ^ seed ^ (batch * 257)) % omission_modulus != 0
                )
                rows.append((first, second) if has_second else (first,))

            formatter = HelpFormatter(width=61 + seed % 23)
            formatter.write_dl(
                (row for row in rows),
                col_max=12 + rounds % 11,
                col_spacing=1 + seed % 4,
            )
            rendered = formatter.getvalue()

            self.assertIsInstance(rendered, str)
            self.assertGreater(len(rendered), len(rows))
            self.assertTrue(rendered.endswith("\n"))
            self.assertNotIn("\x00", rendered)

    def test_dense_plain_rows(self) -> None:
        self._exercise(101, 3, 2, "plain")

    def test_sparse_plain_rows(self) -> None:
        self._exercise(211, 4, 3, "plain")

    def test_wide_rows_short_rounds(self) -> None:
        self._exercise(307, 5, 5, "wide")

    def test_styled_rows_short_rounds(self) -> None:
        self._exercise(401, 6, 7, "styled")

    def test_dense_spaced_rows(self) -> None:
        self._exercise(503, 7, 2, "spaced")

    def test_sparse_wide_rows(self) -> None:
        self._exercise(601, 8, 3, "wide")

    def test_medium_styled_rows(self) -> None:
        self._exercise(701, 9, 5, "styled")

    def test_lightly_omitted_plain_rows(self) -> None:
        self._exercise(809, 10, 7, "plain")

    def test_dense_wide_rows(self) -> None:
        self._exercise(907, 11, 2, "wide")

    def test_sparse_styled_rows(self) -> None:
        self._exercise(1009, 12, 3, "styled")

    def test_medium_spaced_rows(self) -> None:
        self._exercise(1103, 13, 5, "spaced")

    def test_lightly_omitted_wide_rows(self) -> None:
        self._exercise(1201, 14, 7, "wide")
