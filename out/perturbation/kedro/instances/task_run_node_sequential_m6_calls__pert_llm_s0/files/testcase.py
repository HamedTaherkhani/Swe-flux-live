"""Deterministic exercise of the sequential pipeline runner's per-node task
execution path.

A seeded random generator programmatically builds a 14-node Kedro pipeline:
regular nodes with one or two inputs and one or two outputs, two streaming
generator nodes (one yielding tuples, one yielding dicts), and a final
reducer node.  The pipeline is run once end to end through ``SequentialRunner``
(default arguments) against a ``DataCatalog`` backed by ``MemoryDataset``
objects, with a real pluggy hook manager carrying one registered
``before_node_run`` hook implementation that records the nodes it sees.

Final catalog contents are asserted against expected values that the test
simulates independently while constructing the pipeline.
"""

import random
import unittest

from kedro.framework.hooks import _create_hook_manager
from kedro.framework.hooks.manager import _register_hooks
from kedro.framework.hooks.markers import hook_impl
from kedro.io import DataCatalog, MemoryDataset
from kedro.pipeline import Pipeline, node
from kedro.runner import SequentialRunner

SEED = 99123456
RAW_LEN = 64
N_STAGE1 = 13
N_STAGE2 = 18
GEN_A_CHUNKS = 23
GEN_B_CHUNKS = 19


def _make_stage1_func(weights, offset):
    def stage1(data):
        return sum(v * w for v, w in zip(data, weights)) + offset

    return stage1


def _make_unary(factor, bias):
    def unary(a):
        return a * factor + bias

    return unary


def _make_binary(factor, bias):
    def binary(a, b):
        return a * factor - b + bias

    return binary


def _make_split(factor):
    def split(a, b):
        return {"res": a + factor * b, "aux": a - b}

    return split


def _make_stream_pairs(n_chunks, step):
    def stream_pairs(seed_val):
        base = seed_val % 50
        for i in range(n_chunks):
            yield base + i * step, (base + i) ** 2 % 97

    return stream_pairs


def _make_stream_dicts(n_chunks):
    def stream_dicts(x):
        acc = x % 31
        for i in range(n_chunks):
            acc = (acc * 3 + i) % 1000
            yield {"val": acc, "tag": "t%d" % i}

    return stream_dicts


def _reduce(a, b):
    return 2 * a + b


class _RecordingHooks:
    def __init__(self):
        self.before_node_run_nodes = []

    @hook_impl
    def before_node_run(self, node, catalog, inputs, is_async, run_id):
        self.before_node_run_nodes.append(node.name)
        return None


class TestSequentialRunCoverage(unittest.TestCase):
    def test_sequential_pipeline_coverage(self):
        rng = random.Random(SEED)
        raw = [rng.randrange(-127, 128) for _ in range(RAW_LEN)]

        nodes = []
        values = {"raw": raw}

        for i in range(N_STAGE1):
            weights = [rng.randrange(1, 17) for _ in range(RAW_LEN)]
            offset = rng.randrange(-999, 1000)
            fn = _make_stage1_func(weights, offset)
            out = "s1_%d" % i
            nodes.append(
                node(fn, inputs="raw", outputs=out, name="stage1_node_%d" % i)
            )
            values[out] = fn(raw)

        for j in range(N_STAGE2):
            a = "s1_%d" % (j % N_STAGE1)
            bias = rng.randrange(-127, 128)
            factor = rng.randrange(2, 17)
            if j % 3 == 0:
                b = "s1_%d" % ((j + 2) % N_STAGE1)
                fn = _make_split(factor)
                res, aux = "s2_%d" % j, "s2_%d_aux" % j
                nodes.append(
                    node(
                        fn,
                        inputs=[a, b],
                        outputs={"res": res, "aux": aux},
                        name="stage2_node_%d" % j,
                    )
                )
                out_dict = fn(values[a], values[b])
                values[res] = out_dict["res"]
                values[aux] = out_dict["aux"]
            elif j % 2 == 0:
                fn = _make_unary(factor, bias)
                res = "s2_%d" % j
                nodes.append(
                    node(fn, inputs=a, outputs=res, name="stage2_node_%d" % j)
                )
                values[res] = fn(values[a])
            else:
                b = "s1_%d" % ((j + 2) % N_STAGE1)
                fn = _make_binary(factor, bias)
                res = "s2_%d" % j
                nodes.append(
                    node(fn, inputs=[a, b], outputs=res, name="stage2_node_%d" % j)
                )
                values[res] = fn(values[a], values[b])

        step = rng.randrange(3, 23)
        gen_a = _make_stream_pairs(GEN_A_CHUNKS, step)
        nodes.append(
            node(
                gen_a,
                inputs="s2_7",
                outputs=["pairs_left", "pairs_right"],
                name="stream_pairs_node",
            )
        )
        base = values["s2_7"] % 50
        last_left = base + (GEN_A_CHUNKS - 1) * step
        last_right = (base + GEN_A_CHUNKS - 1) ** 2 % 97

        gen_b = _make_stream_dicts(GEN_B_CHUNKS)
        nodes.append(
            node(
                gen_b,
                inputs="s2_13",
                outputs={"val": "tags_val", "tag": "tags_tag"},
                name="stream_dicts_node",
            )
        )
        acc = values["s2_13"] % 31
        for i in range(GEN_B_CHUNKS):
            acc = (acc * 3 + i) % 1000
        last_val = acc
        last_tag = "t%d" % (GEN_B_CHUNKS - 1)

        nodes.append(
            node(
                _reduce,
                inputs=["pairs_left", "tags_val"],
                outputs="final",
                name="final_reducer_node",
            )
        )
        expected_final = _reduce(last_left, last_val)

        catalog = DataCatalog(datasets={"raw": MemoryDataset(data=list(raw))})
        hook_manager = _create_hook_manager()
        recorder = _RecordingHooks()
        _register_hooks(hook_manager, [recorder])

        runner = SequentialRunner()
        free_outputs = runner.run(
            Pipeline(nodes), catalog, hook_manager=hook_manager
        )

        # The runner releases intermediate datasets once nothing downstream
        # needs them, so only free (unconsumed) outputs remain loadable.
        used_as_input = set()
        for n in nodes:
            used_as_input.update(n.inputs)
        produced = (set(values) - {"raw"}) | {
            "pairs_left",
            "pairs_right",
            "tags_val",
            "tags_tag",
            "final",
        }
        free_names = produced - used_as_input
        expected_free = dict(values)
        expected_free.update(
            {
                "pairs_right": last_right,
                "tags_tag": last_tag,
                "final": expected_final,
            }
        )

        self.assertIn("pairs_left", used_as_input)
        self.assertEqual(set(free_outputs), free_names)
        for name in sorted(free_names):
            self.assertEqual(catalog.load(name), expected_free[name])

        self.assertEqual(len(recorder.before_node_run_nodes), len(nodes))
        self.assertEqual(
            sorted(recorder.before_node_run_nodes),
            sorted(n.name for n in nodes),
        )


if __name__ == "__main__":
    unittest.main()
