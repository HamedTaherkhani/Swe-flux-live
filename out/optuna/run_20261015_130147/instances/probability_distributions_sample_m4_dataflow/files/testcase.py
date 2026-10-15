from __future__ import annotations

import math
import unittest

import numpy as np

from optuna.samplers._tpe.probability_distributions import _BatchedCategoricalDistributions
from optuna.samplers._tpe.probability_distributions import _BatchedDiscreteTruncLogNormDistributions
from optuna.samplers._tpe.probability_distributions import _BatchedDiscreteTruncNormDistributions
from optuna.samplers._tpe.probability_distributions import _BatchedTruncLogNormDistributions
from optuna.samplers._tpe.probability_distributions import _BatchedTruncNormDistributions
from optuna.samplers._tpe.probability_distributions import _MixtureOfProductDistribution


KINDS = ("cat", "norm", "lognorm", "disc", "disclog")


def _build_mixture(seed: int, n_components: int, kinds: list[str]) -> _MixtureOfProductDistribution:
    gen = np.random.RandomState(seed)
    weights = gen.dirichlet(np.ones(n_components))
    dists = []
    for kind in kinds:
        if kind == "cat":
            n_choices = 2 + gen.randint(4)
            dists.append(
                _BatchedCategoricalDistributions(
                    gen.dirichlet(np.ones(n_choices), size=n_components)
                )
            )
        elif kind == "norm":
            mu = gen.uniform(-5.0, 5.0, n_components)
            sigma = gen.uniform(0.3, 3.0, n_components)
            dists.append(_BatchedTruncNormDistributions(mu, sigma, -6.0, 6.0))
        elif kind == "lognorm":
            mu = gen.uniform(math.log(0.1), math.log(100.0), n_components)
            sigma = gen.uniform(0.2, 1.5, n_components)
            dists.append(_BatchedTruncLogNormDistributions(mu, sigma, 0.1, 100.0))
        elif kind == "disc":
            mu = gen.uniform(0.0, 20.0, n_components)
            sigma = gen.uniform(0.5, 4.0, n_components)
            dists.append(_BatchedDiscreteTruncNormDistributions(mu, sigma, 0.0, 20.0, 2.0))
        else:
            mu = gen.uniform(0.0, math.log(64.0), n_components)
            sigma = gen.uniform(0.2, 1.0, n_components)
            dists.append(_BatchedDiscreteTruncLogNormDistributions(mu, sigma, 1.0, 64.0, 1.0))
    return _MixtureOfProductDistribution(weights, dists)


def _random_kinds(seed: int, n_dims: int) -> list[str]:
    gen = np.random.RandomState(seed)
    return [KINDS[k] for k in gen.randint(len(KINDS), size=n_dims)]


class TestMixtureSampleDataFlow(unittest.TestCase):
    def _check(self, mixture: _MixtureOfProductDistribution, samples: np.ndarray, batch: int) -> None:
        self.assertEqual(samples.shape, (batch, len(mixture.distributions)))
        for j, d in enumerate(mixture.distributions):
            col = samples[:, j]
            if isinstance(d, _BatchedCategoricalDistributions):
                self.assertTrue(np.all(col >= 0))
                self.assertTrue(np.all(col < d.weights.shape[1]))
                self.assertTrue(np.all(col == np.round(col)))
            else:
                self.assertTrue(np.all(col >= d.low - 1e-8))
                self.assertTrue(np.all(col <= d.high + 1e-8))
                if hasattr(d, "step") and d.step != 0.0:
                    grid = (col - d.low) / d.step
                    self.assertTrue(np.allclose(grid, np.round(grid)))

    def _run(self, mixture: _MixtureOfProductDistribution, rng_seed: int, batches: list[int]) -> None:
        rng = np.random.RandomState(rng_seed)
        for batch in batches:
            samples = mixture.sample(rng, batch)
            self._check(mixture, samples, batch)

    def test_all_categorical(self) -> None:
        kinds = ["cat"] * (2 + 2 * 2)
        mixture = _build_mixture(11, 4, kinds)
        self._run(mixture, 101, [7, 3])

    def test_all_plain_normal(self) -> None:
        kinds = ["norm" for _ in range(5)]
        mixture = _build_mixture(12, 6, kinds)
        self._run(mixture, 102, [9])

    def test_log_only(self) -> None:
        kinds = ["lognorm"] * 3
        mixture = _build_mixture(13, 5, kinds)
        self._run(mixture, 103, [4, 6])

    def test_discrete_only(self) -> None:
        kinds = ["disc", "disclog"] * 2
        mixture = _build_mixture(14, 3, kinds)
        self._run(mixture, 104, [5])

    def test_random_mix_small(self) -> None:
        kinds = _random_kinds(201, 10)
        mixture = _build_mixture(15, 7, kinds)
        self._run(mixture, 105, [8, 2])

    def test_random_mix_large(self) -> None:
        kinds = _random_kinds(202, 14)
        mixture = _build_mixture(16, 9, kinds)
        self._run(mixture, 106, [b * b % 11 + 1 for b in range(3, 6)])

    def test_strided_kinds(self) -> None:
        kinds = [KINDS[(3 * j) % len(KINDS)] for j in range(9)]
        mixture = _build_mixture(17, 5, kinds)
        self._run(mixture, 107, [6])

    def test_single_component(self) -> None:
        kinds = _random_kinds(203, 6)
        mixture = _build_mixture(18, 1, kinds)
        self._run(mixture, 108, [3, 1])

    def test_many_mixtures(self) -> None:
        for k in range(4):
            kinds = _random_kinds(300 + k, 3 + 2 * k)
            mixture = _build_mixture(19 + k, 2 + k, kinds)
            self._run(mixture, 109 + k, [k + 2])

    def test_numerical_then_categorical(self) -> None:
        kinds = [KINDS[1 + (j % 4)] for j in range(7)] + ["cat", "cat"]
        mixture = _build_mixture(30, 4, kinds)
        self._run(mixture, 130, [5])

    def test_batch_size_one_repeated(self) -> None:
        kinds = _random_kinds(204, 8)
        mixture = _build_mixture(31, 3, kinds)
        self._run(mixture, 131, [1] * 4)

    def test_categorical_heavy_with_one_log(self) -> None:
        gen = np.random.RandomState(205)
        kinds = ["cat"] * (3 + gen.randint(4)) + ["disclog"]
        kinds = [kinds[p] for p in gen.permutation(len(kinds))]
        mixture = _build_mixture(32, 6, kinds)
        self._run(mixture, 132, [4, 7])


if __name__ == "__main__":
    unittest.main()
