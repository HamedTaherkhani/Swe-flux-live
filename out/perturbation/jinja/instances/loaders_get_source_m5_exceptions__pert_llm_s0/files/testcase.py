import hashlib
import os
import random
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from jinja2 import Environment
from jinja2.loaders import ChoiceLoader, PrefixLoader


def _digest(seed: int, tag: str, index: int = 0) -> str:
    return hashlib.blake2b(
        f"loaders_lgm5:{seed}:{tag}:{index}".encode(), digest_size=10
    ).hexdigest()


def _template_token(seed: int, index: int) -> str:
    return _digest(seed, "name", index)[:12]


def _loaders_module():
    return __import__("jinja2.loaders", fromlist=["x"])


class LoadersGetSourceM5ExceptionsTest(unittest.TestCase):
    """Exercise PackageLoader loading indirectly through composite loaders."""

    _temp_dirs: list[str] = []
    _saved_path: list[str] = []
    fixtures: dict[str, object] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls._saved_path = list(sys.path)
        cls.fixtures = cls._build_fixture_tree()
        sys.path.insert(0, str(cls.fixtures["root"]))
        sys.path.insert(0, str(cls.fixtures["zip_archive"]))

    @classmethod
    def tearDownClass(cls) -> None:
        sys.path[:] = cls._saved_path

    @classmethod
    def _build_fixture_tree(cls) -> dict[str, object]:
        root = Path(tempfile.mkdtemp(prefix="jinja_qa_lgm5_"))
        cls._temp_dirs.append(str(root))

        pkg_root = root / "qa_dir_pkg"
        template_root = pkg_root / "templates"
        template_root.mkdir(parents=True)
        (pkg_root / "__init__.py").write_text("", encoding="utf-8")

        rng = random.Random(2026082907)
        valid_flat: list[str] = []
        for idx in range(72):
            name = f"flat_{_template_token(21, idx)}.html"
            (template_root / name).write_text(f"flat-{idx}", encoding="utf-8")
            valid_flat.append(name)

        valid_nested: list[str] = []
        for bucket in range(20):
            nested_dir = template_root / f"bucket_{bucket}"
            nested_dir.mkdir()
            for idx in range(7):
                leaf = f"leaf_{_template_token(33, bucket * 12 + idx)}.html"
                (nested_dir / leaf).write_text(f"nest-{bucket}-{idx}", encoding="utf-8")
                valid_nested.append(f"bucket_{bucket}/{leaf}")

        bad_encoding: list[str] = []
        for idx in range(20):
            name = f"raw_{_template_token(27, idx)}.bin"
            payload = bytes(
                [0xFF, 0xFE, 0xC0 + (idx % 4), 0x80 | (idx % 3), idx, 0x81, 0xED, 0xA0]
            )
            (template_root / name).write_bytes(payload)
            bad_encoding.append(name)

        zip_path = root / "qa_zip_pkg.zip"
        zip_valid: list[str] = []
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("qa_zip_pkg/__init__.py", "")
            for idx in range(64):
                rel = f"zone_{idx % 12}/deep_{idx % 6}/zip_{_template_token(39, idx)}.html"
                archive.writestr(
                    f"qa_zip_pkg/templates/{rel}",
                    f"zip-body-{idx}",
                )
                zip_valid.append(rel)

        return {
            "root": root,
            "zip_archive": zip_path,
            "valid_flat": valid_flat,
            "valid_nested": valid_nested,
            "bad_encoding": bad_encoding,
            "zip_valid": zip_valid,
            "rng_seed": rng.randint(1, 999_999),
        }

    def setUp(self) -> None:
        loaders = _loaders_module()
        pkg_cls = getattr(loaders, "PackageLoader")
        self.dir_loader = pkg_cls("qa_dir_pkg", "templates")
        self.zip_loader = pkg_cls("qa_zip_pkg", "templates")
        self.choice_env = Environment(
            loader=ChoiceLoader([self.dir_loader, self.zip_loader])
        )
        self.prefix_env = Environment(
            loader=PrefixLoader(
                {
                    "dir": self.dir_loader,
                    "zip": self.zip_loader,
                }
            )
        )

    def _load_choice(self, template: str) -> None:
        self.choice_env.loader.load(self.choice_env, template)

    def _load_prefix(self, template: str) -> None:
        self.prefix_env.loader.load(self.prefix_env, template)

    def _expect_failure(self, action) -> None:
        with self.assertRaises(Exception):
            action()

    def test_choice_bulk_successful_directory_templates(self) -> None:
        names = list(self.fixtures["valid_flat"])  # type: ignore[index]
        names.extend(self.fixtures["valid_nested"])  # type: ignore[index]
        for name in names:
            self._load_choice(name)
        self.assertGreater(len(names), 80)

    def test_choice_bulk_missing_directory_templates(self) -> None:
        rng = random.Random(int(self.fixtures["rng_seed"]) + 1)  # type: ignore[arg-type]
        missing = [
            f"missing_{_template_token(43, idx)}.html"
            for idx in range(28)
        ]
        rng.shuffle(missing)
        failures = 0
        for name in missing:
            try:
                self._load_choice(name)
            except Exception:
                failures += 1
        self.assertEqual(failures, len(missing))

    def test_choice_parent_segment_rejections(self) -> None:
        rng = random.Random(int(self.fixtures["rng_seed"]) + 3)  # type: ignore[arg-type]
        bases = list(self.fixtures["valid_flat"])[:11]  # type: ignore[index]
        probes: list[str] = []
        for idx in range(28):
            base = bases[idx % len(bases)]
            probes.append(f"../{base}")
            probes.append(f"segment/../{base}")
            probes.append(f"wide/deep/zone/../../../{base}")
        rng.shuffle(probes)
        failures = 0
        for probe in probes:
            try:
                self._load_choice(probe)
            except Exception:
                failures += 1
        self.assertEqual(failures, len(probes))

    def test_choice_separator_segment_rejections(self) -> None:
        rng = random.Random(int(self.fixtures["rng_seed"]) + 5)  # type: ignore[arg-type]
        pieces = [
            f"badsep_{_template_token(47, idx)}.html"
            for idx in range(20)
        ]
        probes: list[str] = []
        for piece in pieces:
            probes.append(piece.replace("_", os.sep, 1))
            probes.append(f"bucket_5{os.sep}..{os.sep}outside.html")
        rng.shuffle(probes)
        failures = 0
        for probe in probes:
            try:
                self._load_choice(probe)
            except Exception:
                failures += 1
        self.assertEqual(failures, len(probes))

    def test_prefix_successful_directory_templates(self) -> None:
        names = list(self.fixtures["valid_nested"])  # type: ignore[index]
        for name in names:
            self._load_prefix(f"dir/{name}")
        self.assertGreater(len(names), 60)

    def test_prefix_missing_directory_templates(self) -> None:
        rng = random.Random(int(self.fixtures["rng_seed"]) + 7)  # type: ignore[arg-type]
        missing = [
            f"dir/absent_{_template_token(51, idx)}.html"
            for idx in range(22)
        ]
        rng.shuffle(missing)
        failures = 0
        for name in missing:
            try:
                self._load_prefix(name)
            except Exception:
                failures += 1
        self.assertEqual(failures, len(missing))

    def test_choice_zip_successful_templates(self) -> None:
        names = list(self.fixtures["zip_valid"])  # type: ignore[index]
        for name in names:
            self._load_choice(name)
        self.assertGreater(len(names), 40)

    def test_choice_zip_missing_templates(self) -> None:
        rng = random.Random(int(self.fixtures["rng_seed"]) + 11)  # type: ignore[arg-type]
        missing = [
            f"zip_missing_{_template_token(55, idx)}.html"
            for idx in range(24)
        ]
        rng.shuffle(missing)
        failures = 0
        for name in missing:
            try:
                self._load_choice(name)
            except Exception:
                failures += 1
        self.assertEqual(failures, len(missing))

    def test_prefix_zip_missing_templates(self) -> None:
        rng = random.Random(int(self.fixtures["rng_seed"]) + 13)  # type: ignore[arg-type]
        missing = [
            f"zip/ghost_{_template_token(59, idx)}.html"
            for idx in range(20)
        ]
        rng.shuffle(missing)
        failures = 0
        for name in missing:
            try:
                self._load_prefix(name)
            except Exception:
                failures += 1
        self.assertEqual(failures, len(missing))

    def test_choice_directory_decode_failures(self) -> None:
        names = list(self.fixtures["bad_encoding"])  # type: ignore[index]
        failures = 0
        for name in names:
            try:
                self._load_choice(name)
            except Exception:
                failures += 1
        self.assertEqual(failures, len(names))

    def test_prefix_directory_decode_failures(self) -> None:
        rng = random.Random(int(self.fixtures["rng_seed"]) + 17)  # type: ignore[arg-type]
        names = list(self.fixtures["bad_encoding"])  # type: ignore[index]
        rng.shuffle(names)
        failures = 0
        for name in names:
            try:
                self._load_prefix(f"dir/{name}")
            except Exception:
                failures += 1
        self.assertEqual(failures, len(names))

    def test_choice_interleaved_hits_and_misses(self) -> None:
        rng = random.Random(int(self.fixtures["rng_seed"]) + 19)  # type: ignore[arg-type]
        hits = list(self.fixtures["valid_flat"])  # type: ignore[index]
        misses = [f"void_{_template_token(63, idx)}.html" for idx in range(28)]
        schedule: list[tuple[str, bool]] = [(name, True) for name in hits[:42]]
        schedule.extend((name, False) for name in misses)
        rng.shuffle(schedule)
        matched = 0
        for name, should_work in schedule:
            try:
                self._load_choice(name)
                if should_work:
                    matched += 1
            except Exception:
                if not should_work:
                    matched += 1
        self.assertEqual(matched, len(schedule))
        self.assertGreater(len(schedule), 45)
