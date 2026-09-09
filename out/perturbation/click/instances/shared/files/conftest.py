import os
from pathlib import Path
import sys


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import trace_plugin  # noqa: E402  pylint: disable=wrong-import-position


def pytest_runtest_setup(item):
    if os.environ.get("TRACE_ON") == "1":
        trace_plugin.enable()


def pytest_runtest_teardown(item, nextitem):
    trace_plugin.disable()
