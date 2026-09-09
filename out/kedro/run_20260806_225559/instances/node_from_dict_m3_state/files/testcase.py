"""Deterministic pytest test for instance node_from_dict_m3_state.

Drives ``Node.run`` many times on nodes whose ``outputs`` argument is a
dict, so that the inner helper ``Node._outputs_to_dictionary._from_dict``
is exercised indirectly (run -> _run_with_no_inputs -> _outputs_to_dictionary
-> _from_dict) across many invocations, including two failing shapes.
"""

import random
import unittest

from kedro.pipeline import node

SEED = 0x5EED99
N_THREE = 14
N_TWO = 7
OUTPUTS_THREE = {"a0": "ds_m", "a1": "ds_n", "a2": "ds_p"}
OUTPUTS_TWO = {"b0": "ds_q", "b1": "ds_r"}


def _build_plan():
    """Build a deterministic, interleaved execution plan.

    Each entry is (kind, payload) where ``kind`` selects which node shape
    must consume the payload and whether the run is expected to succeed.
    """
    rng = random.Random(SEED)
    plan = []
    for i in range(N_THREE):
        base = rng.randint(1000, 9999) + 7919 * i
        plan.append(
            (
                "three",
                {"a0": base, "a1": base + i * i, "a2": (base * 3) % 9973},
            )
        )
    for j in range(N_TWO):
        base = rng.randint(2000, 8888) + 13 * j
        plan.append(("two", {"b0": base - j, "b1": base + 2 * j}))
    rng.shuffle(plan)
    # One run whose function returns a dict with a wrong key set.
    plan.insert(
        5,
        (
            "three_badkeys",
            {"a0": len(plan) + 101, "a9": len(plan) + 102, "a2": len(plan) + 103},
        ),
    )
    # One run whose function returns a list instead of a dict.
    plan.insert(13, ("two_badtype", [len(plan) * 2 + 1, len(plan) * 3 + 2]))
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
