import random
import unittest

from rich._inspect import Inspect


def _build_inspect_subject(seed: int, slot_count: int):
    """Build a class with a seeded mix of attrs, methods, privates, and errors."""
    rng = random.Random(seed)
    plain_fields: list[tuple[str, int]] = []
    method_sources: list[tuple[str, str]] = []
    private_fields: list[tuple[str, str]] = []
    failing_names: list[str] = []

    for index in range(slot_count):
        bucket = rng.randint(0, 9)
        if bucket < 4:
            plain_fields.append((f"attr_{index:03d}", rng.randint(-500, 500)))
        elif bucket < 7:
            method_name = f"method_{index:03d}"
            arg_default = rng.randint(0, 5)
            token = rng.choice(("north", "south", "east", "west"))
            body = (
                f"def {method_name}(self, axis={arg_default}, label='{token}'):\n"
                f"    '''Callable slot {index} for {method_name}.'''\n"
                f"    return axis\n"
            )
            method_sources.append((method_name, body))
        elif bucket < 9:
            private_fields.append(
                (f"_{index:03d}_private", rng.choice(("hidden", "secret", "quiet")))
            )
        else:
            failing_names.append(f"bad_{index:03d}")

    class Subject:
        """Primary doc paragraph for the inspect subject.

        Secondary paragraph kept out of the default help slice.
        """

    for name, value in plain_fields:
        setattr(Subject, name, value)

    for name, source in method_sources:
        namespace: dict = {}
        exec(source, namespace)
        setattr(Subject, name, namespace[name])

    for name, value in private_fields:
        setattr(Subject, name, value)

    for name in failing_names:

        def _make_failing_property(blocked_name: str):
            @property
            def _blocked(self):
                raise ValueError(f"cannot read {blocked_name}")

            return _blocked

        setattr(Subject, name, _make_failing_property(name))

    return Subject()


class TestInspectRenderCalls(unittest.TestCase):
    def test_render_interprocedural_calls(self) -> None:
        subject = _build_inspect_subject(seed=17, slot_count=40)
        inspector = Inspect(
            subject,
            methods=True,
            docs=True,
            private=True,
            dunder=False,
            sort=True,
            value=False,
            help=False,
            all=False,
        )
        renderables = list(inspector._render())

        table_rows = sum(
            piece.row_count for piece in renderables if hasattr(piece, "row_count")
        )
        self.assertGreater(len(renderables), 2)
        self.assertGreater(table_rows, 15)
        self.assertTrue(any(type(piece).__name__ == "Text" for piece in renderables))
