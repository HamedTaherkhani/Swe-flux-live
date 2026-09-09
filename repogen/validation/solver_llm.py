"""Solver-LLM validator (raw LLM inference, no agent).

Ports RepoBehave's read-only LLM + RepoMap evaluation into the validation
stage. Instead of driving a coding agent inside the container, it:

1. Snapshots the repository from the benchmark image to a host directory once
   (cached under the run dir, so multiple models reuse it).
2. For each kept instance, stages a leak-free bundle (question.json without the
   oracle answer, plus test files without parsers).
3. Runs the model with read-only repo tools (get_repo_map / list_dir /
   read_file) via `run_single_instance` — the model reasons about runtime
   behavior statically; it does NOT execute code.
4. Scores the answer against the oracle with the benchmark's comparison rules,
   and records token usage + cost (provider_model_costs.json).

Outputs are namespaced by <provider>/<model>, exactly like the solver_agent
validator's <agent>/<model>, so several models accumulate side by side.

Settings (via CLI):
  provider     openai | anthropic | gemini | fireworks | deepseek | openrouter | vllm | kimi
  model        provider model id (required)
  repo_map_mode  repomap (needs aider-chat) | cheap_repomap | none
  container_runtime  docker | apptainer  (for the one-time repo snapshot)
  max_read_lines, cheap_repomap_max_files, temperature, reasoning_effort,
  max_repair_rounds
  float_tol    scoring tolerance
  parallel     concurrent instances (default 1). Pure API work over a shared
               read-only snapshot, so the practical ceiling is the provider's
               rate limit, not local resources.
"""

from __future__ import annotations

import json
import queue
import tempfile
import threading
from pathlib import Path

from ..scoring import score_answer
from . import register
from .base import (
    ValidationContext,
    ValidationVerdict,
    Validator,
    safe_name,
    write_eval_bundle,
)


