"""Deterministic pytest test for instance node_from_dict_m3_state.

Drives ``Node.run`` many times on nodes whose ``outputs`` argument is a
dict, so that the inner helper ``Node._outputs_to_dictionary._from_dict``
is exercised indirectly (run -> _run_with_no_inputs -> _outputs_to_dictionary
-> _from_dict) across many invocations, including two failing shapes.
"""

import random
import unittest

from kedro.pipeline import node

SEED = 0xC0FFEE42
N_THREE = 40
N_TWO = 20
OUTPUTS_THREE = {"k_alpha": "metrics_a", "k_beta": "metrics_b", "k_gamma": "metrics_c"}
OUTPUTS_TWO = {"k_delta": "series_x", "k_epsilon": "series_y"}


def _build_plan():
    """Build a deterministic, interleaved execution plan.

    Each entry is (kind, payload) where ``kind`` selects which node shape
    must consume the payload and whether the run is expected to succeed.
    """
    rng = random.Random(SEED)
    plan = []
    for i in range(N_THREE):
        base = rng.randint(-4096, 99999) + 1543 * i
        plan.append(
            (
                "three",
                {
                    "k_alpha": base,
                    "k_beta": base + i * i * 31,
                    "k_gamma": (base * 7 + 13 * i) % 8191,
                },
            )
        )
    for j in range(N_TWO):
        base = rng.randint(-8192, 77777) + 97 * j
        plan.append(
            (
                "two",
                {
                    "k_delta": base - j * j,
                    "k_epsilon": (base * 11 - 5 * j) % 32768,
                },
            )
        )
    rng.shuffle(plan)
    # One run whose function returns a dict with a wrong key set.
    plan.insert(
        17,
        (
            "three_badkeys",
            {
                "k_alpha": len(plan) + 1009,
                "k_wrong": len(plan) + 1013,
                "k_gamma": len(plan) + 1019,
            },
        ),
    )
    # One run whose function returns a list instead of a dict.
    plan.insert(41, ("two_badtype", [len(plan) * 5 + 7, len(plan) * 7 + 11]))
    return plan


class TestNodeFromDictState(unittest.TestCase):
    def test_from_dict_state(self):
        plan = _build_plan()
        plan_iter = iter(plan)

        def produce():
            return next(plan_iter)[1]

        node_three = node(
            func=produce,
            inputs=None,
            outputs=OUTPUTS_THREE,
            name="probe_three",
        )
        node_two = node(
            func=produce,
            inputs=None,
            outputs=OUTPUTS_TWO,
            name="probe_two",
        )

        ok_runs = 0
        failed_runs = 0
        for kind, payload in plan:
            if kind.startswith("three"):
                target_node, declared = node_three, OUTPUTS_THREE
            else:
                target_node, declared = node_two, OUTPUTS_TWO
            if kind.endswith("badkeys") or kind.endswith("badtype"):
                with self.assertRaises(ValueError):
                    target_node.run({})
                failed_runs += 1
                continue
            result = target_node.run({})
            ok_runs += 1
            # Structural assertions only: the mapping returned by run() must
            # translate function-output keys to dataset names, preserving the
            # values in the node's declared key order.
            self.assertEqual(sorted(result.keys()), sorted(declared.values()))
            self.assertEqual(
                list(result.values()),
                [payload[k] for k in declared.keys()],
            )
            self.assertTrue(all(isinstance(v, int) for v in result.values()))

        self.assertEqual(ok_runs, N_THREE + N_TWO)
        self.assertEqual(failed_runs, 2)
        self.assertEqual(len(plan), N_THREE + N_TWO + 2)


if __name__ == "__main__":
    unittest.main()
