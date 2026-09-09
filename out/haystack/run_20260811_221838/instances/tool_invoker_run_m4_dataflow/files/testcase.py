import random
import unittest

from haystack.components.agents import State
from haystack.components.tools.tool_invoker import ToolInvoker
from haystack.dataclasses import ChatMessage, ToolCall
from haystack.tools import Tool


_PARAMETERS = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "bias": {"type": "integer"}},
    "required": ["x"],
}


def _compute(x, bias=0):
    return {"value": (x * x + bias) % 97, "parity": (x + bias) % 2}


def _unstable(x, bias=0):
    if (x + bias) % 4 in (0, 1):
        raise RuntimeError("generated tool failure")
    return {"value": x - bias, "parity": x % 2}


def _streamable(x, bias=0, streaming_callback=None):
    return {"value": x + bias, "callback_seen": streaming_callback is not None}


def _tool(name, function=_compute, **kwargs):
    return Tool(
        name=name,
        description=f"Generated deterministic tool {name}",
        parameters=_PARAMETERS,
        function=function,
        **kwargs,
    )


def _calls(tool_names, amount, label):
    rng = random.Random(sum(map(ord, label)))
    return [
        ToolCall(
            tool_name=tool_names[(rng.randrange(len(tool_names)) + index * index) % len(tool_names)],
            arguments={"x": rng.randrange(3, 1000), **({"bias": index % 7} if index % 3 else {})},
            id=f"{label}-{index}-{rng.randrange(1000, 9000)}",
        )
        for index in range(amount)
    ]


def _messages(calls, label):
    width = 2 + (sum(map(ord, label)) % 5)
    grouped = [calls[start : start + width] for start in range(0, len(calls), width)]
    messages = []
    for index, group in enumerate(grouped):
        if (index + len(label)) % 2:
            messages.append(ChatMessage.from_user(text=f"context-{label}-{index}"))
        messages.append(ChatMessage.from_assistant(tool_calls=group))
    return messages


class _SelectiveState(State):
    def set(self, key, value, handler_override=None):
        if isinstance(value, int) and value % 3 == 1:
            raise ValueError("generated selective merge failure")
        super().set(key, value, handler_override)


