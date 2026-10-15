from __future__ import annotations

import random
import unittest

from optuna.visualization._optimization_history import _get_optimization_history_plot
from optuna.visualization._optimization_history import _OptimizationHistoryInfo
from optuna.visualization._optimization_history import _ValuesInfo
from optuna.visualization._optimization_history import _ValueState


def _make_states(rng: random.Random, n: int, p_inf: float, p_inc: float) -> list[_ValueState]:
    states = []
    for _ in range(n):
        r = rng.random()
        if r < p_inc:
            states.append(_ValueState.Incomplete)
        elif r < p_inc + p_inf:
            states.append(_ValueState.Infeasible)
        else:
            states.append(_ValueState.Feasible)
    return states


def _make_info(
    rng: random.Random,
    n: int,
    p_inf: float,
    p_inc: float,
    label: str,
    with_best: bool = True,
    with_stds: bool = False,
) -> _OptimizationHistoryInfo:
    states = _make_states(rng, n, p_inf, p_inc)
    values = [
        float("nan") if s == _ValueState.Incomplete else round(rng.uniform(-5.0, 5.0), 3)
        for s in states
    ]
    stds = [round(rng.uniform(0.0, 1.0), 3) for _ in range(n)] if with_stds else None
    best_info = None
    if with_best:
        best, cur = [], float("inf")
        for v, s in zip(values, states):
            if s == _ValueState.Feasible:
                cur = min(cur, v)
            best.append(cur)
        best_stds = [round(x / 2, 3) for x in stds] if stds is not None else None
        best_info = _ValuesInfo(best, best_stds, "Best Value", states)
    return _OptimizationHistoryInfo(
        trial_numbers=list(range(n)),
        values_info=_ValuesInfo(values, stds, label, states),
        best_values_info=best_info,
    )


def _expected_trace_count(info_list: list[_OptimizationHistoryInfo]) -> int:
    count = 0
    for info in info_list:
        count += 2
        if info.best_values_info is not None:
            count += 1
            if info.best_values_info.stds is not None:
                count += 2
    return count


class TestOptimizationHistoryPlotLoops(unittest.TestCase):
    def _run(self, info_list: list[_OptimizationHistoryInfo], name: str = "Objective Value"):
        fig = _get_optimization_history_plot(info_list, name)
        self.assertEqual(len(fig.data), _expected_trace_count(info_list))
        self.assertEqual(fig.layout.yaxis.title.text, name)
        return fig

    def test_single_study_mostly_feasible(self) -> None:
        rng = random.Random(101)
        self._run([_make_info(rng, rng.randint(25, 40), 0.15, 0.1, "Objective Value")])

    def test_single_study_heavy_infeasible(self) -> None:
        rng = random.Random(202)
        self._run([_make_info(rng, rng.randint(20, 35), 0.55, 0.05, "Objective Value")])

    def test_three_studies_mixed(self) -> None:
        rng = random.Random(303)
        infos = [
            _make_info(rng, rng.randint(12, 30), 0.1 * (k + 1), 0.1, f"Objective Value of s{k}")
            for k in range(3)
        ]
        self._run(infos)

    def test_many_incomplete(self) -> None:
        rng = random.Random(404)
        self._run(
            [_make_info(rng, rng.randint(30, 45), 0.2, 0.5, "Objective Value", with_best=False)]
        )

    def test_error_bar_single(self) -> None:
        rng = random.Random(505)
        self._run(
            [_make_info(rng, rng.randint(18, 26), 0.0, 0.0, "Objective Value", with_stds=True)]
        )

    def test_error_bar_without_best(self) -> None:
        rng = random.Random(606)
        self._run(
            [
                _make_info(
                    rng, rng.randint(15, 22), 0.3, 0.1, "Score", with_best=False, with_stds=True
                )
            ],
            "Score",
        )

    def test_five_small_studies(self) -> None:
        rng = random.Random(707)
        infos = [
            _make_info(rng, 4 + 3 * k + rng.randint(0, 5), 0.25, 0.15, f"Objective Value of s{k}")
            for k in range(5)
        ]
        self._run(infos)

    def test_large_single_study(self) -> None:
        rng = random.Random(808)
        self._run([_make_info(rng, rng.randint(60, 80), 0.3, 0.2, "Objective Value")])

    def test_mixed_error_bar_and_plain(self) -> None:
        rng = random.Random(909)
        infos = [
            _make_info(rng, rng.randint(10, 20), 0.2, 0.2, "Objective Value of a"),
            _make_info(rng, rng.randint(10, 20), 0.0, 0.0, "Objective Value of b", with_stds=True),
            _make_info(rng, rng.randint(10, 20), 0.4, 0.0, "Objective Value of c", with_best=False),
        ]
        self._run(infos)

    def test_custom_target_name_two_studies(self) -> None:
        rng = random.Random(1111)
        infos = [
            _make_info(rng, rng.randint(16, 28), 0.35, 0.25, f"Loss of run{k}", with_best=False)
            for k in range(2)
        ]
        self._run(infos, "Loss")

    def test_nearly_all_incomplete(self) -> None:
        rng = random.Random(1212)
        infos = [
            _make_info(rng, rng.randint(20, 30), 0.1, 0.8, f"Objective Value of s{k}")
            for k in range(2)
        ]
        self._run(infos)

    def test_empty_info_list(self) -> None:
        self._run([])

    def test_growing_studies(self) -> None:
        rng = random.Random(1313)
        infos = []
        size = rng.randint(3, 6)
        for k in range(4):
            infos.append(_make_info(rng, size, 0.2 + 0.1 * k, 0.1, f"Objective Value of g{k}"))
            size = size * 2 - rng.randint(0, 3)
        self._run(infos)


if __name__ == "__main__":
    unittest.main()
