"""Drive werkzeug's debugger PIN derivation across many simulated hosts.

Each simulated host decides what the machine-id probing code sees: which
files exist, what they contain, whether the macOS ``ioreg`` tool can be
spawned, and (optionally) a Windows registry.  The probing is reached only
through ``get_pin_and_cookie_name``.
"""

import builtins
import contextlib
import os
import random
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import werkzeug.debug as wdebug

MACHINE_ID = "/etc/machine-id"
BOOT_ID = "/proc/sys/kernel/random/boot_id"
CGROUP = "/proc/self/cgroup"

_real_open = builtins.open


def demo_app(environ, start_response):  # pragma: no cover - never served
    start_response("200 OK", [])
    return [b""]


class SimulatedHost:
    """A fake machine. ``files`` maps a probed path to a (kind, payload) spec.

    kinds: "data" (bytes file), "blank" (whitespace-only file), "absent",
    "folder", "nested" (path below a regular file), "sink" (opened for
    writing only), "text" (opened in text mode). Paths not listed in
    ``files`` are unknown to the host's path table.
    """

    def __init__(self, root, files, ioreg=("absent", None), registry=None):
        self.root = root
        self.files = files
        self.ioreg = ioreg
        self.registry = registry
        self.table = {}
        self.modes = {}
        for n, (path, (kind, payload)) in enumerate(sorted(files.items())):
            self.table[path], self.modes[path] = self._materialize(n, kind, payload)

    def _materialize(self, n, kind, payload):
        base = os.path.join(self.root, f"f{n}")
        if kind == "data":
            with _real_open(base, "wb") as f:
                f.write(payload)
            return base, "rb"
        if kind == "blank":
            with _real_open(base, "wb") as f:
                f.write(b" \n\t\n" if payload else b"")
            return base, "rb"
        if kind == "absent":
            return base + ".missing", "rb"
        if kind == "folder":
            os.makedirs(base, exist_ok=True)
            return base, "rb"
        if kind == "nested":
            with _real_open(base, "wb") as f:
                f.write(b"x")
            return os.path.join(base, "child"), "rb"
        if kind == "sink":
            return base, "wb"
        if kind == "text":
            with _real_open(base, "w") as f:
                f.write(payload + "\n")
            return base, "r"
        raise AssertionError(kind)

    # -- replacements -------------------------------------------------
    def open(self, name, mode="r", *args, **kwargs):
        return _real_open(self.table[name], self.modes[name])

    def popen(self, args, stdout=None):
        kind, payload = self.ioreg
        if kind == "print":
            return subprocess.Popen(["printf", "%s", payload], stdout=stdout)
        if kind == "print_text":
            return subprocess.Popen(
                ["printf", "%s", payload], stdout=stdout, text=True
            )
        if kind == "absent":
            return subprocess.Popen([os.path.join(self.root, "no-ioreg")], stdout=stdout)
        if kind == "folder":
            path = os.path.join(self.root, "ioreg-dir")
            os.makedirs(path, exist_ok=True)
            return subprocess.Popen([path], stdout=stdout)
        if kind == "plainfile":
            path = os.path.join(self.root, "ioreg-plain")
            with _real_open(path, "wb") as f:
                f.write(b"not a program")
            os.chmod(path, 0o644)
            return subprocess.Popen([path], stdout=stdout)
        raise AssertionError(kind)

    def winreg_module(self):
        reg = self.registry
        root = self.root
        mod = types.ModuleType("winreg")
        mod.HKEY_LOCAL_MACHINE = "HKLM"
        mod.KEY_READ = 1
        mod.KEY_WOW64_64KEY = 2
        mod.REG_SZ = 1

        def OpenKey(hive, sub, reserved, access):
            if reg["key"] == "absent":
                _real_open(os.path.join(root, "registry", sub.replace("\\", "_")))
            return contextlib.nullcontext(reg["values"])

        def QueryValueEx(values, name):
            return values[name]

        mod.OpenKey = OpenKey
        mod.QueryValueEx = QueryValueEx
        return mod

    @contextlib.contextmanager
    def active(self):
        fake_subprocess = types.SimpleNamespace(PIPE=subprocess.PIPE, Popen=self.popen)
        platform = "win32" if self.registry is not None else "linux"
        fake_sys = types.SimpleNamespace(platform=platform, modules=sys.modules)
        patches = [
            mock.patch.object(wdebug, "_machine_id", None),
            mock.patch.object(wdebug, "open", self.open, create=True),
            mock.patch.object(wdebug, "subprocess", fake_subprocess),
            mock.patch.object(wdebug, "sys", fake_sys),
            mock.patch.dict(os.environ, {}, clear=False),
        ]
        if self.registry is not None:
            patches.append(mock.patch.dict(sys.modules, {"winreg": self.winreg_module()}))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            os.environ.pop("WERKZEUG_DEBUG_PIN", None)
            yield


