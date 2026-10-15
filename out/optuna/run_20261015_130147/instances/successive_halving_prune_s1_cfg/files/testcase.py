import math
import random
import unittest

import optuna
from optuna.pruners import NopPruner
from optuna.pruners._successive_halving import SuccessiveHalvingPruner
from optuna.trial import TrialState


class TestSuccessiveHalvingPruneScenario(unittest.TestCase):
    def test_prune_sequence(self) -> None:
        optuna.logging.set_verbosity(optuna.logging.ERROR)
        rng = random.Random(20240917)
        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.RandomSampler(seed=7),
            pruner=NopPruner(),
        )
        pruner = SuccessiveHalvingPruner(
            min_resource="auto", reduction_factor=2, min_early_stopping_rate=0
        )
        outcomes = []

        def check(trial: optuna.trial.Trial) -> bool:
            frozen = study._storage.get_trial(trial._trial_id)
            decision = pruner.prune(study, frozen)
            outcomes.append(decision)
            return decision

        # A trial that has not reported anything yet.
        idle = study.ask()
        check(idle)
        study.tell(idle, state=TrialState.FAIL)

        # Warm-up trials: no completed trial exists while they run.
        warm_lengths = [rng.randint(3, 6) * 37 for _ in range(2)]
        for length in warm_lengths:
            trial = study.ask()
            base = rng.uniform(4.0, 6.0)
            for step in range(length):
                trial.report(base / (1 + 0.05 * step) + rng.random() * 0.01, step)
                if step % 45 == 44:
                    check(trial)
            study.tell(trial, base / (1 + 0.05 * length))

        # Main phase: many trials, each checked at a data-dependent cadence.
        for i in range(18):
            trial = study.ask()
            base = rng.uniform(0.2, 1.8)
            cadence = rng.choice([5, 9, 13, 21])
            n_steps = rng.randint(20, 90)
            pruned = False
            for step in range(n_steps):
                v = base / (1 + 0.03 * step) + rng.random() * 0.2
                if i % 4 == 2 and step == 2 * cadence - 1:
                    v = float("nan")
                trial.report(v, step)
                if (step + 1) % cadence == 0 or step == n_steps - 1:
                    if check(trial):
                        pruned = True
                        break
            if pruned:
                study.tell(trial, state=TrialState.PRUNED)
            else:
                study.tell(trial, base / (1 + 0.03 * n_steps))

        self.assertGreater(len(outcomes), 20)
        self.assertIn(True, outcomes)
        self.assertIn(False, outcomes)
        self.assertEqual(len(study.trials), 21)


if __name__ == "__main__":
    unittest.main()
