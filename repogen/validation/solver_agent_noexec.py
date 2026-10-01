"""Solver-agent evaluation in STATIC mode (no code execution).

Ports RepoBehave's `--no-exec` agent evaluation (run_claude_code_eval_in_docker.sh
and run_codex_eval_in_docker.sh). The agent gets repository access but no access
to the running environment. Two independent guards enforce it:

1. No environment. The repository is snapshotted out of the benchmark image and
   mounted READ-ONLY into a minimal sandbox container (ubuntu:22.04 by default)
   that has no Python, pytest, or project dependencies. Only the output
   directory is writable. The run is refused if the sandbox image contains
   python/pytest.
2. Restricted tools. Claude Code runs with Bash, WebFetch and WebSearch removed
   from its tool set (Read/Glob/Grep to inspect, Write for the answer). Codex
   has no separate file-reading tool, so its shell stays available, but nothing
   in the sandbox can execute the project; its web search is disabled.

The prompt is the static-reasoning variant: execution is unavailable, derive the
answer by reading the code and the test cases.

This stage is evaluation-only: it never discards instances. Outputs live under
evaluation/<agent>-noexec/<model>[-<effort>]/<instance>/, mirroring RepoBehave's
evaluations/<tool>-noexec/<model>/ layout.

Settings (via CLI):
  agent          claude-code | codex
  model          model name for the backend (required)
  effort         reasoning effort; appended to the output model dir name
  timeout_s      per-instance session timeout (default 900)
  float_tol      scoring tolerance
  parallel       concurrent agent sessions in the shared sandbox (default 1)
  sandbox_image  base image for the sandbox (default ubuntu:22.04)
  container_runtime  runtime used for the one-time repo snapshot
  instance_ids, only_agent_validated   instance selection, as for solver_llm
  claude_bin, codex_bin   host binaries copied into the sandbox
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from ..agents import create_backend
from ..docker_env import Container
from ..scoring import score_answer
from . import register
from .base import (
    ValidationContext,
    ValidationVerdict,
    Validator,
    safe_name,
    write_eval_bundle,
)
from .solver_agent import _detect_infra_failure

DEFAULT_SANDBOX_IMAGE = "ubuntu:22.04"
NO_EXEC_AGENTS = ("claude-code", "codex")

_PROMPT_HEADER = """You are running a repository QA evaluation instance in STATIC mode (no code execution).

Question file: {qfile}
Instance directory: {instance_dir}
Output file to write: {answer_out}
"""

_PROMPT_WORKFLOW = """
Required workflow:
1. Read "{qfile}".
2. Use BOTH the "question" field and "template_answer" field.
3. The final output must follow template_answer exactly (same top-level keys, required structure, and value types).
4. Read the instance test cases under "{instance_dir}/files" and every referenced source file.
5. Mentally simulate the execution described by the tests to compute the correct answer.
6. Write ONLY the final JSON answer object to "{answer_out}"{write_hint}.
7. Do not write markdown fences. Do not ask for confirmation.
8. Ensure "{answer_out}" is valid JSON before finishing.
"""

_CONSTRAINTS = {
    "claude-code": """
Constraints of this environment:
- The repository is mounted READ-ONLY and there is NO Python interpreter, pytest, or project
  environment installed. You CANNOT run tests or execute any code.
- The Bash tool is not available. Use only Read, Glob and Grep to inspect files, and Write to
  produce the single output file below.
- Derive the answer by reading the code and the test cases and reasoning about the execution
  step by step. Always write a best-effort answer; an unanswered instance counts as wrong.
""",
    "codex": """
Constraints of this environment:
- The repository is mounted READ-ONLY and there is NO Python interpreter, pytest, or project
  environment installed. You CANNOT run the tests or execute any project code.
- Use the shell ONLY to read files (cat, sed -n, grep, rg, ls, find). Attempts to run python,
  pytest, or the project will fail; do not waste steps retrying them.
- The only writable location is "{out_dir}".
- Derive the answer by reading the code and the test cases and reasoning about the execution
  step by step. Do not guess placeholder values; trace the program logic carefully.
