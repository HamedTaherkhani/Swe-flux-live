import random
import sys
import unittest

from rich.traceback import install


def _build_deep_stack(depth: int, body):
    """Return a callable that invokes `body` after `depth` nested calls."""
    if depth <= 0:
        return body

    def layer():
        return _build_deep_stack(depth - 1, body)()

    layer.__name__ = f"frame_{depth}"
    return layer


def _make_leaf_error(tag: str, seed: int):
    rng = random.Random(seed)
    payload = {f"k{i}": rng.randint(0, 9) for i in range(20)}
    raise RuntimeError(f"{tag}:{sum(payload.values())}")


class TestTracebackExtractInvocationPath(unittest.TestCase):
    def test_excepthook_drives_extract_paths(self):
        random.seed(0xC0FFEE)
        old_hook = install(show_locals=True, locals_hide_sunder=True)
        try:

            def run_leaf(tag: str, seed: int):
                def leaf():
                    _make_leaf_error(tag, seed)

                _build_deep_stack(18, leaf)()

            # Invocation 1: single runtime error with a deep stack.
            try:
                run_leaf("alpha", 11)
            except RuntimeError as exc:
                sys.excepthook(type(exc), exc, exc.__traceback__)

            # Invocation 2: explicit __cause__ chain (while-loop continues twice).
            try:
                try:
                    run_leaf("beta", 22)
                except RuntimeError as first:
                    try:
                        run_leaf("gamma", 33)
                    except RuntimeError as second:
                        second.__cause__ = first
                        raise
            except RuntimeError as exc:
                sys.excepthook(type(exc), exc, exc.__traceback__)

            # Invocation 3: syntax error branch.
            try:
                compile("if True\n    pass", "<syntax_probe>", "exec")
            except SyntaxError as exc:
                sys.excepthook(type(exc), exc, exc.__traceback__)

            # Invocations 4-8: ExceptionGroup fans out recursive extract calls.
            group_members = []
            for idx in range(5):
                try:
                    run_leaf(f"grp{idx}", 100 + idx)
                except RuntimeError as member:
                    group_members.append(member)
            bundle = ExceptionGroup("bundle", group_members)
            sys.excepthook(type(bundle), bundle, bundle.__traceback__)

        finally:
            sys.excepthook = old_hook

        self.assertGreaterEqual(len(group_members), 1)
