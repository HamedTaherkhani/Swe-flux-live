from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Sequence

CONTAINER_RUNTIME_CHOICES = ("docker", "apptainer")


def _run_checked(cmd: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        check=True,
        text=True,
        capture_output=capture,
    )


def _sanitize_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", (value or "").strip())


class ContainerRuntime(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def ensure_image_available(self, image: str, *, repo_name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_dir_entries(self, *, image: str, dir_path: str) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def copy_dir_contents(self, *, image: str, src_dir: str, dest: Path, name_hint: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def path_exists(self, *, image: str, path: str) -> bool:
        raise NotImplementedError


class DockerRuntime(ContainerRuntime):
    name = "docker"

    def is_available(self) -> bool:
        return shutil.which("docker") is not None

    def ensure_image_available(self, image: str, *, repo_name: str) -> None:
        if subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode != 0:
            print(f"[{repo_name}] Pulling image for snapshot: {image}")
            _run_checked(["docker", "pull", image])

    def list_dir_entries(self, *, image: str, dir_path: str) -> List[str]:
        proc = _run_checked(
            ["docker", "run", "--rm", image, "bash", "-lc", f"ls -1A {shlex.quote(dir_path)}"],
            capture=True,
        )
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    def copy_dir_contents(self, *, image: str, src_dir: str, dest: Path, name_hint: str) -> None:
        container_name = f"repobehave-snap-{_sanitize_name(name_hint).lower()}-{os.getpid()}"
        _run_checked(["docker", "create", "--name", container_name, image], capture=True)
        try:
            _run_checked(["docker", "cp", f"{container_name}:{src_dir}/.", str(dest)])
        finally:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def path_exists(self, *, image: str, path: str) -> bool:
        proc = subprocess.run(
            ["docker", "run", "--rm", image, "bash", "-lc", f"test -e {shlex.quote(path)}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return proc.returncode == 0


class ApptainerRuntime(ContainerRuntime):
    name = "apptainer"

    def is_available(self) -> bool:
        return shutil.which("apptainer") is not None

    def _image_ref(self, image: str) -> str:
        raw = (image or "").strip()
        if not raw:
            raise RuntimeError("Container image must be non-empty")

        if "://" in raw:
            return raw

        candidate = Path(raw).expanduser()
        if candidate.exists():
            return str(candidate.resolve())

        if candidate.suffix.lower() in {".sif", ".sqsh", ".img"}:
            raise RuntimeError(f"Apptainer image file not found: {candidate}")

        return f"docker://{raw}"

    def ensure_image_available(self, image: str, *, repo_name: str) -> None:
        # Apptainer can execute docker:// images directly and caches layers internally.
        self._image_ref(image)

    def list_dir_entries(self, *, image: str, dir_path: str) -> List[str]:
        image_ref = self._image_ref(image)
        proc = _run_checked(
            ["apptainer", "exec", image_ref, "bash", "-lc", f"ls -1A {shlex.quote(dir_path)}"],
            capture=True,
        )
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    def copy_dir_contents(self, *, image: str, src_dir: str, dest: Path, name_hint: str) -> None:
        del name_hint
        image_ref = self._image_ref(image)
        dest_resolved = dest.resolve()
        bind_spec = f"{dest_resolved}:/repobehave-dest"
        src_with_contents = f"{src_dir.rstrip('/')}/."
        cmd = (
            "mkdir -p /repobehave-dest && "
            f"cp -a {shlex.quote(src_with_contents)} /repobehave-dest/"
        )
        _run_checked(["apptainer", "exec", "--bind", bind_spec, image_ref, "bash", "-lc", cmd])

    def path_exists(self, *, image: str, path: str) -> bool:
        image_ref = self._image_ref(image)
        proc = subprocess.run(
            ["apptainer", "exec", image_ref, "bash", "-lc", f"test -e {shlex.quote(path)}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return proc.returncode == 0


def build_container_runtime(runtime_name: str) -> ContainerRuntime:
    normalized = (runtime_name or "").strip().lower()
    if normalized == "docker":
        return DockerRuntime()
    if normalized == "apptainer":
        return ApptainerRuntime()
    raise ValueError(
        f"Unsupported container runtime '{runtime_name}'. Supported: {', '.join(CONTAINER_RUNTIME_CHOICES)}"
    )
