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
  provider     openai | anthropic | gemini | fireworks | openrouter | vllm
  model        provider model id (required)
  repo_map_mode  repomap (needs aider-chat) | cheap_repomap | none
  container_runtime  docker | apptainer  (for the one-time repo snapshot)
  max_read_lines, cheap_repomap_max_files, temperature, max_repair_rounds
  float_tol    scoring tolerance
"""

from __future__ import annotations

import json
import tempfile
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
        max_repair_rounds = int(self.settings.get("max_repair_rounds") or 2)
        float_tol = float(self.settings.get("float_tol") or 1e-6)

        instance_dirs = ctx.instance_dirs()

        # By default, evaluate only instances at least one agent-validator got
        # right (evidence the oracle is sound). Turn off with only_agent_validated=False.
        if self.settings.get("only_agent_validated", True):
            from . import agent_validated_instances

            allowed = agent_validated_instances(ctx.run_dir)
            if allowed is None:
                print("[solver_llm] no agent-validation runs found in "
                      "validation_report.json; evaluating ALL instances")
            else:
                before = len(instance_dirs)
                instance_dirs = [d for d in instance_dirs if d.name in allowed]
                print(f"[solver_llm] restricting to agent-validated instances: "
                      f"{len(instance_dirs)}/{before} (>=1 agent passed)")

        if not instance_dirs:
            return []

        repo_root = self._ensure_repo_snapshot(ctx, runtime_name)
        # Evaluation outputs (never validation): evaluation/llm/<provider>/<model>/,
        # mirroring RepoBehave's evaluations/llm/<vendor>/<model>/ layout.
        out_root = ctx.run_dir / "evaluation" / "llm" / self.scope_key()
        out_root.mkdir(parents=True, exist_ok=True)

        verdicts: list[ValidationVerdict] = []
        total_cost = 0.0
        cost_known = True

        for index, instance_dir in enumerate(instance_dirs, start=1):
            instance_id = instance_dir.name
            print(f"[solver_llm][{index}/{len(instance_dirs)}] {instance_id} "
                  f"({provider}/{model})")
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
                max_repair_rounds=max_repair_rounds,
                float_tol=float_tol,
            )
            if inst_cost is None:
                cost_known = False
            else:
                total_cost += inst_cost
            status = "PASS" if verdict.passed else f"FAIL ({verdict.reason})"
            cost_str = f"${inst_cost:.4f}" if inst_cost is not None else "cost n/a"
            print(f"    -> {status}  [{cost_str}]")
            verdicts.append(verdict)

        summary = {
            "provider": provider,
            "model": model,
            "repo_map_mode": repo_map_mode,
            "instances": len(verdicts),
            "passed": sum(1 for v in verdicts if v.passed),
            "total_cost_usd": total_cost if cost_known else None,
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
        temperature, max_repair_rounds, float_tol,
    ):
        instance_id = instance_dir.name
        oracle = ctx.load_oracle(instance_dir)
        if oracle is None or "oracle_answer" not in oracle:
            return ValidationVerdict(instance_id, False, "unreadable oracle.json"), None

        host_out = out_root / instance_id
        host_out.mkdir(parents=True, exist_ok=True)
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
                    max_repair_rounds=max_repair_rounds,
                    trace=trace_lines.append,
                )
            except Exception as exc:  # API error / no valid JSON after repairs
                (host_out / "trace.log").write_text("\n".join(trace_lines), encoding="utf-8")
                return ValidationVerdict(
                    instance_id, False, f"llm inference failed: {type(exc).__name__}: {exc}",
                    {"provider": provider, "model": model},
                ), None

        # Persist artifacts.
        (host_out / "answer.json").write_text(
            json.dumps(parsed, indent=2) + "\n", encoding="utf-8"
        )
        (host_out / "debug.json").write_text(
            json.dumps(debug, indent=2, default=str) + "\n", encoding="utf-8"
        )
        (host_out / "trace.log").write_text("\n".join(trace_lines), encoding="utf-8")

        cost_obj = debug.get("cost") if isinstance(debug, dict) else None
        inst_cost = None
        if isinstance(cost_obj, dict):
            inst_cost = cost_obj.get("cost_usd")

        correct, reason = score_answer(oracle["oracle_answer"], parsed, float_tol=float_tol)
        details = {
            "provider": provider,
            "model": model,
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
