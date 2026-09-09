import hashlib
import unittest
from io import StringIO

from rich import inspect as rich_inspect
from rich.console import Console


_BUILTIN_POOL = (
    len,
    abs,
    max,
    min,
    sum,
    all,
    any,
    repr,
    hash,
    chr,
    ord,
    hex,
    oct,
    bin,
    callable,
    getattr,
    setattr,
    iter,
    next,
    sorted,
    reversed,
    enumerate,
    zip,
    map,
    filter,
    range,
    print,
    open,
    type,
    isinstance,
    id,
)


def _digest(seed: int, label: str) -> bytes:
    return hashlib.sha256(f"inspect-sig-{seed}-{label}".encode()).digest()


def _make_method(index: int):
    code = (
        f"def method_{index}(self, arg_{index}: int = {index}) -> int:\n"
        f"    return arg_{index} + {index}\n"
    )
    namespace: dict = {}
    exec(code, namespace)
    return namespace[f"method_{index}"]


def _build_carrier(
    seed: int,
    *,
    label: str,
    method_count: int,
    builtin_count: int,
    coroutine_count: int = 0,
):
    digest = _digest(seed, label)
    attrs: dict = {}
    for i in range(method_count):
        attrs[f"method_{i}"] = _make_method(i + seed)
    for i in range(builtin_count):
        attrs[f"builtin_{i}"] = _BUILTIN_POOL[digest[i] % len(_BUILTIN_POOL)]
    for i in range(coroutine_count):
        code = (
            f"async def coro_{i}(self, token_{i}: str = 'c{i}') -> str:\n"
            f"    return token_{i}\n"
        )
        namespace: dict = {}
        exec(code, namespace)
        attrs[f"coro_{i}"] = namespace[f"coro_{i}"]
    return type(f"Carrier{seed}_{label}", (), attrs)


def _render_inspection(subject, **inspect_kwargs) -> str:
    buffer = StringIO()
    console = Console(file=buffer, width=96, force_terminal=False)
    rich_inspect(subject, console=console, **inspect_kwargs)
    return buffer.getvalue()


def _checksum(text: str) -> int:
    return sum(ord(ch) for ch in hashlib.sha256(text.encode()).hexdigest())


class InspectGetSignatureExceptionsTest(unittest.TestCase):
    def test_pure_python_methods_only(self) -> None:
        carrier = _build_carrier(11, label="pure", method_count=18, builtin_count=0)
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=False,
            value=False,
            private=False,
            dunder=False,
            all=False,
        )
        self.assertGreater(len(output), 40)
        self.assertIn("method_0", output)
        self.assertGreater(_checksum(output), 2000)

    def test_dense_builtin_attachments(self) -> None:
        carrier = _build_carrier(23, label="dense", method_count=2, builtin_count=22)
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=False,
            value=False,
            private=False,
            dunder=False,
            all=False,
        )
        self.assertGreater(len(output), 80)
        self.assertIn("builtin_", output)
        self.assertGreater(_checksum(output), 3500)

    def test_mixed_methods_and_builtins(self) -> None:
        carrier = _build_carrier(37, label="mixed", method_count=9, builtin_count=11)
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=False,
            value=False,
            private=False,
            dunder=False,
            all=False,
        )
        self.assertGreater(len(output), 60)
        self.assertGreater(_checksum(output), 2800)

    def test_dunder_surface_exposed(self) -> None:
        carrier = _build_carrier(41, label="dunder", method_count=3, builtin_count=5)
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=False,
            value=False,
            private=False,
            dunder=True,
            all=False,
        )
        self.assertGreater(len(output), 120)
        self.assertIn("__", output)
        self.assertGreater(_checksum(output), 4200)

    def test_all_attributes_enabled(self) -> None:
        carrier = _build_carrier(53, label="all", method_count=1, builtin_count=14)
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=False,
            value=False,
            all=True,
        )
        self.assertGreater(len(output), 150)
        self.assertGreater(_checksum(output), 4500)

    def test_callable_class_subject(self) -> None:
        carrier_cls = _build_carrier(61, label="cls", method_count=6, builtin_count=8)
        output = _render_inspection(
            carrier_cls,
            methods=True,
            docs=False,
            value=False,
            private=False,
            dunder=False,
            all=False,
        )
        self.assertGreater(len(output), 70)
        self.assertIn("class", output)
        self.assertGreater(_checksum(output), 3000)

    def test_async_callable_methods(self) -> None:
        carrier = _build_carrier(
            67,
            label="async",
            method_count=4,
            builtin_count=6,
            coroutine_count=5,
        )
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=False,
            value=False,
            private=False,
            dunder=False,
            all=False,
        )
        self.assertGreater(len(output), 55)
        self.assertIn("async def", output)
        self.assertGreater(_checksum(output), 2600)

    def test_private_attribute_surface(self) -> None:
        carrier = _build_carrier(71, label="private", method_count=5, builtin_count=9)

        def _hidden(self, token: str = "x") -> str:
            return token

        carrier._hidden = _hidden  # type: ignore[attr-defined]
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=False,
            value=False,
            private=True,
            dunder=False,
            all=False,
        )
        self.assertGreater(len(output), 65)
        self.assertIn("_hidden", output)
        self.assertGreater(_checksum(output), 2900)

    def test_seeded_wave_a(self) -> None:
        digest = _digest(79, "wave-a")
        method_count = 3 + (digest[0] % 7)
        builtin_count = 4 + (digest[1] % 13)
        carrier = _build_carrier(
            79, label="wave-a", method_count=method_count, builtin_count=builtin_count
        )
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=True,
            value=False,
            private=False,
            dunder=(digest[2] % 2 == 0),
            all=False,
        )
        self.assertGreater(len(output), 50)
        self.assertGreater(_checksum(output), 2400)

    def test_seeded_wave_b(self) -> None:
        digest = _digest(83, "wave-b")
        method_count = 2 + (digest[3] % 9)
        builtin_count = 6 + (digest[4] % 11)
        carrier = _build_carrier(
            83,
            label="wave-b",
            method_count=method_count,
            builtin_count=builtin_count,
            coroutine_count=1 + (digest[5] % 3),
        )
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=False,
            value=True,
            private=(digest[6] % 2 == 1),
            dunder=False,
            all=False,
        )
        self.assertGreater(len(output), 40)
        self.assertGreater(_checksum(output), 2200)

    def test_seeded_wave_c(self) -> None:
        digest = _digest(89, "wave-c")
        method_count = 1 + (digest[7] % 8)
        builtin_count = 8 + (digest[8] % 10)
        carrier = _build_carrier(
            89, label="wave-c", method_count=method_count, builtin_count=builtin_count
        )
        output = _render_inspection(
            carrier(),
            methods=True,
            docs=False,
            value=False,
            private=True,
            dunder=True,
            all=(digest[9] % 3 == 0),
        )
        self.assertGreater(len(output), 90)
        self.assertGreater(_checksum(output), 3800)

    def test_minimal_instance_without_method_scan(self) -> None:
        carrier = _build_carrier(97, label="minimal", method_count=12, builtin_count=0)
        output = _render_inspection(
            carrier(),
            methods=False,
            docs=False,
            value=True,
            private=False,
            dunder=False,
            all=False,
        )
        self.assertGreater(len(output), 20)
        self.assertNotIn("method_0 =", output)
        self.assertGreater(_checksum(output), 1500)
