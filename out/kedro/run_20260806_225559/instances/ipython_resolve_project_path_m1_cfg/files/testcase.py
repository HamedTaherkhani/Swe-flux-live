"""Runtime control-flow coverage scenario for the kedro.ipython reload logic.

Drives the project-path resolution indirectly through `reload_kedro` and the
line-magic function `magic_reload_kedro` with several distinct
(path, local_namespace) combinations; everything downstream of the path
resolution inside `reload_kedro` is mocked out so the test is hermetic and
deterministic.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import kedro.ipython as kip


class _FakeContext:
    """Minimal stand-in for a KedroContext stored in the ipython namespace."""

    def __init__(self, project_path):
        self.project_path = project_path


class TestResolveProjectPathCfgRuntime(unittest.TestCase):
    def test_traced_run(self):
        base = Path(tempfile.mkdtemp(prefix="kedro_qa_m1_"))
        proj_a = base / "proj_a"
        proj_b = base / "proj_b"
        proj_a.mkdir(parents=True)
        proj_b.mkdir(parents=True)
        found = base / "found_proj"
        found.mkdir()

        resolved_a = Path(str(proj_a)).expanduser().resolve()

        with mock.patch.object(kip, "bootstrap_project") as m_bootstrap, mock.patch.object(
            kip, "_remove_cached_modules"
        ), mock.patch.object(kip, "configure_project"), mock.patch.object(
            kip, "KedroSession"
        ) as m_session, mock.patch.object(
            kip, "get_ipython"
        ) as m_get_ipython, mock.patch.object(
            kip, "load_entry_points", return_value=[]
        ):

            # 1. explicit path, no local namespace at all
            kip.reload_kedro(str(proj_a))

            # 2. explicit path, namespace context already holds the same path
            ns_same = {"context": _FakeContext(resolved_a)}
            kip.reload_kedro(str(proj_a), None, None, ns_same)

            # 3. explicit path given through the line magic, namespace context
            #    holds a different path
            ns_diff = {"context": _FakeContext(resolved_a)}
            kip.magic_reload_kedro(str(proj_b), local_ns=ns_diff)

            # 4. no path: resolved from the namespace's stored context
            kip.reload_kedro(None, None, None, ns_same)

            # 5. no path, empty namespace: project discovered on disk
            with mock.patch.object(kip, "find_kedro_project", return_value=found):
                kip.reload_kedro(None, None, None, {})

            # 6. no path, no namespace, nothing discoverable on disk
            with mock.patch.object(kip, "find_kedro_project", return_value=None):
                kip.reload_kedro()

        assert m_bootstrap.call_count == 6
        assert m_session.create.call_count == 6
        assert m_get_ipython.return_value.push.call_count == 6
