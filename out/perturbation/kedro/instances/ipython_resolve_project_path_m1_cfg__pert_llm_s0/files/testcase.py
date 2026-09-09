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
        base = Path(tempfile.mkdtemp(prefix="kedro_qa_m1_hard_variant_0x_"))
        nest = base / "warehouse" / "tier-1" / "deploy"
        nest.mkdir(parents=True)
        actual_a = nest / "actual_alpha"
        actual_a.mkdir()
        proj_a = nest / "link_alpha"
        proj_a.symlink_to(actual_a)
        actual_b = nest / "beta_staging" / "proj_b"
        actual_b.mkdir(parents=True)
        proj_b = actual_b
        found_real = base / "discovered" / "kedro_root"
        found_real.mkdir(parents=True)
        found_link = base / "discovered" / "kedro_link"
        found_link.symlink_to(found_real)
        found = found_link / ".." / "discovered" / "kedro_link"
        found_disc = base / "orphan_discovery" / "deep" / "leaf"
        found_disc.mkdir(parents=True)

        resolved_a = actual_a.resolve()
        resolved_b = actual_b.resolve()
        resolved_found = found.resolve()

        path_a_explicit = str(proj_a / ".." / "link_alpha" / ".")
        path_a_call2 = str(proj_b) + "/"
        path_b_magic = str(proj_a / ".." / "link_alpha")

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
            kip.reload_kedro(path_a_explicit)

            # 2. explicit path, namespace context already holds the same path
            ns_same = {
                "context": _FakeContext(resolved_a),
                "catalog": object(),
                "_ipython_kernel_initialization": False,
                "pipelines": {"__default__": (), "ingest": (1, 2, 3)},
            }
            kip.reload_kedro(path_a_call2, None, None, ns_same)

            # 3. explicit path given through the line magic, namespace context
            #    holds a different path
            ns_diff = {
                "context": _FakeContext(resolved_b),
                "session": _FakeContext(resolved_a),
                "extra_paths": [resolved_found, resolved_b, resolved_a, base],
            }
            kip.magic_reload_kedro(path_b_magic, local_ns=ns_diff)

            # 4. no path: resolved from the namespace's stored context
            kip.reload_kedro(None, None, None, ns_same)

            # 5. no path, empty namespace: project discovered on disk
            with mock.patch.object(kip, "find_kedro_project", return_value=found):
                kip.reload_kedro(
                    None,
                    None,
                    None,
                    {
                        "context": type("BareContext", (), {})(),
                        "init_kedro": 0,
                        "spark": None,
                    },
                )

            # 6. no path, no namespace, nothing discoverable on disk
            with mock.patch.object(
                kip, "find_kedro_project", return_value=found_disc
            ):
                kip.reload_kedro()

        assert m_bootstrap.call_count == 6
        assert m_session.create.call_count == 6
        assert m_get_ipython.return_value.push.call_count == 6
