from __future__ import annotations

import unittest

import numpy as np

from optuna.samplers._tpe.probability_distributions import _BatchedCategoricalDistributions
from optuna.samplers._tpe.probability_distributions import _BatchedDiscreteTruncNormDistributions
from optuna.samplers._tpe.probability_distributions import _BatchedTruncLogNormDistributions
from optuna.samplers._tpe.probability_distributions import _BatchedTruncNormDistributions
from optuna.samplers._tpe.probability_distributions import _MixtureOfProductDistribution


KINDS = ("cat", "norm", "lognorm", "disc")


def _build_dist(rng: np.random.RandomState, kind: str, n_comp: int, step: float):
    if kind == "cat":
        n_choices = 2 + rng.randint(4)
        w = rng.rand(n_comp, n_choices) + 0.05
        return _BatchedCategoricalDistributions(weights=w / w.sum(axis=1, keepdims=True))
    if kind == "norm":
        low, high = -3.0, 3.0 + rng.randint(5)
        mu = rng.uniform(low, high, size=n_comp)
        sigma = rng.uniform(0.3, 2.0, size=n_comp)
        return _BatchedTruncNormDistributions(mu=mu, sigma=sigma, low=low, high=high)
    if kind == "lognorm":
        low, high = 0.5, 40.0
        mu = rng.uniform(np.log(low), np.log(high), size=n_comp)
        sigma = rng.uniform(0.2, 1.5, size=n_comp)
        return _BatchedTruncLogNormDistributions(mu=mu, sigma=sigma, low=low, high=high)
    low = 0.0
    high = step * (4 + rng.randint(8))
    mu = rng.uniform(low, high, size=n_comp)
    # Make some (mu, sigma) pairs repeat so the unique paths are exercised.
    mu[::3] = mu[0]
    sigma = np.full(n_comp, 0.75 * step + 0.1)
    return _BatchedDiscreteTruncNormDistributions(
        mu=mu, sigma=sigma, low=low, high=high, step=float(step)
    )


def _build_mixture(seed: int, kinds: list[str], n_comp: int, steps: list[float]):
    rng = np.random.RandomState(seed)
    w = rng.rand(n_comp) + 0.1
    dists = []
    disc_seen = 0
    for kind in kinds:
        step = steps[disc_seen % len(steps)] if steps else 1.0
        if kind == "disc":
            disc_seen += 1
        dists.append(_build_dist(rng, kind, n_comp, step))
    return _MixtureOfProductDistribution(weights=w / w.sum(), distributions=dists)


def _random_kinds(seed: int, n_dims: int) -> list[str]:
    rng = np.random.RandomState(seed)
    return [KINDS[k] for k in rng.randint(len(KINDS), size=n_dims)]


class TestMixtureLogPdfInvariants(unittest.TestCase):
    def _run(self, mixture: _MixtureOfProductDistribution, seed: int, batch: int) -> np.ndarray:
        x = mixture.sample(np.random.RandomState(seed + 1000), batch)
        out = mixture.log_pdf(x)
        self.assertEqual(out.shape, (batch,))
        self.assertTrue(np.all(np.isfinite(out)))
        return out

    def test_all_continuous_linear(self) -> None:
        kinds = ["norm"] * 5
        self._run(_build_mixture(11, kinds, 6, []), 11, 20)

    def test_log_then_linear(self) -> None:
        kinds = ["lognorm" if j < 2 else "norm" for j in range(6)]
        self._run(_build_mixture(12, kinds, 5, []), 12, 13)

    def test_categorical_leading(self) -> None:
        kinds = ["cat"] + ["norm", "lognorm"] * 2
        self._run(_build_mixture(13, kinds, 4, []), 13, 12)

    def test_discrete_mixed_steps(self) -> None:
        kinds = ["disc", "norm", "disc", "disc", "lognorm"]
        self._run(_build_mixture(14, kinds, 7, [0.5, 2.0, 0.25]), 14, 25)

    def test_random_kinds_seed_a(self) -> None:
        kinds = _random_kinds(101, 8)
        self._run(_build_mixture(101, kinds, 5, [1.0, 0.5]), 101, 19)

    def test_random_kinds_seed_b(self) -> None:
        kinds = _random_kinds(202, 9)
        self._run(_build_mixture(202, kinds, 3, [0.2, 3.0, 1.5]), 202, 10)

    def test_repeated_calls_growing_dims(self) -> None:
        for n in range(2, 6):
            kinds = [KINDS[(n + j) % 4] for j in range(n)]
            self._run(_build_mixture(300 + n, kinds, 4, [0.1 * n + 0.6]), 300 + n, 8 + n)

    def test_single_component(self) -> None:
        kinds = ["norm", "cat", "disc", "lognorm"]
        self._run(_build_mixture(41, kinds, 1, [5.0]), 41, 9)

    def test_only_categorical_and_discrete(self) -> None:
        kinds = ["cat", "disc", "cat", "disc", "cat"]
        self._run(_build_mixture(51, kinds, 6, [0.75, 1.0]), 51, 14)

    def test_permuted_layout(self) -> None:
        base = ["norm", "norm", "lognorm", "cat", "disc", "disc", "norm"]
        order = np.random.RandomState(61).permutation(len(base))
        kinds = [base[k] for k in order]
        self._run(_build_mixture(61, kinds, 5, [0.4, 1.25]), 61, 16)

    def test_logpdf_consistency_two_batches(self) -> None:
        kinds = _random_kinds(707, 6)
        mixture = _build_mixture(707, kinds, 4, [2.5])
        first = self._run(mixture, 707, 6)
        second = self._run(mixture, 708, 11)
        self.assertEqual(len(first) + len(second), 17)

    def test_wide_lognorm_tail(self) -> None:
        kinds = ["norm"] + ["lognorm"] * 3 + ["disc"]
        self._run(_build_mixture(81, kinds, 8, [1.0]), 81, 30)


if __name__ == "__main__":
    unittest.main()
