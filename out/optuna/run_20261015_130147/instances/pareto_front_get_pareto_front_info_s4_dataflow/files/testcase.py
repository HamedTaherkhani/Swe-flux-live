from __future__ import annotations

import random
import unittest
import warnings

import optuna
from optuna.trial import create_trial
from optuna.trial import TrialState
from optuna.visualization import plot_pareto_front


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _populate(study, rng, n, n_obj, with_constraints):
    for i in range(n):
        vals = [round(rng.uniform(-5.0, 5.0), 3) for _ in range(n_obj)]
        if i % 7 == 3:
            study.add_trial(create_trial(state=TrialState.FAIL))
            continue
        kwargs = {}
        if with_constraints and i % 3 != 0:
            kwargs["constraints"] = {
                "c0": round(sum(vals) - rng.uniform(-2.0, 2.0), 3),
                "c1": round(vals[0] * vals[-1] - 4.0, 3),
            }
        study.add_trial(create_trial(values=vals, **kwargs))


class TestParetoFrontScenarios(unittest.TestCase):
    def test_many_pareto_front_plots(self) -> None:
        rng = random.Random(20240611)
        figures = []

        # 1) Two objectives, mixed constrained/unconstrained trials, all defaults.
        s1 = optuna.create_study(directions=["minimize", "maximize"])
        _populate(s1, rng, 24, 2, with_constraints=True)
        figures.append(plot_pareto_front(s1))

        # 2) Three objectives with metric names, dominated trials hidden.
        s2 = optuna.create_study(directions=["minimize", "minimize", "maximize"])
        _populate(s2, rng, 18, 3, with_constraints=False)
        s2.set_metric_names(["alpha", "beta", "gamma"])
        figures.append(plot_pareto_front(s2, include_dominated_trials=False))

        # 3) Four objectives projected onto two targets, deprecated constraints_func.
        s3 = optuna.create_study(directions=["minimize"] * 4)
        _populate(s3, rng, 16, 4, with_constraints=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            figures.append(
                plot_pareto_front(
                    s3,
                    target_names=["first", "sum_rest"],
                    constraints_func=lambda t: [t.values[1] - t.values[2]],
                    targets=lambda t: (t.values[0], sum(t.values[1:])),
                )
            )

        # 4) Empty two-objective study, defaults.
        s4 = optuna.create_study(directions=["maximize", "maximize"])
        figures.append(plot_pareto_front(s4))

        # 5) Empty study with explicit targets and names.
        figures.append(
            plot_pareto_front(
                s4, target_names=["u", "v", "w"], targets=lambda t: (1.0, 2.0, 3.0)
            )
        )

        # 6) Every trial infeasible.
        s6 = optuna.create_study(directions=["minimize", "minimize"])
        for k in range(9):
            s6.add_trial(
                create_trial(values=[float(k), float(9 - k)], constraints={"c": 1.0 + k})
            )
        figures.append(plot_pareto_front(s6, include_dominated_trials=False))

        # Failure paths.
        with self.assertRaisesRegex(ValueError, "only supports 2 or 3 objective"):
            plot_pareto_front(s3)
        with self.assertRaisesRegex(ValueError, "supposed to be"):
            plot_pareto_front(s1, target_names=["a", "b", "c"])
        with self.assertRaisesRegex(ValueError, "only supports 2 or 3 targets"):
            plot_pareto_front(s3, targets=lambda t: t.values)
        with self.assertRaisesRegex(ValueError, "must be specified"):
            plot_pareto_front(s4, targets=lambda t: t.values)

        self.assertEqual(len(figures), 6)
        self.assertEqual([len(f.data) for f in figures], [3, 2, 3, 2, 2, 3])


if __name__ == "__main__":
    unittest.main()
