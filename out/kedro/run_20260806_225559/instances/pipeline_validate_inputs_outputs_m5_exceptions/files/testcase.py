"""Runtime QA testcase for instance pipeline_validate_inputs_outputs_m5_exceptions.

Exercises Kedro's modular-pipeline input/output validation indirectly:
each test method programmatically builds a chain pipeline (varying length,
auxiliary free inputs, parameter-consuming stages and transcoded dataset
names) and then calls the public `pipeline(...)` helper once with
method-specific `inputs`/`outputs`/`namespace` arguments. Some argument
combinations are valid and yield a new Pipeline object; others are rejected
by the validation logic during construction (anticipated by the test, so
every method stays green).
"""

import unittest

from kedro.pipeline import node, pipeline


def _unary(a):
    return a


def _binary(a, b):
    return a


def _ternary(a, b, c):
    return a


def _quaternary(a, b, c, d):
    return a


_FUNCS = {1: _unary, 2: _binary, 3: _ternary, 4: _quaternary}


def _chain_nodes(
    length,
    param_stage=None,
    all_params_stage=None,
    transcoded_first=False,
    transcoded_last=False,
    aux_inputs=0,
):
    """Build a linear chain of `length` nodes.

    Stage 0 consumes "src_0" (or "src_0@csv" when transcoded_first), stage i
    consumes "mid_{i}" and produces "mid_{i+1}"; every stage may additionally
    consume aux inputs "aux_0".., one stage may consume a single parameter
    "params:knob_<i>", and one stage may consume the whole "parameters".
    """
    nodes = []
    for i in range(length):
        ins = []
        if i == 0:
            ins.append("src_0@csv" if transcoded_first else "src_0")
        else:
            ins.append(f"mid_{i}")
        for j in range(aux_inputs):
            ins.append(f"aux_{j}")
        if param_stage is not None and i == param_stage:
            ins.append(f"params:knob_{i}")
        if all_params_stage is not None and i == all_params_stage:
            ins.append("parameters")
        out = f"mid_{i + 1}"
        if transcoded_last and i == length - 1:
            out = f"{out}@parquet"
        nodes.append(node(_FUNCS[len(ins)], ins, out, name=f"stage_{i:02d}"))
    return nodes


class TestValidateInputsOutputsCrashMatrix(unittest.TestCase):
    def _expect_crash(self, nodes, **kwargs):
        with self.assertRaises(Exception) as ctx:
            pipeline(nodes, **kwargs)
        # Generic, outcome-derived assertions only.
        self.assertIsInstance(ctx.exception, Exception)
        self.assertGreater(len(str(ctx.exception)), 10)

    def _expect_safe(self, nodes, expected_node_count, **kwargs):
        result = pipeline(nodes, **kwargs)
        self.assertEqual(len(result.nodes), expected_node_count)
        return result

    def test_case_00(self):
        nodes = _chain_nodes(14)
        result = self._expect_safe(
            nodes, 14, inputs={"src_0"}, outputs={"mid_14": "report_00"}
        )
        self.assertIn("report_00", result.outputs())

    def test_case_01(self):
        nodes = _chain_nodes(15)
        result = self._expect_safe(
            nodes, 15, inputs={"src_0": "feed_01"}, outputs={"mid_15": "report_01"}
        )
        self.assertIn("feed_01", result.inputs())
        self.assertIn("report_01", result.outputs())

    def test_case_02(self):
        nodes = _chain_nodes(13)
        self._expect_crash(nodes, inputs={"mid_6"})

    def test_case_03(self):
        nodes = _chain_nodes(16)
        self._expect_crash(nodes, inputs={"mid_16"})

    def test_case_04(self):
        nodes = _chain_nodes(14, param_stage=3)
        self._expect_crash(nodes, inputs={"params:knob_3"})

    def test_case_05(self):
        nodes = _chain_nodes(14, param_stage=2)
        result = self._expect_safe(
            nodes, 14, inputs={"src_0"}, outputs={"mid_14": "report_05"}
        )
        self.assertIn("report_05", result.outputs())

    def test_case_06(self):
        nodes = _chain_nodes(12)
        self._expect_crash(nodes, outputs={"src_0": "echo_06"})

    def test_case_07(self):
        nodes = _chain_nodes(13, transcoded_first=True)
        self._expect_crash(nodes, outputs={"src_0@csv": "echo_07"})

    def test_case_08(self):
        nodes = _chain_nodes(12, transcoded_last=True)
        result = self._expect_safe(nodes, 12, outputs={"mid_12@parquet": "report_08"})
        self.assertIn("report_08", result.outputs())

    def test_case_09(self):
        nodes = _chain_nodes(13, all_params_stage=5)
        self._expect_crash(nodes, inputs={"parameters"})

    def test_case_10(self):
        nodes = _chain_nodes(13)
        result = self._expect_safe(nodes, 13, namespace="ns_10")
        self.assertTrue(all(n.namespace == "ns_10" for n in result.nodes))

    def test_case_11(self):
        nodes = _chain_nodes(15, aux_inputs=2)
        self._expect_crash(nodes, inputs={"src_0", "aux_1", "mid_9"})

    def test_case_12(self):
        nodes = _chain_nodes(15, aux_inputs=3)
        result = self._expect_safe(
            nodes,
            15,
            inputs={"src_0", "aux_0", "aux_2"},
            outputs={"mid_15": "report_12"},
        )
        self.assertIn("report_12", result.outputs())

    def test_case_13(self):
        nodes = _chain_nodes(14, param_stage=7)
        self._expect_crash(nodes, inputs={"src_0", "params:knob_7"})


if __name__ == "__main__":
    unittest.main()
