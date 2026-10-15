"""Scenarios exporting optuna studies to pandas DataFrames."""

import math
import random
import unittest

import optuna
from optuna.samplers import RandomSampler
from optuna.samplers import TPESampler
from optuna.trial import TrialState


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _conditional_objective(trial):
    kind = trial.suggest_categorical("kind", ["linear", "tree", "mlp"])
    if kind == "linear":
        c = trial.suggest_float("c", 1e-3, 1e2, log=True)
        return math.log10(c) ** 2
    if kind == "tree":
        depth = trial.suggest_int("depth", 1, 8)
        if depth > 4:
            trial.suggest_float("min_split", 0.0, 1.0)
        return 1.0 / depth
    n_layers = trial.suggest_int("n_layers", 1, 3)
    total = 0.0
    for i in range(n_layers):
        total += trial.suggest_int(f"units_{i}", 4, 64, log=True)
    return total / 100.0


class TestTrialsDataframeExport(unittest.TestCase):
    def test_conditional_random_default_attrs(self):
        study = optuna.create_study(sampler=RandomSampler(seed=11))
        study.optimize(_conditional_objective, n_trials=17)
        df = study.trials_dataframe()
        self.assertEqual(len(df), 17)
        self.assertIn("params_kind", df.columns)

    def test_conditional_tpe_multi_index(self):
        study = optuna.create_study(sampler=TPESampler(seed=5, n_startup_trials=6))
        study.optimize(_conditional_objective, n_trials=14)
        df = study.trials_dataframe(multi_index=True)
        self.assertEqual(df.shape[0], 14)
        self.assertEqual(df.columns.nlevels, 2)

    def test_user_attrs_varying_per_trial(self):
        rng = random.Random(23)

        def objective(trial):
            x = trial.suggest_float("x", -3, 3)
            for j in range(rng.randint(0, 4)):
                trial.set_user_attr(f"tag_{rng.choice('abcde')}", j)
            return x * x

        study = optuna.create_study(sampler=RandomSampler(seed=2))
        study.optimize(objective, n_trials=12)
        df = study.trials_dataframe(attrs=("number", "params", "user_attrs"))
        self.assertEqual(len(df), 12)

    def test_enqueued_trials_system_attrs(self):
        study = optuna.create_study(sampler=RandomSampler(seed=8))
        for d in range(1, 6, 2):
            study.enqueue_trial({"kind": "tree", "depth": d})
        study.enqueue_trial({"kind": "mlp", "n_layers": 2})
        study.optimize(_conditional_objective, n_trials=9)
        df = study.trials_dataframe(attrs=("number", "params", "system_attrs", "state"))
        self.assertEqual(len(df), 9)

    def test_pruned_intermediate_values(self):
        def objective(trial):
            lr = trial.suggest_float("lr", 1e-4, 1e-1, log=True)
            steps = 3 + trial.number % 5
            for step in range(steps):
                v = lr * (step + 1) * (trial.number % 3 + 1)
                trial.report(v, step)
                if v > 0.05:
                    raise optuna.TrialPruned()
            return lr

        study = optuna.create_study(sampler=RandomSampler(seed=31))
        study.optimize(objective, n_trials=13)
        df = study.trials_dataframe(attrs=("number", "params", "intermediate_values", "state"))
        self.assertEqual(len(df), 13)
        self.assertTrue(any(s == "PRUNED" for s in df["state"]))

    def test_failed_trials_keep_partial_params(self):
        def objective(trial):
            a = trial.suggest_int("a", 0, 9)
            if a % 3 == 0:
                raise RuntimeError("boom")
            b = trial.suggest_int("b", 0, a)
            if b % 2 == 1:
                trial.suggest_float("c", 0, 1)
            return a + b

        study = optuna.create_study(sampler=RandomSampler(seed=4))
        study.optimize(objective, n_trials=16, catch=(RuntimeError,))
        df = study.trials_dataframe()
        self.assertEqual(len(df), 16)

    def test_multi_objective_with_metric_names(self):
        def objective(trial):
            x = trial.suggest_float("x", 0, 5)
            y = trial.suggest_float("y", 0, 3)
            if x > 2.5:
                trial.set_user_attr("big_x", True)
            return x * x + y, (x - 5) ** 2 + y

        study = optuna.create_study(
            directions=["minimize", "minimize"], sampler=RandomSampler(seed=19)
        )
        study.set_metric_names(["cost", "error"])
        study.optimize(objective, n_trials=11)
        df = study.trials_dataframe()
        self.assertIn("values_cost", df.columns)
        self.assertEqual(len(df), 11)

    def test_manual_add_trials(self):
        dist = optuna.distributions.IntDistribution(0, 20)
        study = optuna.create_study()
        for i in range(10):
            params = {f"p{k}": (i * k) % 21 for k in range(i % 4 + 1)}
            study.add_trial(
                optuna.trial.create_trial(
                    params=params,
                    distributions={name: dist for name in params},
                    value=float(sum(params.values())),
                    user_attrs={"src": "manual"} if i % 3 == 0 else {},
                    system_attrs={f"s{i % 2}": i},
                )
            )
        df = study.trials_dataframe(attrs=("params", "distributions", "user_attrs", "value"))
        self.assertEqual(len(df), 10)

    def test_empty_study(self):
        study = optuna.create_study()
        df = study.trials_dataframe()
        self.assertTrue(df.empty)

    def test_ask_tell_mixed_states(self):
        study = optuna.create_study(sampler=RandomSampler(seed=55))
        for i in range(15):
            trial = study.ask()
            n = trial.suggest_int("n", 0, 6)
            for k in range(n % 3):
                trial.suggest_float(f"w{k}", 0, 1)
            if n == 0:
                study.tell(trial, state=TrialState.FAIL)
            elif n % 4 == 1:
                trial.report(float(n), 0)
                study.tell(trial, state=TrialState.PRUNED)
            elif i % 7 != 6:
                study.tell(trial, float(n))
        df = study.trials_dataframe(
            attrs=("number", "params", "intermediate_values", "user_attrs", "state")
        )
        self.assertEqual(len(df), 15)

    def test_only_scalar_attrs(self):
        study = optuna.create_study(sampler=RandomSampler(seed=3))
        study.optimize(_conditional_objective, n_trials=20)
        df = study.trials_dataframe(attrs=("number", "value", "state", "duration"))
        self.assertEqual(len(df), 20)
        self.assertNotIn("params_kind", df.columns)

    def test_private_attr_names_and_maximize(self):
        study = optuna.create_study(direction="maximize", sampler=RandomSampler(seed=77))
        study.enqueue_trial({"kind": "linear"})
        study.optimize(_conditional_objective, n_trials=10)
        df = study.trials_dataframe(attrs=("number", "_params", "_user_attrs", "_trial_id"))
        self.assertEqual(len(df), 10)
        self.assertIn("trial_id", df.columns)
