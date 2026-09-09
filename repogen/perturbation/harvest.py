"""Oracle harvesting for perturbed instances.

Re-uses the run's own `run_qa_fromhost.sh`, which starts the repo image, stages
the qa tree, runs one instance and parses its trace into oracle.json. Harvesting
is never re-implemented here -- this only invokes it and copies the artifacts
next to the instance so screening and the rest of the toolchain find them.

This step is also the validator: a perturbation that breaks execution produces
no oracle, and the caller drops it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ARTIFACTS = ("oracle.json", "trace.log", "pytest.log", "oracle.log")


@dataclass
class HarvestResult:
    ok: bool
    detail: str
    returncode: int = 0
    oracle_path: Optional[Path] = None
    trace_path: Optional[Path] = None


class OracleHarvester:
    """Runs `run_qa_fromhost.sh <instance_id>` in an instances/ tree."""

    def __init__(self, instances_dir: Path, image: str = "", timeout: int = 900) -> None:
        self.instances_dir = Path(instances_dir)
        self.image = image
        self.timeout = timeout

    @property
    def script(self) -> Path:
        return self.instances_dir / "run_qa_fromhost.sh"

    def harvest(self, instance_id: str, container_name: Optional[str] = None) -> HarvestResult:
        if not self.script.is_file():
            return HarvestResult(False, f"missing run_qa_fromhost.sh in {self.instances_dir}")

        env = os.environ.copy()
        if self.image:
            env["IMAGE"] = self.image
        # A unique container name lets several harvests run concurrently; the
        # script otherwise reuses one fixed name and the second run would kill
        # the first one's container out from under it.
        if container_name:
            env["CONTAINER_NAME"] = container_name

        try:
            proc = subprocess.run(
                ["bash", self.script.name, instance_id],
                cwd=str(self.instances_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return HarvestResult(False, f"harvest timed out after {self.timeout}s")

        out_dir = self.instances_dir / "qa_artifacts" / instance_id
        harvested = out_dir / "oracle.json"
        if proc.returncode != 0 or not harvested.is_file():
            tail = (proc.stderr or proc.stdout or "")[-600:].strip().replace("\n", " ")
            return HarvestResult(False, f"harvest failed: {tail}", proc.returncode)

        instance_dir = self.instances_dir / instance_id
        oracle_dest = instance_dir / "oracle.json"
        trace_dest: Optional[Path] = None
        for name in ARTIFACTS:
            src = out_dir / name
            if src.is_file():
                dest = instance_dir / name
                shutil.copy2(src, dest)
                if name == "trace.log":
                    trace_dest = dest

        if not self._oracle_is_sane(oracle_dest):
            return HarvestResult(False, "harvested oracle.json is empty or malformed")

        return HarvestResult(True, "ok", 0, oracle_dest, trace_dest)

    @staticmethod
    def _oracle_is_sane(path: Path) -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return isinstance(data, dict) and "oracle_answer" in data

    def cleanup_artifacts(self, instance_id: str) -> None:
        shutil.rmtree(self.instances_dir / "qa_artifacts" / instance_id, ignore_errors=True)
