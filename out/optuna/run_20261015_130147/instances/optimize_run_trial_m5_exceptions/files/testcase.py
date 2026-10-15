"""Many optimization scenarios whose trials fail, prune or misbehave in different ways."""

import math
import unittest

import optuna
from optuna.samplers import RandomSampler
from optuna.trial import TrialState


optuna.logging.set_verbosity(optuna.logging.CRITICAL)


def _optimize(study, objective, n_trials, catch=()):
    """Run study.optimize and report generically whether it stopped with an error."""
    try:
        study.optimize(objective, n_trials=n_trials, catch=catch)
    except BaseException:  # noqa: B036
        return True
    return False


def _states(study):
    counts = {}
    for t in study.get_trials(deepcopy=False):
        counts[t.state] = counts.get(t.state, 0) + 1
    return counts


class _PickySampler(RandomSampler):
    """Random sampler whose post-processing only understands finished values."""

    def after_trial(self, study, trial, state, values):
        self.last_first_value = float(values[0]) * 2.0
        super().after_trial(study, trial, state, values)


class _BudgetSampler(RandomSampler):
    """Random sampler that consumes a finite budget of tickets on every trial."""

    def __init__(self, n_tickets, seed):
        super().__init__(seed=seed)
        self._tickets = [i * i for i in range(n_tickets)]

    def before_trial(self, study, trial):
        self._tickets.pop()
        super().before_trial(study, trial)


