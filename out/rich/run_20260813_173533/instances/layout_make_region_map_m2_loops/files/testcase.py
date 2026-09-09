import hashlib
import unittest

from rich.console import Console
from rich.layout import Layout


def _seed_bytes(label: str, count: int) -> bytes:
    return hashlib.sha256(f"layout-region-map-m2-{label}".encode()).digest() * (
        (count // 32) + 1
    )


def _digest_rendered(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _render_layout(layout: Layout, width: int, height: int) -> str:
    console = Console(width=width, height=height, force_terminal=False, color_system=None)
    with console.capture() as capture:
        console.print(layout, height=height)
    return capture.get()


def _build_chain(seed: str, depth: int, splitter: str) -> Layout:
    root = Layout(name=f"chain-root-{seed[:6]}")
    current = root
    raw = _seed_bytes(seed, depth)
    for index in range(depth):
        child = Layout(name=f"chain-{seed[:4]}-{index}")
        if splitter == "row":
            current.split_row(child)
        else:
            current.split_column(child)
        current = child
    return root


def _build_wide_split(seed: str, child_count: int, splitter: str) -> Layout:
    root = Layout(name=f"wide-{seed[:6]}")
    children = [Layout(name=f"wide-{seed[:4]}-{index}") for index in range(child_count)]
    if splitter == "row":
        root.split_row(*children)
    else:
        root.split_column(*children)
    return root


def _build_binary_tree(seed: str, depth: int) -> Layout:
    root = Layout(name=f"bin-{seed[:6]}")

    def attach(node: Layout, level: int) -> None:
        if level >= depth:
            return
        left = Layout(name=f"bin-{seed[:4]}-L{level}")
        right = Layout(name=f"bin-{seed[:4]}-R{level}")
        if level % 2 == 0:
            node.split_row(left, right)
        else:
            node.split_column(left, right)
        attach(left, level + 1)
        attach(right, level + 1)

    attach(root, 0)
    return root


def _build_mixed_tree(seed: str, layers: int) -> Layout:
    root = Layout(name=f"mix-{seed[:6]}")
    current = root
    raw = _seed_bytes(seed, layers * 3)
    for layer in range(layers):
        count = 2 + (raw[layer] % 4)
        children = [
            Layout(name=f"mix-{seed[:4]}-{layer}-{index}") for index in range(count)
        ]
        if raw[layer + layers] % 2 == 0:
            current.split_row(*children)
        else:
            current.split_column(*children)
        current = children[raw[layer + 2 * layers] % count]
    return root


def _build_hidden_pruned_tree(seed: str, visible: int, hidden: int) -> Layout:
    root = Layout(name=f"hide-{seed[:6]}")
    shown = [Layout(name=f"vis-{seed[:4]}-{index}") for index in range(visible)]
    concealed = [
        Layout(name=f"hid-{seed[:4]}-{index}", visible=False)
        for index in range(hidden)
    ]
    root.split_row(*(shown + concealed))
    for index, child in enumerate(shown):
        if index % 2 == 0:
            child.split_column(
                Layout(name=f"vis-sub-a-{seed[:4]}-{index}"),
                Layout(name=f"vis-sub-b-{seed[:4]}-{index}"),
            )
    return root


def _build_incremental_split(seed: str, stages: int) -> Layout:
    root = Layout(name=f"inc-{seed[:6]}")
    raw = _seed_bytes(seed, stages)
    for stage in range(stages):
        child = Layout(name=f"inc-{seed[:4]}-{stage}")
        if stage == 0:
            root.split_column(child)
        else:
            root.add_split(child)
        if raw[stage] % 3 == 0:
            child.split_row(
                Layout(name=f"inc-row-{seed[:4]}-{stage}-0"),
                Layout(name=f"inc-row-{seed[:4]}-{stage}-1"),
            )
    return root


class LayoutMakeRegionMapLoopsTest(unittest.TestCase):
    def _assert_render_digest(self, layout: Layout, width: int, height: int) -> None:
        rendered = _render_layout(layout, width, height)
        digest = _digest_rendered(rendered)
        self.assertEqual(len(digest), 64)
        self.assertTrue(any(ch in "0123456789abcdef" for ch in digest))

    def test_placeholder_only(self) -> None:
        layout = Layout(name="solo")
        self._assert_render_digest(layout, 40, 12)

    def test_shallow_row_split(self) -> None:
        layout = _build_wide_split("shallow-row", 3, "row")
        self._assert_render_digest(layout, 48, 14)

    def test_shallow_column_split(self) -> None:
        layout = _build_wide_split("shallow-col", 4, "column")
        self._assert_render_digest(layout, 52, 16)

    def test_deep_column_chain(self) -> None:
        layout = _build_chain("deep-col", 11, "column")
        self._assert_render_digest(layout, 44, 18)

    def test_deep_row_chain(self) -> None:
        layout = _build_chain("deep-row", 13, "row")
        self._assert_render_digest(layout, 56, 12)

    def test_binary_tree_depth_four(self) -> None:
        layout = _build_binary_tree("bin-four", 4)
        self._assert_render_digest(layout, 64, 20)

    def test_binary_tree_depth_five(self) -> None:
        layout = _build_binary_tree("bin-five", 5)
        self._assert_render_digest(layout, 72, 22)

    def test_mixed_layered_tree(self) -> None:
        layout = _build_mixed_tree("mixed-layers", 7)
        self._assert_render_digest(layout, 60, 24)

    def test_wide_row_fanout(self) -> None:
        layout = _build_wide_split("wide-row", 9, "row")
        self._assert_render_digest(layout, 80, 10)

    def test_hidden_children_pruning(self) -> None:
        layout = _build_hidden_pruned_tree("hidden-prune", 5, 4)
        self._assert_render_digest(layout, 50, 15)

    def test_incremental_add_split(self) -> None:
        layout = _build_incremental_split("incremental", 6)
        self._assert_render_digest(layout, 58, 18)

    def test_burst_repeated_render(self) -> None:
        layout = _build_mixed_tree("burst", 5)
        digests = []
        for _ in range(3):
            digests.append(_digest_rendered(_render_layout(layout, 46, 16)))
        self.assertEqual(len(set(digests)), 1)

    def test_seeded_large_mixed_tree(self) -> None:
        raw = _seed_bytes("large-mixed", 16)
        depth = 6 + (raw[0] % 3)
        layout = _build_mixed_tree("large-mixed", depth)
        self._assert_render_digest(layout, 88, 28)