class TestToolInvokerRunDataFlow(unittest.TestCase):
    def test_constructor_tool_many_successes(self):
        label = "constructor-success-grid"
        calls = _calls(["compute"], len(label), label)
        invoker = ToolInvoker(tools=[_tool("compute")], max_workers=3)
        result = invoker.run(messages=_messages(calls, label))
        self.assertEqual(len(result["tool_messages"]), len(calls))
        self.assertTrue(all(not item.tool_call_result.error for item in result["tool_messages"]))

    def test_supplied_state_injects_missing_arguments(self):
        label = "state-injection-wave"
        calls = _calls(["stateful"], len(label) + len("bias"), label)
        state = State(schema={"bias": {"type": int}}, data={"bias": len(label)})
        tool = _tool("stateful", inputs_from_state={"bias": "bias"})
        invoker = ToolInvoker(tools=[tool], max_workers=2)
        result = invoker.run(messages=_messages(calls, label), state=state)
        self.assertIs(result["state"], state)
        self.assertEqual(len(result["tool_messages"]), len(calls))

    def test_runtime_tools_override_constructor_mapping(self):
        label = "runtime-override-lattice"
        calls = _calls(["replacement"], len(label) - len("grid"), label)
        invoker = ToolInvoker(tools=[_tool("dormant")], max_workers=4)
        result = invoker.run(messages=_messages(calls, label), tools=[_tool("replacement")])
        self.assertEqual(len(result["tool_messages"]), len(calls))
        self.assertFalse(any(item.tool_call_result.error for item in result["tool_messages"]))

    def test_unknown_tools_become_messages(self):
        label = "unknown-only-spectrum"
        names = [f"missing_{index}" for index in range(len("names"))]
        calls = _calls(names, len(label), label)
        invoker = ToolInvoker(tools=[_tool("compute")], raise_on_failure=False, max_workers=2)
        result = invoker.run(messages=_messages(calls, label))
        self.assertEqual(len(result["tool_messages"]), len(calls))
        self.assertTrue(all(item.tool_call_result.error for item in result["tool_messages"]))

    def test_known_and_unknown_calls_interleave(self):
        label = "mixed-lookup-topology"
        names = ["compute"] + [f"absent_{index}" for index in range(len("gaps"))]
        calls = _calls(names, len(label) + len("mesh"), label)
        invoker = ToolInvoker(tools=[_tool("compute")], raise_on_failure=False, max_workers=3)
        result = invoker.run(messages=_messages(calls, label))
        flags = [item.tool_call_result.error for item in result["tool_messages"]]
        self.assertEqual(len(flags), len(calls))
        self.assertTrue(any(flags) and not all(flags))

    def test_invocation_failures_interleave_with_results(self):
        label = "worker-failure-mosaic"
        calls = _calls(["unstable", "compute"], len(label) + len("pool"), label)
        tools = [_tool("unstable", _unstable), _tool("compute")]
        invoker = ToolInvoker(tools=tools, raise_on_failure=False, max_workers=4)
        result = invoker.run(messages=_messages(calls, label))
        flags = [item.tool_call_result.error for item in result["tool_messages"]]
        self.assertEqual(len(flags), len(calls))
        self.assertTrue(any(flags) and not all(flags))

    def test_streaming_callback_receives_result_chunks(self):
        label = "streaming-result-cascade"
        calls = _calls(["compute"], len(label), label)
        chunks = []
        invoker = ToolInvoker(tools=[_tool("compute")], max_workers=3)
        result = invoker.run(messages=_messages(calls, label), streaming_callback=chunks.append)
        self.assertEqual(len(result["tool_messages"]), len(calls))
        self.assertGreater(len(chunks), len(calls))
        self.assertIsNotNone(chunks[-1].finish_reason)

    def test_constructor_streaming_callback_is_selected(self):
        label = "constructor-stream-channel"
        calls = _calls(["compute"], len(label) - len("path"), label)
        chunks = []
        invoker = ToolInvoker(tools=[_tool("compute")], streaming_callback=chunks.append, max_workers=2)
        result = invoker.run(messages=_messages(calls, label))
        self.assertEqual(len(result["tool_messages"]), len(calls))
        self.assertGreater(len(chunks), len(calls))

    def test_runtime_passthrough_reaches_compatible_tool(self):
        label = "passthrough-signature-map"
        calls = _calls(["streamable"], len(label), label)
        chunks = []
        invoker = ToolInvoker(
            tools=[_tool("streamable", _streamable)],
            enable_streaming_callback_passthrough=False,
            max_workers=3,
        )
        result = invoker.run(
            messages=_messages(calls, label),
            streaming_callback=chunks.append,
            enable_streaming_callback_passthrough=True,
        )
        self.assertEqual(len(result["tool_messages"]), len(calls))
        self.assertGreater(len(chunks), len(calls))

    def test_successful_outputs_merge_into_state(self):
        label = "state-output-accumulation"
        calls = _calls(["writer"], len(label) - len("key"), label)
        tool = _tool("writer", outputs_to_state={"value": {"source": "value"}})
        state = State(schema={"value": {"type": int}})
        invoker = ToolInvoker(tools=[tool], max_workers=4)
        result = invoker.run(messages=_messages(calls, label), state=state)
        self.assertEqual(len(result["tool_messages"]), len(calls))
        self.assertTrue(state.has("value"))

    def test_selective_merge_errors_skip_result_messages(self):
        label = "selective-merge-fault-pattern"
        calls = _calls(["writer"], len(label), label)
        tool = _tool("writer", outputs_to_state={"value": {"source": "value"}})
        state = _SelectiveState(schema={"value": {"type": int}})
        invoker = ToolInvoker(tools=[tool], raise_on_failure=False, max_workers=3)
        result = invoker.run(messages=_messages(calls, label), state=state)
        flags = [item.tool_call_result.error for item in result["tool_messages"]]
        self.assertEqual(len(flags), len(calls))
        self.assertTrue(any(flags) and not all(flags))

    def test_override_state_failures_and_streaming_mix(self):
        label = "combined-branch-interference"
        names = ["writer", "unstable", "unavailable"]
        calls = _calls(names, len(label) + len("flow"), label)
        writer = _tool("writer", outputs_to_state={"value": {"source": "value"}})
        tools = [writer, _tool("unstable", _unstable)]
        state = _SelectiveState(schema={"value": {"type": int}})
        chunks = []
        invoker = ToolInvoker(tools=[_tool("placeholder")], raise_on_failure=False, max_workers=4)
        result = invoker.run(
            messages=_messages(calls, label),
            state=state,
            streaming_callback=chunks.append,
            tools=tools,
        )
        flags = [item.tool_call_result.error for item in result["tool_messages"]]
        self.assertEqual(len(flags), len(calls))
        self.assertTrue(any(flags) and not all(flags))
        self.assertGreater(len(chunks), len("x"))
