import random
import unittest
import warnings

import optuna
from optuna.study import StudyDirection
from optuna.trial import TrialState
from optuna.trial import create_trial
from optuna.visualization import plot_hypervolume_history


optuna.logging.set_verbosity(optuna.logging.ERROR)
warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)


def _make_study(directions, seed, n_trials, low, high, infeasible_every=0, fail_every=0):
    rng = random.Random(seed)
    study = optuna.create_study(directions=directions)
    for i in range(n_trials):
        values = [float(rng.randint(low, high)) for _ in directions]
        if fail_every and i % fail_every == fail_every - 1:
            study.add_trial(create_trial(state=TrialState.FAIL))
            continue
        constraints = None
        if infeasible_every:
            c = float(rng.randint(-2, 2)) if i % infeasible_every == 0 else -1.0
            constraints = {"c0": c, "c1": float(rng.randint(-3, 0))}
        study.add_trial(create_trial(values=values, constraints=constraints))
    return study


class TestHypervolumeHistoryStates(unittest.TestCase):
    def _check(self, study, reference_point):
        fig = plot_hypervolume_history(study, reference_point)
        complete = [
            t for t in study.get_trials(deepcopy=False) if t.state == TrialState.COMPLETE
        ]
        ys = list(fig.data[0].y) if fig.data[0].y is not None else []
        self.assertEqual(len(ys), len(complete))
        for a, b in zip(ys, ys[1:]):
            self.assertLessEqual(a, b + 1e-9)
        return ys

    def test_two_min_objectives(self):
        study = _make_study(["minimize", "minimize"], 11, 18, 0, 9)
        self._check(study, [10.0, 10.0])

    def test_two_max_objectives(self):
        study = _make_study(["maximize", "maximize"], 23, 17, 1, 12)
        self._check(study, [0.0, 0.0])

    def test_mixed_directions(self):
        study = _make_study(["minimize", "maximize"], 37, 20, 0, 8)
        self._check(study, [8.0, 0.0])

    def test_three_objectives(self):
        study = _make_study(["minimize"] * 3, 41, 16, 0, 5)
        self._check(study, [6.0, 6.0, 6.0])

    def test_with_infeasible_trials(self):
        study = _make_study(["minimize", "minimize"], 53, 21, 0, 7, infeasible_every=3)
        self._check(study, [7.0, 7.0])

    def test_out_of_reference(self):
        study = _make_study(["minimize", "minimize"], 67, 19, 0, 14)
        self._check(study, [9.0, 11.0])

    def test_with_failed_trials(self):
        study = _make_study(["maximize", "minimize"], 71, 22, 2, 10, fail_every=4)
        self._check(study, [1.0, 11.0])

    def test_boundary_points(self):
        study = optuna.create_study(directions=["minimize", "minimize"])
        rng = random.Random(83)
        for _ in range(15):
            a = float(rng.choice([2, 4, 5, 6, 6]))
            b = float(rng.choice([1, 3, 6, 6, 7]))
            study.add_trial(create_trial(values=[a, b]))
        self._check(study, [6.0, 6.0])

    def test_staircase_then_dominator(self):
        study = optuna.create_study(directions=["minimize", "minimize"])
        pts = [(k, 12 - k) for k in range(1, 12, 2)]
        pts += [(k + 1, 12 - k) for k in range(1, 12, 3)]
        pts.append((1.0, 1.0))
        pts += [(k % 5, (3 * k) % 7) for k in range(6)]
        for a, b in pts:
            study.add_trial(create_trial(values=[float(a), float(b)]))
        self._check(study, [13.0, 13.0])

    def test_three_mixed_with_constraints(self):
        study = _make_study(
            ["maximize", "minimize", "maximize"], 97, 18, 0, 6, infeasible_every=2
        )
        self._check(study, [0.0, 7.0, 0.0])

    def test_no_completed_trials(self):
        study = optuna.create_study(directions=["minimize", "minimize"])
        for _ in range(3):
            study.add_trial(create_trial(state=TrialState.FAIL))
        ys = self._check(study, [5.0, 5.0])
        self.assertEqual(ys, [])

    def test_all_infeasible_then_feasible(self):
        study = optuna.create_study(
            directions=[StudyDirection.MINIMIZE, StudyDirection.MINIMIZE]
        )
        rng = random.Random(109)
        for i in range(16):
            vals = [float(rng.randint(0, 6)), float(rng.randint(0, 6))]
            c = 1.0 if i < 6 else float(rng.randint(-1, 1))
            study.add_trial(create_trial(values=vals, constraints={"c": c}))
        self._check(study, [6.0, 6.0])


if __name__ == "__main__":
    unittest.main()
