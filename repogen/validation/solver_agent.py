"""Solver-agent validator.

Runs a code agent (default: claude-code) on every kept instance in the exact
evaluation setting RepoBehave uses: a fresh container, question.json with the
oracle answer stripped, the instance test files (no parser, no eval.sh, no
oracle), and one isolated agent session that must write answer.json. The
answer is then scored against the oracle with the benchmark's own comparison
rules; instances the agent cannot solve are failed (and discarded by the
runner).

Settings (via CLI):
  agent      backend name (default "claude-code"; any registered backend works)
  model      model name for the backend (required)
  timeout_s  per-instance session timeout (default 900)
  float_tol  scoring tolerance (default 1e-6)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

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

_PROMPT_TEMPLATE = """You are running a repository QA evaluation instance with full environment access.

Question file: {qfile}
Instance directory: {instance_dir}
Output file to write: {answer_out}

You have complete access to this environment: you can read/write files, run tests, and run any code/commands needed.

Required workflow:
1. Open and read "{qfile}".
2. Use BOTH the "question" field and "template_answer" field.
3. The final output must follow template_answer exactly (same top-level keys, required structure, and value types).
4. Use the instance test cases under "{instance_dir}/files" and referenced files to derive the answer.
5. Run tests and, if needed, add temporary logging/instrumentation to compute the correct answer.
6. Write ONLY the final JSON answer object to "{answer_out}".
7. Do not write markdown fences. Do not ask for confirmation.
8. Ensure "{answer_out}" is valid JSON before finishing.
"""


@register
class SolverAgentValidator(Validator):
    name = "solver_agent"

    @property
    def agent_name(self) -> str:
        return self.settings.get("agent") or "claude-code"

    @property
    def model(self) -> str:
        return self.settings.get("model") or ""

    def scope_key(self) -> str:
        # Namespace outputs by agent AND model so different solvers coexist
        # (mirrors RepoBehave's evaluations/<tool>/<model>/ layout).
        return f"{safe_name(self.agent_name)}/{safe_name(self.model or 'unset')}"

    def describe(self) -> dict:
        return {"agent": self.agent_name, "model": self.model}

    def validate(self, ctx: ValidationContext) -> list[ValidationVerdict]:
        agent_name = self.agent_name
        model = self.model
        if not model:
            raise ValueError("solver_agent validator requires a model (--solver-model)")
        timeout_s = int(self.settings.get("timeout_s") or 900)
        float_tol = float(self.settings.get("float_tol") or 1e-6)

        instance_dirs = ctx.instance_dirs()
        if not instance_dirs:
            return []

        backend = create_backend(agent_name, model)
        out_root = ctx.run_dir / "validation" / self.name / self.scope_key()
        eval_root = f"{ctx.workdir}/qa_instances_eval/{ctx.repo_key}"
        answers_root = f"{ctx.workdir}/validation_answers"

        verdicts: list[ValidationVerdict] = []
        container = Container(ctx.image, workdir=ctx.workdir)
        try:
            print(f"[solver_agent] starting fresh container from {ctx.image}")
            container.start()
            print(f"[solver_agent] preparing backend '{agent_name}' ({model})")
            backend.prepare(container)

            for index, instance_dir in enumerate(instance_dirs, start=1):
                instance_id = instance_dir.name
                print(f"[solver_agent][{index}/{len(instance_dirs)}] {instance_id}")
                verdict = self._validate_one(
                    ctx, container, backend, instance_dir,
                    eval_root, answers_root, out_root, timeout_s, float_tol,
                )
                status = "PASS" if verdict.passed else f"FAIL ({verdict.reason})"
                print(f"    -> {status}")
                verdicts.append(verdict)
        finally:
            container.stop()
        return verdicts

    # -- per instance ----------------------------------------------------

    def _validate_one(
        self,
        ctx: ValidationContext,
        container: Container,
        backend,
        instance_dir: Path,
        eval_root: str,
        answers_root: str,
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

        # 1. Stage the leak-free eval bundle (question.json = oracle minus
        #    oracle_answer; files/ minus parsers).
        with tempfile.TemporaryDirectory(prefix="repogen_eval_") as tmp:
            bundle = write_eval_bundle(instance_dir, oracle, Path(tmp) / instance_id)
            container.exec(f"rm -rf '{eval_root}/{instance_id}'")
            container.cp_to(bundle, f"{eval_root}/{instance_id}")

        container_instance_dir = f"{eval_root}/{instance_id}"
        answer_out = f"{answers_root}/{instance_id}/answer.json"
        container.exec(f"mkdir -p '{answers_root}/{instance_id}'")

        # 2. One isolated solver session.
        prompt = _PROMPT_TEMPLATE.format(
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

        # 3. Collect and score the answer.
        host_answer = host_out / "answer.json"
        container.cp_from(answer_out, host_answer)
        details = {"agent_exit_code": agent_result.exit_code}
        if agent_result.note:
            details["agent_note"] = agent_result.note

        if not host_answer.is_file() or host_answer.stat().st_size == 0:
            return ValidationVerdict(
                instance_id, False, "solver produced no answer.json", details
            )
        try:
            predicted = json.loads(host_answer.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return ValidationVerdict(
                instance_id, False, f"answer.json invalid JSON: {e}", details
            )

        correct, reason = score_answer(
            oracle["oracle_answer"], predicted, float_tol=float_tol
        )
        details["score_reason"] = reason
        if correct:
            return ValidationVerdict(instance_id, True, "solver matched oracle", details)
        return ValidationVerdict(
            instance_id, False, f"solver answer mismatch: {reason}", details
        )