def probe(host):
    """Return ("ok", pin) or ("crash", None) for one simulated host."""
    with host.active():
        try:
            pin, cookie = wdebug.get_pin_and_cookie_name(demo_app)
        except Exception:
            return "crash", None
    assert cookie.startswith("__wzd")
    return "ok", pin


FILE_KINDS = ["data", "blank", "absent", "folder", "nested", "sink"]


def random_spec(rng, kinds):
    kind = rng.choice(kinds)
    if kind == "data":
        return kind, bytes(rng.choice(b"0123456789abcdef") for _ in range(rng.randint(4, 12)))
    if kind == "blank":
        return kind, rng.random() < 0.5
    if kind == "text":
        return kind, "".join(rng.choice("abcdef") for _ in range(8))
    return kind, None


class MachineIdProbeTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wzd-host-")
        self.counter = 0

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def host(self, files, **kw):
        self.counter += 1
        d = os.path.join(self.root, f"h{self.counter}")
        os.makedirs(d)
        return SimulatedHost(d, files, **kw)

    def run_hosts(self, hosts):
        return [probe(h) for h in hosts]

    def test_plain_linux_host(self):
        h = self.host(
            {
                MACHINE_ID: ("data", b"0f3a9c1e77d24b10"),
                BOOT_ID: ("data", b"never-read"),
                CGROUP: ("data", b"0::/user.slice"),
            }
        )
        status, pin = probe(h)
        self.assertEqual(status, "ok")
        self.assertEqual(len(pin.replace("-", "")), 9)

    def test_boot_id_fallback_sweep(self):
        rng = random.Random(101)
        hosts = []
        for _ in range(9):
            hosts.append(
                self.host(
                    {
                        MACHINE_ID: random_spec(rng, ["blank", "absent", "folder", "nested"]),
                        BOOT_ID: random_spec(rng, ["data", "blank", "absent"]),
                        CGROUP: random_spec(rng, ["data", "absent", "blank"]),
                        },
                    ioreg=("print", "nothing useful"),
                )
            )
        results = self.run_hosts(hosts)
        self.assertTrue(all(s == "ok" for s, _ in results))

    def test_write_only_handles(self):
        rng = random.Random(202)
        hosts = []
        for i in range(7):
            files = {
                MACHINE_ID: ("sink", None),
                BOOT_ID: ("sink", None) if i % 2 else random_spec(rng, ["data", "absent"]),
                CGROUP: random_spec(rng, ["sink", "data", "folder"]),
            }
            hosts.append(self.host(files, ioreg=("print", '"serial-number" = <C02X%d>' % i)))
        results = self.run_hosts(hosts)
        self.assertTrue(all(s == "ok" for s, _ in results))

    def test_ioreg_serial_numbers(self):
        rng = random.Random(303)
        hosts = []
        for i in range(8):
            serial = "".join(rng.choice("ABCDEFGH0123456789") for _ in range(10))
            body = '"serial-number" = <%s>' % serial if rng.random() < 0.6 else "IOPlatform"
            hosts.append(
                self.host(
                    {
                        MACHINE_ID: ("absent", None),
                        BOOT_ID: ("blank", i % 2 == 0),
                        CGROUP: random_spec(rng, ["absent", "blank", "folder"]),
                    },
                    ioreg=("print", body),
                )
            )
        results = self.run_hosts(hosts)
        self.assertTrue(all(s == "ok" for s, _ in results))
        self.assertGreaterEqual(len({p for _, p in results}), 2)

    def test_ioreg_cannot_spawn(self):
        hosts = []
        kinds = ["absent", "folder", "plainfile"]
        for i in range(9):
            hosts.append(
                self.host(
                    {
                        MACHINE_ID: (FILE_KINDS[1 + i % 5], i % 2 == 1),
                        BOOT_ID: ("absent", None),
                        CGROUP: ("absent", None) if i < 5 else ("blank", True),
                    },
                    ioreg=(kinds[(i * i) % 3], None),
                )
            )
        results = self.run_hosts(hosts)
        self.assertTrue(all(s == "ok" for s, _ in results))

    def test_text_mode_identifiers(self):
        rng = random.Random(404)
        hosts = []
        for i in range(6):
            hosts.append(
                self.host(
                    {
                        MACHINE_ID: ("text", "id%04d" % rng.randint(0, 9999)) if i < 3 else ("absent", None),
                        BOOT_ID: ("text", "boot") if i >= 3 else ("data", b"x"),
                        CGROUP: ("data", b"0::/"),
                    }
                )
            )
        results = self.run_hosts(hosts)
        self.assertEqual(sum(s == "crash" for s, _ in results), 6)

    def test_text_mode_cgroup(self):
        rng = random.Random(505)
        hosts = []
        for i in range(10):
            mid = random_spec(rng, ["data", "absent", "blank", "folder"])
            hosts.append(
                self.host(
                    {
                        MACHINE_ID: mid,
                        BOOT_ID: random_spec(rng, ["absent", "blank", "nested"]),
                        CGROUP: ("text", "0::/init.scope") if i % 3 != 2 else ("folder", None),
                    },
                    ioreg=("print", "none"),
                )
            )
        results = self.run_hosts(hosts)
        crashed = sum(s == "crash" for s, _ in results)
        self.assertGreater(crashed, 0)
        self.assertLess(crashed, 10)

    def test_ioreg_text_output(self):
        hosts = []
        for i in range(5):
            hosts.append(
                self.host(
                    {
                        MACHINE_ID: ("nested", None) if i % 2 else ("folder", None),
                        BOOT_ID: ("blank", bool(i % 3)),
                        CGROUP: ("absent", None),
                    },
                    ioreg=("print_text", "serial %d" % i) if i != 4 else ("folder", None),
                )
            )
        results = self.run_hosts(hosts)
        self.assertEqual([s for s, _ in results].count("ok"), 1)

    def test_unknown_paths(self):
        hosts = [
            self.host({}),
            self.host({MACHINE_ID: ("absent", None)}),
            self.host({MACHINE_ID: ("blank", True), BOOT_ID: ("folder", None)}),
            self.host({MACHINE_ID: ("data", b"abc"), BOOT_ID: ("absent", None)}),
            self.host({BOOT_ID: ("data", b"b00t"), CGROUP: ("data", b"0::/")}),
        ]
        results = self.run_hosts(hosts)
        self.assertEqual(sum(s == "crash" for s, _ in results), len(hosts))

    def test_windows_registry_guid(self):
        rng = random.Random(606)
        hosts = []
        for i in range(8):
            guid = "%08x-%04x" % (rng.getrandbits(32), rng.getrandbits(16))
            gtype = 1 if i % 3 else 3
            value = guid if gtype == 1 else guid.encode()
            hosts.append(
                self.host(
                    {
                        MACHINE_ID: random_spec(rng, ["absent", "blank", "folder"]),
                        BOOT_ID: random_spec(rng, ["absent", "sink", "nested"]),
                        CGROUP: random_spec(rng, ["absent", "sink"]),
                    },
                    ioreg=("absent", None),
                    registry={"key": "present", "values": {"MachineGuid": (value, gtype)}},
                )
            )
        results = self.run_hosts(hosts)
        self.assertTrue(all(s == "ok" for s, _ in results))

    def test_windows_registry_failures(self):
        hosts = []
        for i in range(7):
            registry = (
                {"key": "absent", "values": {}}
                if i % 2 == 0
                else {"key": "present", "values": {"ProductId": ("x", 1)}}
            )
            hosts.append(
                self.host(
                    {
                        MACHINE_ID: ("blank", i % 3 == 0),
                        BOOT_ID: (["absent", "folder", "nested", "sink"][i % 4], None),
                        CGROUP: ("folder", None) if i % 2 else ("blank", False),
                    },
                    ioreg=("print", "no serial") if i < 4 else ("plainfile", None),
                    registry=registry,
                )
            )
        results = self.run_hosts(hosts)
        statuses = [s for s, _ in results]
        self.assertEqual(statuses.count("crash"), 3)

    def test_mixed_fleet(self):
        rng = random.Random(707)
        hosts = []
        for i in range(16):
            files = {}
            for path in (MACHINE_ID, BOOT_ID, CGROUP):
                if rng.random() < 0.92:
                    files[path] = random_spec(rng, FILE_KINDS)
            ioreg = rng.choice(
                [("print", "nope"), ("absent", None), ("folder", None), ("print", '"serial-number" = <Z9>')]
            )
            registry = None
            if rng.random() < 0.4:
                registry = {"key": rng.choice(["absent", "present"]), "values": {"MachineGuid": ("g%d" % i, 1)}}
            hosts.append(self.host(files, ioreg=ioreg, registry=registry))
        results = self.run_hosts(hosts)
        self.assertEqual(len(results), 16)
        self.assertTrue(any(s == "ok" for s, _ in results))
