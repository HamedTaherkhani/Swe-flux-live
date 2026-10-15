from __future__ import annotations

import unittest

import numpy as np

import optuna
from optuna.samplers._nsgaiii._elite_population_selection_strategy import (
    _preserve_niche_individuals,
)
from optuna.trial import create_trial


class TestPreserveNicheIndividuals(unittest.TestCase):
    def test_preserve_niche_selection(self) -> None:
        optuna.logging.set_verbosity(optuna.logging.ERROR)
        gen = np.random.RandomState(20240611)
        n_reference_points = 11

        # Elite members cluster on low-index reference points (skewed weights).
        weights = np.array([1.0 / (k + 1) ** 1.3 for k in range(n_reference_points)])
        weights /= weights.sum()
        elite_num = 3 * n_reference_points + 4
        elite_refs = gen.choice(n_reference_points, size=elite_num, p=weights)

        # Borderline members prefer the opposite end of the reference set.
        rev_weights = weights[::-1].copy()
        border_num = 2 * n_reference_points + 7
        border_refs = gen.choice(n_reference_points, size=border_num, p=rev_weights)

        closest_reference_points = np.concatenate([elite_refs, border_refs]).astype(int)
        distance_reference_points = np.round(
            gen.uniform(0.0, 1.0, size=elite_num + border_num), 6
        )

        population = [
            create_trial(
                values=[float(i % 7), float((i * 3) % 5)],
                params={"x": float(i)},
                distributions={"x": optuna.distributions.FloatDistribution(-1.0, 100.0)},
            )
            for i in range(border_num)
        ]
        target_population_size = border_num - (n_reference_points // 2) - 3

        selected = _preserve_niche_individuals(
            target_population_size,
            elite_num,
            population,
            closest_reference_points,
            distance_reference_points,
            np.random.RandomState(7),
        )

        self.assertEqual(len(selected), target_population_size)
        ids = [id(t) for t in selected]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertTrue(all(t in population for t in selected))


if __name__ == "__main__":
    unittest.main()
