import hashlib
import unittest
from io import StringIO

from rich.console import Console
from rich.progress import Progress


def _nested_payload(index: int, byte: int) -> dict:
    depth = (byte % 4) + 1
    node: dict = {"idx": index, "leaf": byte % 97}
    current = node
    for level in range(depth):
        child = {"level": level, "val": (byte + level * 13) % 251}
        current["child"] = child
        current = child
    return node


def _build_operations(seed: int) -> list[dict]:
    digest = hashlib.sha256(f"console-print-s4-{seed}".encode()).digest()
    operations: list[dict] = []
    for index in range(28):
        byte = digest[index % len(digest)]
        kind = byte % 7
        if kind == 0:
            operations.append(
                {
                    "kind": "out",
                    "parts": [f"plain-{index}", f"code-{byte % 16}"],
                }
            )
        elif kind == 1:
            operations.append(
                {
                    "kind": "out",
                    "parts": [f"styled-{index}"],
                    "style": "bold cyan",
                }
            )
        elif kind == 2:
            operations.append(
                {
                    "kind": "rule",
                    "title": f"Block {index}-{byte % 32}",
                }
            )
        elif kind == 3:
            operations.append({"kind": "line", "count": (byte % 4) + 1})
        elif kind == 4:
            operations.append(
                {
                    "kind": "json",
                    "payload": _nested_payload(index, byte),
                }
            )
        elif kind == 5:
            operations.append({"kind": "progress", "steps": (byte % 6) + 4})
        else:
            operations.append(
                {
                    "kind": "input",
                    "prompt": f"Q{index}? ",
                    "answer": f"a{byte % 64}",
                }
            )
    return operations


class ConsolePrintDataflowTest(unittest.TestCase):
    def test_seeded_indirect_print_dataflow(self) -> None:
        buffer = StringIO()
        console = Console(file=buffer, width=72, force_terminal=False)
        operations = _build_operations(31)
        checksum = 0

        for op in operations:
            kind = op["kind"]
            if kind == "out":
                style = op.get("style")
                if style is None:
                    console.out(*op["parts"])
                else:
                    console.out(*op["parts"], style=style)
            elif kind == "rule":
                console.rule(op["title"])
            elif kind == "line":
                console.line(op["count"])
            elif kind == "json":
                console.print_json(data=op["payload"])
            elif kind == "progress":
                steps = op["steps"]
                with Progress(console=console) as progress:
                    task = progress.add_task("run", total=steps)
                    for _ in range(steps):
                        progress.advance(task)
            elif kind == "input":
                stream = StringIO(op["answer"] + "\n")
                reply = console.input(op["prompt"], stream=stream)
                checksum += len(reply)

        rendered = buffer.getvalue()
        self.assertGreater(len(rendered), 0)
        self.assertGreater(checksum, 0)
        digest = hashlib.sha256(rendered.encode()).hexdigest()
        self.assertEqual(len(digest), 64)
