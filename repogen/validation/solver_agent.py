"""Solver-agent validator.

Runs a code agent (default: claude-code) on every kept instance in the exact
evaluation setting RepoBehave uses: a fresh container, question.json with the
oracle answer stripped, the instance test files (no parser, no eval.sh, no
oracle), and one isolated agent session that must write answer.json. The
answer is then scored against the oracle with the benchmark's own comparison
rules; instances the agent cannot solve are failed (and discarded by the
runner).

Settings (via CLI):
  agent         backend name (default "claude-code"; any registered backend works)
  model         model name for the backend (required)
  timeout_s     per-instance session timeout (default 900)
  float_tol     scoring tolerance (default 1e-6)
  rollouts      independent solver sessions per instance; the instance passes
                only if ALL rollouts match the oracle (default 1). Stops at the
                first failed rollout.
  instance_ids  optional list of instance ids to validate (default: all kept
                instances). Used by tiered validation to escalate only
                the instances the previous tier failed.
  parallel      number of concurrent containers (default 2). Instances are
                drained from a shared queue; all rollouts of one instance run
                in the same container.
"""

from __future__ import annotations

import json
import queue
import tempfile
import threading
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

# Signatures in an agent's logs that mean the solver never got to reason at all
# — the provider refused the request. A rollout that dies this way says nothing
# about the instance, so callers (the cascade) must not count it as a failure.
_INFRA_SIGNATURES = (
    ("out of usage credits", "provider usage limit"),
    ("usage limit reached", "provider usage limit"),
    ("credit balance is too low", "provider usage limit"),
    # Claude Code subscription limits. The session/weekly wording below is what
    # actually appears in the trajectory when a subscription quota runs out; it
    # never says "usage limit reached", so matching only that phrase let a whole
    # rate-limited tier be recorded as 0/3 solver failures (i.e. as "hard").
    ("session limit", "provider usage limit"),
    ("hit your usage limit", "provider usage limit"),
    ("weekly limit", "provider usage limit"),
    ("limit · resets", "provider usage limit"),
    ("rate_limit_error", "provider rate limit"),
    # NOT "rate_limit_event": the SDK emits that advisory even when the request
    # is throttled and then retried successfully, so it fires on healthy runs.
    # Match only signatures that accompany a TERMINAL failure.
    ('"error": "rate_limit"', "provider rate limit"),
    ('"api_error_status": 429', "provider rate limit"),
    ("too many requests", "provider rate limit"),
    ("invalid api key", "auth failure"),
    ("authentication_error", "auth failure"),
    ("please run /login", "auth failure"),
    ("oauth token has expired", "auth failure"),
)


