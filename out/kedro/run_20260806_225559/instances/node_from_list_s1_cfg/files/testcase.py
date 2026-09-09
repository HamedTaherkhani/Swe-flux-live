"""Deterministic pytest test for instance node_from_list_s1_cfg.

Drives ``Node.run`` many times on nodes whose declared ``outputs`` are
lists of dataset names, so that the nested output-translation helper is
exercised indirectly (run -> _run_with_no_inputs -> _outputs_to_dictionary
-> list branch) across many invocations with mixed list/generator
payloads, including four runs that fail inside output translation.
"""

import random
import unittest

from kedro.pipeline import node

SEED = 0x5EED11
N_LIST_RUNS = 11
N_GEN_RUNS = 6
OUT_A = ["raw_alpha", "raw_beta", "raw_gamma"]
OUT_B = ["raw_delta", "raw_epsilon"]


def _build_plan():
    """Build a deterministic, interleaved execution plan.

    Each entry is ``(kind, payload)`` where ``kind`` encodes the payload
    shape, the failure mode (if any), and which node must consume it.
    """
    rng = random.Random(SEED)
    entries = []
    for i in range(N_LIST_RUNS):
        width = 3 if i % 2 == 0 else 2
        base = rng.randint(1000, 9999) + 7919 * i
        entries.append(
            (
                "list_a" if width == 3 else "list_b",
                [base + 17 * j for j in range(width)],
            )
        )
    for j in range(N_GEN_RUNS):
        width = 3 if j % 2 == 0 else 2
        rows = 3 + (j % 3)
        seed0 = rng.randint(2000, 8888) + 31 * j
        entries.append(
            ("gen_a" if width == 3 else "gen_b", (width, rows, seed0))
        )
    rng.shuffle(entries)
    # Deterministically interleave four failing runs (ascending insertion
    # order keeps the final positions fixed): a plain int payload, a
    # generator whose first item has the wrong length, a list of the wrong
    # length, and a generator whose first item is not a sequence.
    entries.insert(3, ("badtype_a", rng.randint(5000, 9999)))
    entries.insert(12, ("gen_badlen_a", (2, 4, rng.randint(2000, 8888))))
    entries.insert(16, ("badlen_b", [7919, 7920, 7921]))
    entries.insert(19, ("gen_badtype_b", (0, 4, rng.randint(2000, 8888))))
    return entries


class TestNodeFromListCfg(unittest.TestCase):
    def test_from_list_cfg_paths(self):
        plan = _build_plan()
        plan_iter = iter(plan)

        def produce():
            kind, payload = next(plan_iter)
            if kind.startswith("gen"):
                width, rows, seed0 = payload

                def _gen():
                    for r in range(rows):
                        if width == 0:
                            yield seed0 + 101 * r
                        else:
                            yield tuple(seed0 + 101 * r + c for c in range(width))

                return _gen()
            return payload

        node_a = node(func=produce, inputs=None, outputs=OUT_A, name="probe_list_a")
        node_b = node(func=produce, inputs=None, outputs=OUT_B, name="probe_list_b")

        ok_runs = 0
        failed_runs = 0
        for kind, payload in plan:
            target_node = node_a if kind.endswith("_a") else node_b
            if "bad" in kind:
                with self.assertRaises(ValueError):
                    target_node.run({})
                failed_runs += 1
                continue
            result = target_node.run({})
            ok_runs += 1
            declared = OUT_A if kind.endswith("_a") else OUT_B
            # Structural assertions only: run() must bind the function's
            # outputs to the declared dataset names in declared order.
            self.assertEqual(list(result.keys()), declared)
            if kind.startswith("gen"):
                width, rows, seed0 = payload
                expected = [
                    [seed0 + 101 * r + c for r in range(rows)]
                    for c in range(width)
                ]
                self.assertEqual([list(v) for v in result.values()], expected)
            else:
                self.assertEqual(list(result.values()), payload)

        self.assertEqual(ok_runs, N_LIST_RUNS + N_GEN_RUNS)
        self.assertEqual(failed_runs, 4)
        self.assertEqual(len(plan), N_LIST_RUNS + N_GEN_RUNS + 4)


if __name__ == "__main__":
    unittest.main()