@register
class SolverLLMValidator(Validator):
    name = "solver_llm"
    # LLM inference is for EVALUATION only — it never discards instances and its
    # outputs live under evaluation/ (unlike the agent validator).
    evaluation_only = True

    @property
    def provider(self) -> str:
        return self.settings.get("provider") or "openai"

    @property
    def model(self) -> str:
        return self.settings.get("model") or ""

    def scope_key(self) -> str:
        return f"{safe_name(self.provider)}/{safe_name(self.model or 'unset')}"

    def describe(self) -> dict:
        return {"kind": "llm", "provider": self.provider, "model": self.model}

    # -- main ------------------------------------------------------------

    def validate(self, ctx: ValidationContext) -> list[ValidationVerdict]:
        if not self.model:
            raise ValueError("solver_llm validator requires a model (--llm-model)")

        # Imported lazily so the rest of repogen works without the LLM/optional deps.
        from ..llm_eval import build_container_runtime, run_single_instance

        provider = self.provider
        model = self.model
        repo_map_mode = self.settings.get("repo_map_mode") or "repomap"
        runtime_name = self.settings.get("container_runtime") or "docker"
        max_read_lines = int(self.settings.get("max_read_lines") or 250)
        cheap_repomap_max_files = int(self.settings.get("cheap_repomap_max_files") or 2000)
        temperature = float(self.settings.get("temperature") or 0.0)
        reasoning_effort = str(self.settings.get("reasoning_effort") or "")
        max_repair_rounds = int(self.settings.get("max_repair_rounds") or 2)
        float_tol = float(self.settings.get("float_tol") or 1e-6)

        instance_dirs = ctx.instance_dirs()

        wanted = self.settings.get("instance_ids") or []
        if wanted:
            wanted_set = set(wanted)
            missing = wanted_set - {d.name for d in instance_dirs}
            if missing:
                raise ValueError(f"unknown/absent instance ids: {sorted(missing)}")
            instance_dirs = [d for d in instance_dirs if d.name in wanted_set]

        # By default, evaluate only instances at least one approved Haiku/Fable
        # rollout got right. Turn off explicitly with only_agent_validated=False.
        if self.settings.get("only_agent_validated", True):
            from . import agent_validated_instances

            allowed = agent_validated_instances(ctx.run_dir)
            if allowed is None:
                print("[solver_llm] no Haiku/Fable validation runs found; "
                      "evaluating NO instances (use --all-instances to override)")
                instance_dirs = []
            else:
                before = len(instance_dirs)
                instance_dirs = [d for d in instance_dirs if d.name in allowed]
                print(f"[solver_llm] restricting to validated instances: "
                      f"{len(instance_dirs)}/{before} "
                      "(>=1 Haiku/Fable rollout passed)")

        if not instance_dirs:
            return []

        repo_root = self._ensure_repo_snapshot(ctx, runtime_name)
        # Evaluation outputs (never validation): evaluation/llm/<provider>/<model>/,
        # mirroring RepoBehave's evaluations/llm/<vendor>/<model>/ layout.
        out_root = ctx.run_dir / "evaluation" / "llm" / self.scope_key()
        out_root.mkdir(parents=True, exist_ok=True)

        total = len(instance_dirs)
        parallel = max(1, int(self.settings.get("parallel") or 1))
        workers = min(parallel, total)

        # Shared work queue. Every instance is independent: its own eval bundle,
        # its own output dir, its own ProviderRunner — the only shared state is
        # the read-only repo snapshot, which is materialized above.
        work: queue.Queue = queue.Queue()
        for item in enumerate(instance_dirs, start=1):
            work.put(item)
        results: dict[int, tuple] = {}
        errors: list[str] = []
        lock = threading.Lock()

        def run_worker(worker_id: int) -> None:
            tag = "[solver_llm]" if workers == 1 else f"[solver_llm][w{worker_id}]"
            while True:
                try:
                    index, instance_dir = work.get_nowait()
                except queue.Empty:
                    return
                instance_id = instance_dir.name
                print(f"{tag}[{index}/{total}] {instance_id} ({provider}/{model})")
                try:
                    verdict, inst_cost = self._validate_one(
                        ctx=ctx,
                        instance_dir=instance_dir,
                        repo_root=repo_root,
                        out_root=out_root,
                        run_single_instance=run_single_instance,
                        provider=provider,
                        model=model,
                        repo_map_mode=repo_map_mode,
                        max_read_lines=max_read_lines,
                        cheap_repomap_max_files=cheap_repomap_max_files,
                        temperature=temperature,
                        reasoning_effort=reasoning_effort,
                        max_repair_rounds=max_repair_rounds,
                        float_tol=float_tol,
                    )
                except Exception as exc:  # noqa: BLE001 — reported after join
                    with lock:
                        errors.append(f"{instance_id}: {type(exc).__name__}: {exc}")
                    print(f"{tag} {instance_id} -> ERROR {type(exc).__name__}: {exc}")
                    continue
                status = "PASS" if verdict.passed else f"FAIL ({verdict.reason})"
                cost_str = f"${inst_cost:.4f}" if inst_cost is not None else "cost n/a"
                print(f"{tag} {instance_id} -> {status}  [{cost_str}]")
                with lock:
                    results[index] = (verdict, inst_cost)

        if workers == 1:
            run_worker(1)
        else:
            print(f"[solver_llm] evaluating {total} instance(s) with {workers} workers")
            threads = [
                threading.Thread(target=run_worker, args=(i,), daemon=True)
                for i in range(1, workers + 1)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        if len(results) != total:
            # Evaluation never discards, so a missing instance is a reporting
            # gap, not a data-loss risk: report loudly and score what we have.
            print(f"[solver_llm] WARNING: {total - len(results)} instance(s) produced "
                  f"no verdict: {'; '.join(errors) or 'no error recorded'}")

        verdicts = [results[i][0] for i in sorted(results)]
        costs = [results[i][1] for i in sorted(results)]
        cost_known = all(c is not None for c in costs)
        total_cost = sum(c for c in costs if c is not None)

        summary = {
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "repo_map_mode": repo_map_mode,
            "instances": len(verdicts),
            "passed": sum(1 for v in verdicts if v.passed),
            "total_cost_usd": total_cost if cost_known else None,
            "parallel": workers,
            "errors": errors,
        }
        (out_root / "run_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        cost_label = f"${total_cost:.4f}" if cost_known else "unknown (model not in pricing file)"
        print(f"[solver_llm] total cost for {provider}/{model}: {cost_label}")
        return verdicts

    # -- per instance ----------------------------------------------------

    def _validate_one(
        self, *, ctx, instance_dir, repo_root, out_root, run_single_instance,
        provider, model, repo_map_mode, max_read_lines, cheap_repomap_max_files,
        temperature, reasoning_effort, max_repair_rounds, float_tol,
    ):
        instance_id = instance_dir.name
        oracle = ctx.load_oracle(instance_dir)
        if oracle is None or "oracle_answer" not in oracle:
            return ValidationVerdict(instance_id, False, "unreadable oracle.json"), None

        host_out = out_root / instance_id
        host_out.mkdir(parents=True, exist_ok=True)
        answer_path = host_out / "answer.json"
        debug_path = host_out / "debug.json"
        trace_path = host_out / "trace.log"

        # A process interruption can happen after most expensive API calls have
        # completed but before evaluation_report.json is assembled. Reuse only
        # complete per-instance artifacts so a resumed run does not repeat
        # those calls; incomplete directories fall through to fresh inference.
        if answer_path.is_file() and debug_path.is_file() and trace_path.is_file():
            try:
                parsed = json.loads(answer_path.read_text(encoding="utf-8"))
                debug = json.loads(debug_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass
            else:
                cost_obj = debug.get("cost") if isinstance(debug, dict) else None
                inst_cost = cost_obj.get("cost_usd") if isinstance(cost_obj, dict) else None
                correct, reason = score_answer(
                    oracle["oracle_answer"], parsed, float_tol=float_tol
                )
                details = {
                    "provider": provider,
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                    "usage": debug.get("usage") if isinstance(debug, dict) else None,
                    "cost": cost_obj,
                    "repair_attempts": (
                        debug.get("repair_attempts") if isinstance(debug, dict) else None
                    ),
                    "score_reason": reason,
                    "reused_artifact": True,
                }
                if correct:
                    return ValidationVerdict(
                        instance_id, True, "llm matched oracle", details
                    ), inst_cost
                return ValidationVerdict(
                    instance_id, False, f"llm answer mismatch: {reason}", details
                ), inst_cost

        trace_lines: list[str] = []

        with tempfile.TemporaryDirectory(prefix="repogen_llm_") as tmp:
            bundle = write_eval_bundle(instance_dir, oracle, Path(tmp) / instance_id)
            question_path = bundle / "question.json"
            try:
                parsed, debug = run_single_instance(
                    provider=provider,
                    model=model,
                    question_path=question_path,
                    repo_root=repo_root,
                    max_read_lines=max_read_lines,
                    repo_map_mode=repo_map_mode,
                    cheap_repomap_max_files=cheap_repomap_max_files,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    max_repair_rounds=max_repair_rounds,
                    trace=trace_lines.append,
                )
            except Exception as exc:  # API error / no valid JSON after repairs
                trace_path.write_text("\n".join(trace_lines), encoding="utf-8")
                return ValidationVerdict(
                    instance_id, False, f"llm inference failed: {type(exc).__name__}: {exc}",
                    {"provider": provider, "model": model},
                ), None

        # Persist artifacts.
        answer_path.write_text(
            json.dumps(parsed, indent=2) + "\n", encoding="utf-8"
        )
        debug_path.write_text(
            json.dumps(debug, indent=2, default=str) + "\n", encoding="utf-8"
        )
        trace_path.write_text("\n".join(trace_lines), encoding="utf-8")

        cost_obj = debug.get("cost") if isinstance(debug, dict) else None
        inst_cost = None
        if isinstance(cost_obj, dict):
            inst_cost = cost_obj.get("cost_usd")

        correct, reason = score_answer(oracle["oracle_answer"], parsed, float_tol=float_tol)
        details = {
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "usage": debug.get("usage") if isinstance(debug, dict) else None,
            "cost": cost_obj,
            "repair_attempts": debug.get("repair_attempts") if isinstance(debug, dict) else None,
            "score_reason": reason,
        }
        if correct:
            return ValidationVerdict(instance_id, True, "llm matched oracle", details), inst_cost
        return ValidationVerdict(
            instance_id, False, f"llm answer mismatch: {reason}", details
        ), inst_cost

    # -- repo snapshot (once per run, shared across models) --------------

    def _ensure_repo_snapshot(self, ctx: ValidationContext, runtime_name: str) -> Path:
        from ..llm_eval import build_container_runtime

        snapshot_root = ctx.run_dir / ".llm_repo_snapshot"
        dest = snapshot_root / safe_name(ctx.repo_key)
        if dest.is_dir() and any(dest.iterdir()):
            print(f"[solver_llm] reusing repo snapshot: {dest}")
            return dest

        runtime = build_container_runtime(runtime_name)
        if not runtime.is_available():
            raise RuntimeError(
                f"container runtime '{runtime_name}' is not available for repo snapshot"
            )
        print(f"[solver_llm] snapshotting /testbed from {ctx.image} -> {dest}")
        runtime.ensure_image_available(ctx.image, repo_name=ctx.repo_key)
        dest.mkdir(parents=True, exist_ok=True)
        runtime.copy_dir_contents(
            image=ctx.image, src_dir="/testbed", dest=dest, name_hint=ctx.repo_key
        )
        if not any(dest.iterdir()):
            raise RuntimeError(f"repo snapshot produced empty directory: {dest}")
        return dest
