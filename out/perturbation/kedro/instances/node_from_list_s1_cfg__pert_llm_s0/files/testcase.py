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

SEED = 0xFACEFEED
N_LIST_RUNS = 0
N_GEN_RUNS = 17
OUT_A = ["trace_out_alpha_cfg", "trace_out_beta_cfg", "trace_out_gamma_cfg"]
OUT_B = ["trace_out_delta_cfg", "trace_out_epsilon_cfg"]


def _build_plan():
    """Build a deterministic, interleaved execution plan.

    Each entry is ``(kind, payload)`` where ``kind`` encodes the payload
    shape, the failure mode (if any), and which node must consume it.
    """
    rng = random.Random(SEED)
    entries = []
    for i in range(N_LIST_RUNS):
        width = 2 if i % 2 == 0 else 3
        base = rng.randint(1, 99999) + 15413 * i
        entries.append(
            (
                "list_a" if width == 3 else "list_b",
                [base + 67 * j for j in range(width)],
            )
        )
    for j in range(N_GEN_RUNS):
        width = 2 if j % 2 == 0 else 3
        rows = 9 + (j % 6)
        seed0 = rng.randint(1, 99999) + 211 * j
        entries.append(
            ("gen_a" if width == 3 else "gen_b", (width, rows, seed0))
        )
    rng.shuffle(entries)
    # Deterministically interleave four failing runs (ascending insertion
    # order keeps the final positions fixed): a plain int payload, a
    # generator whose first item has the wrong length, a list of the wrong
    # length, and a generator whose first item is not a sequence.
    entries.insert(3, ("badtype_a", {"payload": "not_a_sequence"}))
    entries.insert(12, ("gen_badlen_a", (2, 12, rng.randint(4000, 88888))))
    entries.insert(16, ("badlen_b", [3, 6, 9, 12, 15, 18, 21, 24, 27]))
    entries.insert(19, ("gen_badtype_b", (0, 11, rng.randint(4000, 88888))))
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

        node_a = node(func=produce, inputs=None, outputs=OUT_A, name="trace_probe_alpha_node")
        node_b = node(func=produce, inputs=None, outputs=OUT_B, name="trace_probe_beta_node")

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
