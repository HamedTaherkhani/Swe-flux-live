"""Create a perturbed instance directory from an original one.

A perturbed instance keeps the original test file name, class, and method names
(so the question text and the parser still apply); only the directory name, the
input values, and the harvested oracle differ. eval.sh embeds the instance id in
several paths, so it is rewritten for the new id.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Materialized:
    instance_dir: Path
    test_path: Path


class InstanceMaterializer:
    def __init__(self, source_instances: Path, dest_instances: Path) -> None:
        self.source_instances = Path(source_instances)
        self.dest_instances = Path(dest_instances)

    def materialize(
        self, original_id: str, new_id: str, new_test_source: str
    ) -> Optional[Materialized]:
        src = self.source_instances / original_id
        dest = self.dest_instances / new_id
        if not src.is_dir():
            return None
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))

        # The oracle must be re-harvested; carrying the original over would let a
        # failed harvest silently score against stale ground truth.
        for stale in ("oracle.json", "trace.log", "pytest.log", "oracle.log",
                      "difficulty.json", "perturbation.json"):
            (dest / stale).unlink(missing_ok=True)

        test_path = dest / "files" / "testcase.py"
        test_path.write_text(new_test_source, encoding="utf-8")

        self._rewrite_eval_sh(dest / "eval.sh", original_id, new_id)
        return Materialized(dest, test_path)

    @staticmethod
    def _rewrite_eval_sh(path: Path, original_id: str, new_id: str) -> None:
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(original_id, new_id), encoding="utf-8")

    def remove(self, new_id: str) -> None:
        shutil.rmtree(self.dest_instances / new_id, ignore_errors=True)

    @staticmethod
    def write_metadata(instance_dir: Path, payload: dict) -> None:
        (instance_dir / "perturbation.json").write_text(
            json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
        )
