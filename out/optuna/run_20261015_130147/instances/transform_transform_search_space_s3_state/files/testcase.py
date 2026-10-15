import random
import unittest
import warnings

import numpy as np

from optuna._transform import _transform_search_space
from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution


def _build_search_space(seed, n_params):
    rng = random.Random(seed)
    space = {}
    for k in range(n_params):
        flavor = (k * 3 + rng.randrange(7)) % 6
        name = f"p{k:02d}_{flavor}"
        if flavor == 0:
            n_choices = 2 + rng.randrange(4)
            space[name] = CategoricalDistribution([f"c{j}" for j in range(n_choices)])
        elif flavor == 1:
            low = rng.randint(1, 9) / 4
            space[name] = FloatDistribution(low, low + rng.randint(2, 30) / 3, log=True)
        elif flavor == 2:
            low = rng.randint(-20, 5) / 10
            step = rng.choice([0.25, 0.3, 0.7, 1.5])
            space[name] = FloatDistribution(low, low + rng.randint(3, 40) / 7, step=step)
        elif flavor == 3:
            low = rng.randint(1, 12)
            space[name] = IntDistribution(low, low * rng.randint(2, 9) + 1, log=True)
        elif flavor == 4:
            low = rng.randint(-15, 15)
            space[name] = IntDistribution(low, low + rng.randint(4, 60), step=rng.randint(1, 6))
        else:
            low = -rng.random() * 5
            space[name] = FloatDistribution(low, low + rng.random() * 9 + 0.5)
    return space


class TestTransformSearchSpaceState(unittest.TestCase):
    def test_transform_mixed_search_space(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            space = _build_search_space(seed=4242, n_params=26)

        bounds, col_to_enc, enc_to_col = _transform_search_space(space, True, True)

        n_cat_cols = sum(
            len(d.choices) for d in space.values() if isinstance(d, CategoricalDistribution)
        )
        n_num = sum(1 for d in space.values() if not isinstance(d, CategoricalDistribution))
        self.assertEqual(len(col_to_enc), len(space))
        self.assertEqual(bounds.shape, (n_cat_cols + n_num, 2))
        self.assertEqual(enc_to_col.shape[0], bounds.shape[0])
        self.assertTrue(np.all(bounds[:, 0] <= bounds[:, 1]))
        self.assertGreater(n_num, 15)
        self.assertGreater(n_cat_cols, 0)