def _detect_infra_failure(host_out: Path) -> str:
    """Classify a missing answer.json: infrastructure refusal or a real miss.

    Returns a short cause ("provider usage limit", "auth failure", ...) when the
    agent's logs carry a provider-refusal signature, else "" — the agent ran but
    produced nothing useful, which IS a solver failure.
    """
    for path in sorted(host_out.rglob("*")):
        if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            continue
        if path.suffix not in {".log", ".json", ".txt", ".jsonl"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for needle, cause in _INFRA_SIGNATURES:
            if needle in text:
                return cause
    return ""


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

    @property
    def rollouts(self) -> int:
        return max(1, int(self.settings.get("rollouts") or 1))

    def describe(self) -> dict:
        info = {"agent": self.agent_name, "model": self.model, "rollouts": self.rollouts}
        if self.settings.get("effort"):
            info["effort"] = self.settings["effort"]
        return info

    def validate(self, ctx: ValidationContext) -> list[ValidationVerdict]:
        agent_name = self.agent_name
        model = self.model
        if not model:
            raise ValueError("solver_agent validator requires a model (--solver-model)")
        timeout_s = int(self.settings.get("timeout_s") or 900)
        float_tol = float(self.settings.get("float_tol") or 1e-6)

        instance_dirs = ctx.instance_dirs()
        only = self.settings.get("instance_ids")
        if only is not None:
            wanted = set(only)
            instance_dirs = [p for p in instance_dirs if p.name in wanted]
        if not instance_dirs:
            return []

        backend_settings = {}
        if self.settings.get("effort"):
            backend_settings["effort"] = self.settings["effort"]
        backend = create_backend(agent_name, model, backend_settings)
        out_root = ctx.run_dir / "validation" / self.name / self.scope_key()
        eval_root = f"{ctx.workdir}/qa_instances_eval/{ctx.repo_key}"
        answers_root = f"{ctx.workdir}/validation_answers"

        parallel = max(1, int(self.settings.get("parallel") or 1))
        workers = min(parallel, len(instance_dirs))
        total = len(instance_dirs)
        # Optional callback, invoked with each ValidationVerdict as soon as that
        # instance finishes (from the worker thread, so it must be thread-safe).
        on_verdict = self.settings.get("on_verdict")

        # Shared work queue; each worker owns one container for its lifetime.
        # backend.run_task only reads backend state, so one backend instance is
        # safely shared; backend.prepare runs once per container.
        work: queue.Queue = queue.Queue()
        for item in enumerate(instance_dirs, start=1):
            work.put(item)
        results: dict[int, ValidationVerdict] = {}
        errors: list[str] = []

        def run_worker(worker_id: int) -> None:
            container = Container(ctx.image, workdir=ctx.workdir)
            tag = f"[solver_agent][w{worker_id}]"
            try:
                print(f"{tag} starting fresh container from {ctx.image}")
                container.start()
                print(f"{tag} preparing backend '{agent_name}' ({model})")
                backend.prepare(container)
                while True:
                    try:
                        index, instance_dir = work.get_nowait()
                    except queue.Empty:
                        return
                    instance_id = instance_dir.name
                    print(f"{tag}[{index}/{total}] {instance_id}")
                    verdict = self._validate_one(
                        ctx, container, backend, instance_dir,
                        eval_root, answers_root, out_root, timeout_s, float_tol,
                    )
                    status = "PASS" if verdict.passed else f"FAIL ({verdict.reason})"
                    print(f"{tag} {instance_id} -> {status}")
                    results[index] = verdict
                    # Let the caller persist a decision the moment it is made.
                    # Without this the cascade only labels instances after the
                    # WHOLE tier returns, so an abort mid-tier (usage limit) or
                    # a kill throws away every already-solved instance.
                    if on_verdict is not None:
                        try:
                            on_verdict(verdict)
                        except Exception as e:  # noqa: BLE001 — never kill a worker
                            print(f"{tag} on_verdict({instance_id}) failed: {e}")
            except Exception as e:  # noqa: BLE001 — reported after join
                errors.append(f"worker {worker_id}: {e}")
            finally:
                container.stop()

        if workers == 1:
            run_worker(1)
        else:
            print(f"[solver_agent] running {total} instance(s) across {workers} containers")
            threads = [
                threading.Thread(target=run_worker, args=(i,), daemon=True)
                for i in range(1, workers + 1)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        if len(results) != total:
            missing = total - len(results)
            raise RuntimeError(
                f"solver_agent: {missing} instance(s) never got a verdict "
                f"(worker errors: {errors or 'none recorded'})"
            )
        return [results[i] for i in sorted(results)]

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

        # 1. Stage the leak-free eval bundle once (question.json = oracle minus
        #    oracle_answer; files/ minus parsers). Every rollout reuses it.
        with tempfile.TemporaryDirectory(prefix="repogen_eval_") as tmp:
            bundle = write_eval_bundle(instance_dir, oracle, Path(tmp) / instance_id)
            container.exec(f"rm -rf '{eval_root}/{instance_id}'")
            container.cp_to(bundle, f"{eval_root}/{instance_id}")

        # 2. Independent solver sessions. Verdict passes only if ALL rollouts
        #    match the oracle. Two stopping strategies:
        #    - default: fail fast at the first failed rollout (later rollouts
        #      cannot change an all-must-pass verdict);
        #    - count_passes: the CALLER also distinguishes partial passes
        #      (e.g. cascade tiers with a "medium" label for 1-2 of 3), so run
        #      until the three-way classification (all/none/mixed) is fixed —
        #      one pass AND one failure seen means "mixed" regardless of the
        #      remaining rollouts.
        rollouts = self.rollouts
        count_passes = bool(self.settings.get("count_passes"))
        records: list[dict] = []
        passes = fails = 0
        for k in range(1, rollouts + 1):
            if rollouts > 1:
                print(f"    [{instance_id}] rollout {k}/{rollouts}")
            rollout_out = host_out if rollouts == 1 else host_out / f"rollout_{k}"
            passed, reason, details = self._run_rollout(
                ctx, container, backend, instance_id, k,
                eval_root, answers_root, rollout_out, oracle, timeout_s, float_tol,
            )
            records.append({"rollout": k, "passed": passed, "reason": reason, **details})
            passes += passed
            fails += (not passed)
            if not count_passes and fails:
                break
            if count_passes and passes and fails:
                break

        detail = {
            "rollouts_required": rollouts,
            "rollouts_run": len(records),
            "pass_count": passes,
            "rollouts": records,
        }
        if fails == 0:
            summary = (
                "solver matched oracle" if rollouts == 1
                else f"all {rollouts} rollouts matched oracle"
            )
            return ValidationVerdict(instance_id, True, summary, detail)
        first_fail = next(r for r in records if not r["passed"])
        summary = (
            f"{passes}/{len(records)} rollouts matched; first failure: "
            f"{first_fail['reason']}"
            if rollouts > 1 else first_fail["reason"]
        )
        return ValidationVerdict(instance_id, False, summary, detail)

    def _run_rollout(
        self,
        ctx: ValidationContext,
        container: Container,
        backend,
        instance_id: str,
        rollout_index: int,
        eval_root: str,
        answers_root: str,
        host_out: Path,
        oracle: dict,
        timeout_s: int,
        float_tol: float,
    ) -> tuple[bool, str, dict]:
        host_out.mkdir(parents=True, exist_ok=True)
        container_instance_dir = f"{eval_root}/{instance_id}"
        answer_dir = f"{answers_root}/{instance_id}/rollout_{rollout_index}"
        answer_out = f"{answer_dir}/answer.json"
        container.exec(f"rm -rf '{answer_dir}' && mkdir -p '{answer_dir}'")

        prompt = _PROMPT_TEMPLATE.format(
            qfile=f"{container_instance_dir}/question.json",
            instance_dir=container_instance_dir,
            answer_out=answer_out,
        )
        prompt_path = f"/tmp/repogen/solve_{instance_id}_r{rollout_index}.md"
        container.write_file(prompt_path, prompt)
        agent_result = backend.run_task(
            container=container,
            prompt_container_path=prompt_path,
            workspace=ctx.workdir,
            host_log_dir=host_out,
            tag=instance_id,
            timeout_s=timeout_s,
        )

        host_answer = host_out / "answer.json"
        container.cp_from(answer_out, host_answer)
        details = {"agent_exit_code": agent_result.exit_code}
        if agent_result.note:
            details["agent_note"] = agent_result.note

        if not host_answer.is_file() or host_answer.stat().st_size == 0:
            infra = _detect_infra_failure(host_out)
            if infra:
                details["infra_error"] = infra
                return False, f"solver could not run ({infra})", details
            return False, "solver produced no answer.json", details
        try:
            predicted = json.loads(host_answer.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return False, f"answer.json invalid JSON: {e}", details

        correct, reason = score_answer(
            oracle["oracle_answer"], predicted, float_tol=float_tol
        )
        details["score_reason"] = reason
        if correct:
            return True, "solver matched oracle", details
        return False, f"solver answer mismatch: {reason}", details