class TestRunTrialExceptionMix(unittest.TestCase):
    def test_clean_quadratic(self):
        study = optuna.create_study(sampler=RandomSampler(seed=0))
        crashed = _optimize(study, lambda t: (t.suggest_float("x", -5, 5) - 2) ** 2, 18)
        self.assertFalse(crashed)
        self.assertEqual(_states(study), {TrialState.COMPLETE: 18})

    def test_log_domain_caught(self):
        def objective(trial):
            x = trial.suggest_float("x", -3.0, 3.0)
            return math.log(x) + x

        study = optuna.create_study(sampler=RandomSampler(seed=1))
        crashed = _optimize(study, objective, 26, catch=(ValueError,))
        self.assertFalse(crashed)
        self.assertEqual(len(study.trials), 26)
        self.assertGreater(_states(study).get(TrialState.FAIL, 0), 0)

    def test_median_pruning(self):
        def objective(trial):
            slope = trial.suggest_float("slope", 0.1, 2.0)
            value = 0.0
            for step in range(8):
                value = slope * (8 - step)
                trial.report(value, step)
                if trial.should_prune():
                    raise optuna.TrialPruned()
            return value

        pruner = optuna.pruners.MedianPruner(n_startup_trials=3, n_warmup_steps=1)
        study = optuna.create_study(sampler=RandomSampler(seed=2), pruner=pruner)
        crashed = _optimize(study, objective, 30)
        self.assertFalse(crashed)
        self.assertGreater(_states(study).get(TrialState.PRUNED, 0), 0)

    def test_lookup_errors_caught(self):
        table = {k: k * 3 for k in range(0, 12, 2)}
        series = [v * 0.5 for v in range(7)]

        def objective(trial):
            k = trial.suggest_int("k", 0, 11)
            j = trial.suggest_int("j", 0, 9)
            return table[k] + series[j]

        study = optuna.create_study(sampler=RandomSampler(seed=3))
        crashed = _optimize(study, objective, 40, catch=(LookupError,))
        self.assertFalse(crashed)
        self.assertEqual(len(study.trials), 40)

    def test_uncaught_division_stops_run(self):
        table = {k: k for k in range(1, 20, 3)}

        def objective(trial):
            k = trial.suggest_int("k", 0, 19)
            return table[k] / (k % 7)

        study = optuna.create_study(sampler=RandomSampler(seed=4))
        crashed = _optimize(study, objective, 60, catch=(LookupError,))
        self.assertTrue(crashed)
        self.assertLess(len(study.trials), 60)

    def test_objective_tells_complete_itself(self):
        def objective(trial):
            x = trial.suggest_float("x", 0.0, 1.0)
            if x > 0.85:
                study.tell(trial, x)
            return x

        study = optuna.create_study(sampler=RandomSampler(seed=5))
        crashed = _optimize(study, objective, 25)
        self.assertTrue(crashed)
        self.assertEqual(_states(study), {TrialState.COMPLETE: len(study.trials)})

    def test_objective_tells_fail_itself(self):
        def objective(trial):
            n = trial.suggest_int("n", 0, 30)
            if n % 6 == 4:
                study.tell(trial, state=TrialState.FAIL)
            return float(n)

        study = optuna.create_study(sampler=RandomSampler(seed=6))
        crashed = _optimize(study, objective, 25)
        self.assertTrue(crashed)
        self.assertEqual(_states(study).get(TrialState.FAIL, 0), 1)

    def test_objective_tells_pruned_then_prunes(self):
        def objective(trial):
            y = trial.suggest_float("y", -1.0, 1.0)
            if y < -0.6:
                study.tell(trial, state=TrialState.PRUNED)
                raise optuna.TrialPruned()
            if y > 0.7:
                raise optuna.TrialPruned()
            return y

        study = optuna.create_study(sampler=RandomSampler(seed=7))
        crashed = _optimize(study, objective, 30)
        self.assertTrue(crashed)

    def test_sampler_post_processing_breaks_on_failure(self):
        def objective(trial):
            z = trial.suggest_float("z", 0.0, 4.0)
            return math.sqrt(2.0 - z) if z > 1.0 else z

        study = optuna.create_study(sampler=_PickySampler(seed=8))
        crashed = _optimize(study, objective, 20, catch=(ValueError,))
        self.assertTrue(crashed)

    def test_sampler_budget_runs_out(self):
        def objective(trial):
            a = trial.suggest_int("a", 1, 9)
            try:
                return 10 // (a - 5)
            except ArithmeticError:
                return 0.0

        study = optuna.create_study(sampler=_BudgetSampler(13, seed=9))
        crashed = _optimize(study, objective, 30)
        self.assertTrue(crashed)
        self.assertEqual(_states(study).get(TrialState.RUNNING, 0), 1)

    def test_invalid_returned_values(self):
        def objective(trial):
            c = trial.suggest_categorical("c", ["num", "text", "nan", "none", "pair"])
            if c == "text":
                return "not-a-number"
            if c == "nan":
                return float("nan")
            if c == "none":
                return None
            if c == "pair":
                return [1.0, 2.0]
            return 1.5

        study = optuna.create_study(sampler=RandomSampler(seed=10))
        crashed = _optimize(study, objective, 24)
        self.assertFalse(crashed)
        self.assertEqual(len(study.trials), 24)

    def test_multi_objective_report_caught_as_runtime(self):
        def objective(trial):
            u = trial.suggest_float("u", 0.0, 3.0)
            if u > 2.2:
                trial.report(u, 0)
            if u < 0.4:
                return u
            return u, 3.0 - u

        study = optuna.create_study(
            directions=["minimize", "minimize"], sampler=RandomSampler(seed=11)
        )
        crashed = _optimize(study, objective, 28, catch=(RuntimeError,))
        self.assertFalse(crashed)
        self.assertEqual(len(study.trials), 28)

    def test_nested_optimize_and_distribution_clash(self):
        def inner(trial):
            return 0.0

        def objective(trial):
            m = trial.suggest_int("m", 0, 14)
            if m % 4 == 1:
                study.optimize(inner, n_trials=1)
            if m % 5 == 3 and trial.number >= 12:
                trial.suggest_float("m", 0.0, 1.0)
            return m * 0.25

        study = optuna.create_study(sampler=RandomSampler(seed=12))
        crashed = _optimize(study, objective, 35, catch=(RuntimeError,))
        self.assertTrue(crashed)

    def test_attribute_errors_swallowed_by_broad_catch(self):
        registry = {f"key{i}": (i if i % 3 else None) for i in range(10)}

        def objective(trial):
            name = trial.suggest_categorical("name", sorted(registry))
            item = registry[name]
            return item.bit_length() + len(name)

        study = optuna.create_study(sampler=RandomSampler(seed=13))
        crashed = _optimize(study, objective, 32, catch=(Exception,))
        self.assertFalse(crashed)
        self.assertEqual(len(study.trials), 32)
