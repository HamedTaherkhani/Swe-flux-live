import unittest

from click.parser import _OptionParser


class TestGeneratedArgumentLayouts(unittest.TestCase):
    def _exercise(self, seed, width, token_adjustment, star_slot):
        state = seed
        specifications = []
        for index in range(width):
            state = (state * 73 + index * index * 19 + 29) % 1009
            specifications.append(1 + ((state ^ (state >> 4) ^ index) % 4))

        if star_slot is not None:
            specifications[(star_slot * 7 + seed) % width] = -1

        fixed_capacity = sum(value for value in specifications if value > 0)
        token_count = max(0, fixed_capacity + token_adjustment)
        tokens = []
        for index in range(token_count):
            state = (state * 43 + index * 31 + seed) % 2029
            tokens.append(f"item_{index}_{state:x}")

        parser = _OptionParser()
        markers = []
        for index, specification in enumerate(specifications):
            marker = object()
            markers.append(marker)
            parser.add_argument(marker, f"field_{index}", nargs=specification)

        values, leftovers, order = parser.parse_args(tokens)

        self.assertEqual(len(values), len(specifications))
        self.assertEqual(order, markers)
        if star_slot is None:
            self.assertEqual(
                len(leftovers), max(0, token_count - fixed_capacity)
            )
        else:
            self.assertFalse(leftovers)

    def test_dense_star_near_front(self):
        self._exercise(211, 23, 7, 2)

    def test_dense_star_near_back(self):
        self._exercise(263, 24, -9, 19)

    def test_exact_without_star(self):
        self._exercise(317, 21, 0, None)

    def test_excess_without_star(self):
        self._exercise(373, 19, 13, None)

    def test_sparse_star_center(self):
        self._exercise(419, 25, 5, 11)

    def test_large_groups_with_star(self):
        self._exercise(461, 27, 18, 8)

    def test_missing_values_without_star(self):
        self._exercise(509, 22, -83, None)

    def test_star_absorbs_nothing(self):
        self._exercise(557, 20, -41, 5)

    def test_alternating_capacity_pressure(self):
        self._exercise(613, 26, 11, 14)

    def test_long_exact_layout(self):
        self._exercise(677, 29, 0, None)

    def test_shortfall_after_early_star(self):
        self._exercise(733, 18, 3, 1)

    def test_surplus_after_late_star(self):
        self._exercise(787, 28, 31, 23)
