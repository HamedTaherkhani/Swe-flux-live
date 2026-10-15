import math
import unittest

import numpy as np

import optuna


def _objectives(x: float, y: float, n: int) -> tuple[float, float]:
    f1 = (x - 0.3) ** 2 + 0.5 * (y + 0.2) ** 2 + 0.05 * n
    f2 = math.sin(3.0 * x) + math.cos(2.0 * y) - 0.1 * n
    return f1, f2


class TestGPSamplerPendingConstrainedFlow(unittest.TestCase):
    def test_pending_constrained_multiobjective(self) -> None:
        optuna.logging.set_verbosity(optuna.logging.ERROR)
        sampler = optuna.samplers.GPSampler(
            seed=23, n_startup_trials=5, warn_independent_sampling=False
        )
        sampler._n_preliminary_samples = 256
        sampler._n_local_search = 6
        study = optuna.create_study(directions=["minimize", "maximize"], sampler=sampler)
        rs = np.random.RandomState(2024)

        pending: list[optuna.trial.Trial] = []

        def finish(trial: optuna.trial.Trial) -> None:
            x = trial.suggest_float("x", -1.0, 1.0)
            y = trial.suggest_float("y", -1.0, 1.0)
            n = trial.suggest_int("n", 0, 4)
            trial.set_constraint("budget", x + y + 1.1)
            trial.set_constraint("spread", abs(x - y) - 0.9 + 0.1 * n)
            study.tell(trial, _objectives(x, y, n))

        for step in range(18):
            trial = study.ask()
            # Partially evaluate the trial: always x, sometimes y and n.
            trial.suggest_float("x", -1.0, 1.0)
            if rs.rand() < 0.6:
                trial.suggest_float("y", -1.0, 1.0)
            if rs.rand() < 0.5:
                trial.suggest_int("n", 0, 4)
            if rs.rand() < 0.55 and len(pending) < 8:
                pending.append(trial)
            else:
                finish(trial)
            if step % 5 == 4 and pending:
                finish(pending.pop(int(rs.randint(len(pending)))))

        for trial in pending:
            finish(trial)

        completed = study.get_trials(states=(optuna.trial.TrialState.COMPLETE,))
        self.assertEqual(len(completed), 18)
        for t in completed:
            self.assertEqual(sorted(t.params), ["n", "x", "y"])
            self.assertEqual(sorted(t.constraints), ["budget", "spread"])
        self.assertGreater(len(study.best_trials), 0)


if __name__ == "__main__":
    unittest.main()