""",
}

_WRITE_HINTS = {"claude-code": "", "codex": " (e.g. with a shell heredoc)"}


def build_prompt(agent: str, qfile: str, instance_dir: str, answer_out: str) -> str:
    fields = {
        "qfile": qfile,
        "instance_dir": instance_dir,
        "answer_out": answer_out,
        "out_dir": str(Path(answer_out).parent),
        "write_hint": _WRITE_HINTS[agent],
    }
    return (_PROMPT_HEADER + _CONSTRAINTS[agent] + _PROMPT_WORKFLOW).format(**fields)


def usage_from_trajectory(agent: str, traj_path: Optional[Path]) -> dict:
    """Token usage (and cost, when the CLI reports it) from an agent trajectory."""
    if traj_path is None or not traj_path.is_file():
        return {}
    try:
        events = json.loads(traj_path.read_text(encoding="utf-8")).get("events", [])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    events = [e for e in events if isinstance(e, dict)]
    if agent == "claude-code":
        results = [e for e in events if e.get("type") == "result"]
        if not results:
            return {}
        final = results[-1]
        keys = ("usage", "total_cost_usd", "num_turns", "duration_ms", "permission_denials")
        return {k: final[k] for k in keys if k in final}
    totals: dict = {}
    turns = 0
    for event in events:
        if event.get("type") != "turn.completed" or not isinstance(event.get("usage"), dict):
            continue
        turns += 1
        for key, value in event["usage"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
    return {"usage": totals, "num_turns": turns} if turns else {}


@register
class SolverAgentNoExecValidator(Validator):
    name = "solver_agent_noexec"
    evaluation_only = True

    @property
    def agent_name(self) -> str:
        return self.settings.get("agent") or "claude-code"

    @property
    def model(self) -> str:
        return self.settings.get("model") or ""

    @property
    def effort(self) -> str:
        return (self.settings.get("effort") or "").strip()

    @property
    def tool_dir(self) -> str:
        return f"{safe_name(self.agent_name)}-noexec"

    @property
    def model_dir(self) -> str:
        # Effort is part of the directory name (as in RepoBehave), so answers
        # produced at different efforts never accumulate in one scope.
        name = safe_name(self.model or "unset")
        return f"{name}-{self.effort}" if self.effort else name

    def scope_key(self) -> str:
        return f"{self.tool_dir}/{self.model_dir}"

    def describe(self) -> dict:
        info = {
            "kind": "agent",
            "agent": self.agent_name,
            "model": self.model,
            "execution": "disabled",
            "sandbox_image": self.settings.get("sandbox_image") or DEFAULT_SANDBOX_IMAGE,
        }
        if self.effort:
            info["effort"] = self.effort
        return info

    # -- selection ---------------------------------------------------------

    def _select_instances(self, ctx: ValidationContext) -> list[Path]:
        instance_dirs = ctx.instance_dirs()
        wanted = self.settings.get("instance_ids") or []
        if wanted:
            wanted_set = set(wanted)
            missing = wanted_set - {d.name for d in instance_dirs}
            if missing:
                raise ValueError(f"unknown/absent instance ids: {sorted(missing)}")
            instance_dirs = [d for d in instance_dirs if d.name in wanted_set]
        if self.settings.get("only_agent_validated", True):
            from . import agent_validated_instances

            allowed = agent_validated_instances(ctx.run_dir)
            if allowed is None:
                print(f"[{self.name}] no Haiku/Fable validation runs found; "
                      "evaluating NO instances (use --all-instances to override)")
                return []
            before = len(instance_dirs)
            instance_dirs = [d for d in instance_dirs if d.name in allowed]
            print(f"[{self.name}] restricting to validated instances: "
                  f"{len(instance_dirs)}/{before} (>=1 Haiku/Fable rollout passed)")
        return instance_dirs

    # -- sandbox -------------------------------------------------------------

    def _build_sandbox_root(
        self, ctx: ValidationContext, instance_dirs: list[Path], container_out_rel: str
    ) -> Path:
        """A private copy of the repo snapshot plus the leak-free eval bundles.
        It is mounted read-only, so the mount point of the writable output dir
        has to exist in it before the container starts."""
        from .solver_llm import SolverLLMValidator

        runtime_name = self.settings.get("container_runtime") or "docker"
        snapshot = SolverLLMValidator()._ensure_repo_snapshot(ctx, runtime_name)
        root = Path(tempfile.mkdtemp(prefix=f"repogen-noexec-{safe_name(ctx.repo_key)}-"))
        print(f"[{self.name}] staging read-only sandbox root: {root}")
        shutil.copytree(snapshot, root, symlinks=True, dirs_exist_ok=True)
        eval_root = root / "qa_instances_eval" / ctx.repo_key
        shutil.rmtree(eval_root, ignore_errors=True)
        for instance_dir in instance_dirs:
            oracle = ctx.load_oracle(instance_dir)
            if oracle is not None:
                write_eval_bundle(instance_dir, oracle, eval_root / instance_dir.name)
        (root / container_out_rel).mkdir(parents=True, exist_ok=True)
        return root

    def _start_sandbox(
        self, ctx: ValidationContext, sandbox_root: Path, out_root: Path, container_out: str
    ) -> Container:
        image = self.settings.get("sandbox_image") or DEFAULT_SANDBOX_IMAGE
        container = Container(
            image,
            workdir=ctx.workdir,
            volumes=[
                f"{sandbox_root.resolve()}:{ctx.workdir}:ro",
                f"{out_root.resolve()}:{container_out}",
                "/etc/ssl/certs:/etc/ssl/certs:ro",
            ],
            env={
                "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt",
                "HOME": "/root",
            },
        )
        print(f"[{self.name}] starting sandbox container from {image}")
        container.start()
        # Hard guard: the sandbox image must not expose the project environment.
        has_runtime = container.exec(
            "command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 "
            "|| command -v pytest >/dev/null 2>&1"
        )
        if has_runtime.ok:
            container.stop()
            raise RuntimeError(
                f"sandbox image '{image}' contains python/pytest; refusing to run no-exec"
            )
        return container

    # -- stage -----------------------------------------------------------------

    def validate(self, ctx: ValidationContext) -> list[ValidationVerdict]:
        agent_name = self.agent_name
        if agent_name not in NO_EXEC_AGENTS:
            raise ValueError(
                f"no-exec evaluation supports {list(NO_EXEC_AGENTS)}, not '{agent_name}'"
            )
        if not self.model:
            raise ValueError(f"{self.name} requires a model (--agent-model)")
        timeout_s = int(self.settings.get("timeout_s") or 900)
        float_tol = float(self.settings.get("float_tol") or 1e-6)

        instance_dirs = self._select_instances(ctx)
        if not instance_dirs:
            return []

        backend_settings = {"no_exec": True}
        for key in ("effort", "claude_bin", "codex_bin"):
            if self.settings.get(key):
                backend_settings[key] = self.settings[key]
        backend = create_backend(agent_name, self.model, backend_settings)

        out_root = ctx.run_dir / "evaluation" / self.tool_dir / self.model_dir
        out_root.mkdir(parents=True, exist_ok=True)
        container_out_rel = f"evaluations/{self.tool_dir}/{self.model_dir}/{ctx.repo_key}"
        container_out = f"{ctx.workdir}/{container_out_rel}"
        eval_root = f"{ctx.workdir}/qa_instances_eval/{ctx.repo_key}"

        total = len(instance_dirs)
        workers = min(max(1, int(self.settings.get("parallel") or 1)), total)
        work: queue.Queue = queue.Queue()
        for item in enumerate(instance_dirs, start=1):
            work.put(item)
        results: dict[int, ValidationVerdict] = {}
        errors: list[str] = []
        lock = threading.Lock()

        sandbox_root = self._build_sandbox_root(ctx, instance_dirs, container_out_rel)
        container: Optional[Container] = None
        try:
            container = self._start_sandbox(ctx, sandbox_root, out_root, container_out)
            print(f"[{self.name}] preparing backend '{agent_name}' ({self.model})")
            backend.prepare(container)

            def run_worker(worker_id: int) -> None:
                tag = f"[{self.name}]" if workers == 1 else f"[{self.name}][w{worker_id}]"
                while True:
                    try:
                        index, instance_dir = work.get_nowait()
                    except queue.Empty:
                        return
                    instance_id = instance_dir.name
                    print(f"{tag}[{index}/{total}] {instance_id} ({agent_name}/{self.model})")
                    try:
                        verdict = self._evaluate_one(
                            ctx, container, backend, instance_dir,
                            eval_root, container_out, out_root, timeout_s, float_tol,
                        )
                    except Exception as exc:  # noqa: BLE001 — reported after join
                        with lock:
                            errors.append(f"{instance_id}: {type(exc).__name__}: {exc}")
                        print(f"{tag} {instance_id} -> ERROR {type(exc).__name__}: {exc}")
                        continue
                    status = "PASS" if verdict.passed else f"FAIL ({verdict.reason})"
                    print(f"{tag} {instance_id} -> {status}")
                    with lock:
                        results[index] = verdict

            if workers == 1:
                run_worker(1)
            else:
                print(f"[{self.name}] evaluating {total} instance(s) with {workers} "
                      "concurrent sessions")
                threads = [
                    threading.Thread(target=run_worker, args=(i,), daemon=True)
                    for i in range(1, workers + 1)
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
        finally:
            if container is not None:
                container.stop()
            shutil.rmtree(sandbox_root, ignore_errors=True)

        if len(results) != total:
            # Evaluation never discards, so a missing instance is a reporting
            # gap, not a data-loss risk: report loudly and score what we have.
            print(f"[{self.name}] WARNING: {total - len(results)} instance(s) produced "
                  f"no verdict: {'; '.join(errors) or 'no error recorded'}")

        verdicts = [results[i] for i in sorted(results)]
        summary = {
            **self.describe(),
            "instances": len(verdicts),
            "passed": sum(1 for v in verdicts if v.passed),
            "parallel": workers,
            "timeout_s": timeout_s,
            "errors": errors,
        }
        (out_root / "run_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        return verdicts

    # -- per instance ------------------------------------------------------------

    def _evaluate_one(
        self,
        ctx: ValidationContext,
        container: Container,
        backend,
        instance_dir: Path,
        eval_root: str,
        container_out: str,
        out_root: Path,
        timeout_s: int,
        float_tol: float,
    ) -> ValidationVerdict:
        instance_id = instance_dir.name
        oracle = ctx.load_oracle(instance_dir)
        if oracle is None or "oracle_answer" not in oracle:
            return ValidationVerdict(instance_id, False, "unreadable oracle.json")

        host_out = out_root / instance_id
        host_out.mkdir(parents=True, exist_ok=True)
        host_answer = host_out / "answer.json"
        host_traj = host_out / f"{instance_id}.traj.json"
        details: dict = {"agent": self.agent_name, "model": self.model}
        if self.effort:
            details["effort"] = self.effort

        # Resume: an instance that already has a non-empty answer is not re-run.
        if host_answer.is_file() and host_answer.stat().st_size > 0:
            details["reused_artifact"] = True
        else:
            container_instance_dir = f"{eval_root}/{instance_id}"
            answer_out = f"{container_out}/{instance_id}/answer.json"
            prompt = build_prompt(
                self.agent_name,
                qfile=f"{container_instance_dir}/question.json",
                instance_dir=container_instance_dir,
                answer_out=answer_out,
            )
            prompt_path = f"/tmp/repogen/solve_{instance_id}.md"
            container.write_file(prompt_path, prompt)
            agent_result = backend.run_task(
                container=container,
                prompt_container_path=prompt_path,
                workspace=ctx.workdir,
                host_log_dir=host_out,
                tag=instance_id,
                timeout_s=timeout_s,
            )
            # Files written through the bind mount are root-owned; hand them to
            # the host user.
            container.exec(
                f"chown -R {os.getuid()}:{os.getgid()} '{container_out}/{instance_id}'"
            )
            details["agent_exit_code"] = agent_result.exit_code
            if agent_result.note:
                details["agent_note"] = agent_result.note

        details.update(usage_from_trajectory(self.agent_name, host_traj))

        if not host_answer.is_file() or host_answer.stat().st_size == 0:
            infra = _detect_infra_failure(host_out)
            if infra:
                details["infra_error"] = infra
                return ValidationVerdict(
                    instance_id, False, f"agent could not run ({infra})", details
                )
            return ValidationVerdict(
                instance_id, False, "agent produced no answer.json", details
            )
        try:
            predicted = json.loads(host_answer.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return ValidationVerdict(
                instance_id, False, f"answer.json invalid JSON: {exc}", details
            )

        correct, reason = score_answer(oracle["oracle_answer"], predicted, float_tol=float_tol)
        details["score_reason"] = reason
        if correct:
            return ValidationVerdict(instance_id, True, "agent matched oracle", details)
        return ValidationVerdict(
            instance_id, False, f"agent answer mismatch: {reason}", details
        )
