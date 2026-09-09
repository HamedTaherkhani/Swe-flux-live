"""CLI entry point: python -m repogen generate --repo faker_qa --agent cursor --model <m>"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Optional

from .agents import available_backends, create_backend
from .config import (
    ALL_CATEGORIES,
    PROJECT_ROOT,
    RunConfig,
    hydrate_provider_env,
    load_env_file,
    load_repositories,
)
from .orchestrator import Orchestrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repogen",
        description="Generate RepoBehave-style runtime-behavior QA instances "
        "from a benchmark Docker image, one agent session per instance.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="scout, plan, and generate instances")
    gen.add_argument("--repo", required=True, help="repo key in repositories.json")
    gen.add_argument("--image", default="", help="override Docker image for the repo")
    gen.add_argument(
        "--agent", default="cursor", choices=available_backends(),
        help="agent backend used to author each instance",
    )
    gen.add_argument("--model", required=True, help="model name for the agent backend")
    gen.add_argument("--num-instances", type=int, default=40)
    gen.add_argument(
        "--categories", default="all",
        help="comma-separated category names, or 'all' (see question taxonomy)",
    )
    gen.add_argument(
        "--repos-file", type=Path, default=PROJECT_ROOT / "repositories.json"
    )
    gen.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "out")
    gen.add_argument("--qa-dir-name", default="", help="QA dir name inside container")
    gen.add_argument("--workdir", default="/testbed")
    gen.add_argument("--seed", type=int, default=7)
    gen.add_argument(
        "--agent-timeout", type=int, default=900,
        help="seconds per instance (default 900 — caps the cost of hung agent "
        "sessions; healthy instances finish in 2-5 minutes)",
    )
    gen.add_argument(
        "--parallel", type=int, default=1,
        help="concurrent generation containers (default 1). Each worker runs "
        "its own agent session and pytest harvests, so budget RAM per worker "
        "(measure with `docker stats`; ML repos need far more than light ones)",
    )
    gen.add_argument("--max-per-module", type=int, default=3)
    gen.add_argument(
        "--plan-only", action="store_true",
        help="run scout + planner, write plan.json, generate nothing",
    )
    gen.add_argument(
        "--targets-json", type=Path, default=None,
        help="reuse a previously scouted targets.json instead of re-scouting",
    )
    gen.add_argument("--keep-container", action="store_true")
    gen.add_argument(
        "--env-file", type=Path, default=None,
        help=".env file with API keys (e.g. cursor_api_key=...); "
        "defaults to <project root>/.env",
    )

    screen = sub.add_parser(
        "screen",
        help="post-generation screening: exclude instances with invalid oracles, "
        "broken templates, failing tests, or too-shallow runtime behavior",
    )
    group = screen.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-dir", type=Path, help="run directory to screen")
    group.add_argument(
        "--repo", help="screen the latest run of this repo under --output-root"
    )
    screen.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "out")
    screen.add_argument(
        "--dry-run", action="store_true",
        help="report verdicts only; do not move excluded instances",
    )

    from .validation import available_evaluators, available_validation_stages

    validate = sub.add_parser(
        "validate",
        help="post-screening validation stages (default: solver_agent — a code "
        "agent answers each instance and must match the oracle; failures are discarded)",
    )
    vgroup = validate.add_mutually_exclusive_group(required=True)
    vgroup.add_argument("--run-dir", type=Path, help="run directory to validate")
    vgroup.add_argument(
        "--repo", help="validate the latest run of this repo under --output-root"
    )
    validate.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "out")
    validate.add_argument(
        "--validators", default="solver_agent",
        help=f"comma-separated validation stages to run in order "
        f"(available: {', '.join(available_validation_stages())})",
    )
    validate.add_argument(
        "--solver-agent", default="claude-code", choices=available_backends(),
        help="agent backend used by the solver_agent validator",
    )
    validate.add_argument(
        "--solver-model", default="",
        help="model for the solver agent (required for solver_agent)",
    )
    validate.add_argument("--solver-timeout", type=int, default=900)
    validate.add_argument(
        "--solver-effort", default="",
        choices=["", "low", "medium", "high", "xhigh", "max"],
        help="reasoning effort for claude-code solvers (default: CLI default, "
        "'high' on current Claude models). For cursor, encode effort in the "
        "model name instead (e.g. gpt-5.3-codex-high)",
    )
    validate.add_argument("--float-tol", type=float, default=1e-6)
    validate.add_argument(
        "--rollouts", type=int, default=1,
        help="independent solver sessions per instance; the instance passes "
        "only if ALL rollouts match the oracle (default 1)",
    )
    validate.add_argument(
        "--parallel", type=int, default=2,
        help="concurrent solver containers (default 2; budget ~1-1.5GB RAM "
        "each). All rollouts of one instance stay in one container",
    )
    validate.add_argument(
        "--dry-run", action="store_true",
        help="report verdicts only; do not discard instances",
    )
    validate.add_argument(
        "--no-discard", action="store_true",
        help="run inference and record this model's outputs + verdicts, but keep "
        "all instances (use to add a model's results without pruning instances/)",
    )
    validate.add_argument(
        "--env-file", type=Path, default=None,
        help=".env file with API keys; defaults to <project root>/.env",
    )

    # --- cascade: tiered agent validation (difficulty remains intrinsic) ---
    cascade = sub.add_parser(
        "cascade",
        help="tiered solver validation, weakest model first. Tier outcomes are "
        "saved as validation evidence only; intrinsic metrics own difficulty.",
    )
    cgroup = cascade.add_mutually_exclusive_group(required=True)
    cgroup.add_argument("--run-dir", type=Path, help="run directory to validate")
    cgroup.add_argument(
        "--repo", help="validate the latest run of this repo under --output-root"
    )
    cascade.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "out")
    cascade.add_argument(
        "--tier", action="append", dest="tiers", metavar="LABEL[/PARTIAL]=AGENT:MODEL",
        required=True,
        help="one validation tier, weakest model first; repeatable. LABEL is a "
        "validation band when all rollouts pass; with /PARTIAL, mixed-rollout "
        "instances get that band instead of escalating (only zero-pass "
        "instances move to the next tier). e.g. "
        "--tier haiku_all/haiku_partial=claude-code:claude-haiku-4-5-20251001 "
        "--tier fable_all=claude-code:claude-fable-5",
    )
    cascade.add_argument(
        "--rollouts", type=int, default=1,
        help="independent solver sessions per instance per tier; a tier accepts "
        "an instance only if ALL rollouts match the oracle (default 1)",
    )
    cascade.add_argument("--solver-timeout", type=int, default=900)
    cascade.add_argument(
        "--parallel", type=int, default=2,
        help="concurrent solver containers per tier (default 2; budget "
        "~1-1.5GB RAM each)",
    )
    cascade.add_argument(
        "--solver-effort", default="",
        choices=["", "low", "medium", "high", "xhigh", "max"],
        help="reasoning effort for claude-code solvers in every tier "
        "(default: CLI default, 'high' on current Claude models)",
    )
    cascade.add_argument("--float-tol", type=float, default=1e-6)
    cascade.add_argument(
        "--no-discard", action="store_true",
        help="keep instances that fail every tier (recorded as rejected in "
        "cascade_validation_report.json but not moved out of instances/)",
    )
    cascade.add_argument(
        "--only-instances", default="",
        help="comma-separated instance ids to run the cascade on; validation "
        "bands outside this set are preserved in cascade_validation_report.json "
        "(use to escalate a previous run's rejects to a stronger tier)",
    )
    cascade.add_argument(
        "--env-file", type=Path, default=None,
        help=".env file with API keys; defaults to <project root>/.env",
    )

    # --- evaluate: raw-LLM inference for measurement only (never discards) ---
    evaluate = sub.add_parser(
        "evaluate",
        help="evaluate a run with a raw LLM (no agent). Measures how the model "
        "answers each instance and records answers/scores/costs under "
        "evaluation/; NEVER discards instances.",
    )
    egroup = evaluate.add_mutually_exclusive_group(required=True)
    egroup.add_argument("--run-dir", type=Path, help="run directory to evaluate")
    egroup.add_argument(
        "--repo", help="evaluate the latest run of this repo under --output-root"
    )
    evaluate.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "out")
    evaluate.add_argument(
        "--evaluators", default="solver_llm",
        help=f"comma-separated evaluator names (available: "
        f"{', '.join(available_evaluators())})",
    )
    evaluate.add_argument(
        "--llm-provider", default="openai",
        choices=["openai", "anthropic", "gemini", "fireworks", "deepseek", "openrouter", "vllm", "kimi"],
        help="provider for the solver_llm evaluator",
    )
    evaluate.add_argument(
        "--llm-reasoning-effort", default="low",
        choices=["", "minimal", "low", "medium", "high", "max"],
        help="reasoning effort for providers that expose it (default low). "
        "Kimi K3 accepts only low|high|max, so other values are mapped to the "
        "nearest supported one; pass '' to send no effort at all",
    )
    evaluate.add_argument(
        "--llm-model", default="",
        help="model id for the solver_llm evaluator (required)",
    )
    evaluate.add_argument(
        "--repo-map-mode", default="repomap",
        choices=["repomap", "cheap_repomap", "none"],
        help="repo context mode (repomap needs aider-chat)",
    )
    evaluate.add_argument(
        "--container-runtime", default="docker", choices=["docker", "apptainer"],
        help="runtime used to snapshot the repo",
    )
    evaluate.add_argument(
        "--parallel", type=int, default=2,
        help="concurrent instances (default 2). Evaluation is pure API work "
        "over a shared read-only snapshot, so raise it until you hit the "
        "provider's rate limit",
    )
    evaluate.add_argument("--llm-max-read-lines", type=int, default=250)
    evaluate.add_argument("--llm-temperature", type=float, default=0.0)
    evaluate.add_argument("--llm-max-repair-rounds", type=int, default=2)
    evaluate.add_argument("--float-tol", type=float, default=1e-6)
    evaluate.add_argument(
        "--only-instances", default="",
        help="comma-separated instance ids to evaluate (subset of instances/); "
        "others are skipped entirely",
    )
    evaluate.add_argument(
        "--all-instances", action="store_true",
        help="override the validation safeguard and evaluate every instance in "
        "instances/ (default: only instances with at least one passing Haiku "
        "or Fable rollout in validation_report.json)",
    )
    evaluate.add_argument(
        "--env-file", type=Path, default=None,
        help=".env file with API keys; defaults to <project root>/.env",
    )

    complexity = sub.add_parser(
        "complexity",
        help="compute intrinsic semantic-reasoning, answer-construction, and "
        "repository-navigation complexity; optionally report held-out model "
        "accuracy in easy/medium/hard/very_hard bins",
    )
    xgroup = complexity.add_mutually_exclusive_group(required=True)
    xgroup.add_argument("--run-dir", type=Path, help="one run directory")
    xgroup.add_argument(
        "--repo", help="latest run of this repo under --output-root"
    )
    xgroup.add_argument(
        "--all-runs", action="store_true",
        help="pool every run containing instances under --output-root",
    )
    complexity.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "out")
    complexity.add_argument(
        "--evaluation-scope", default="",
        help="evaluation_report.json scope to report (for example kimi/kimi-k3); "
        "when omitted, report every available scope",
    )
    complexity.add_argument(
        "--easy-quantile", type=float, default=0.25,
        help="score quantile ending the easy bin (default 0.25)",
    )
    complexity.add_argument(
        "--medium-quantile", type=float, default=0.50,
        help="score quantile ending the medium bin (default 0.50)",
    )
    complexity.add_argument(
        "--very-hard-quantile", "--hard-quantile",
        dest="very_hard_quantile", type=float, default=0.75,
        help="score quantile starting the very_hard bin (default 0.75; "
        "--hard-quantile is retained as a compatibility alias)",
    )
    complexity.add_argument(
        "--stratify-by", default="answer_archetype",
        choices=["none", "category", "answer_archetype", "category_archetype"],
        help="compute score quantiles within comparable task groups "
        "(default answer_archetype)",
    )
    complexity.add_argument(
        "--navigation-stratify-by", default="none",
        choices=["none", "category", "answer_archetype", "category_archetype"],
        help="stratification used only for repository navigation (default none, "
        "because navigation burden is comparable across answer schemas)",
    )
    complexity.add_argument(
        "--report", type=Path, default=None,
        help="output JSON path (default: complexity_report.json in the run or output root)",
    )

    rollout_effort = sub.add_parser(
        "rollout-effort",
        help="measure observed tool use, exploration, execution, deliberation, "
        "friction, tokens, time, and cost in solver-agent validation trajectories",
    )
    rgroup = rollout_effort.add_mutually_exclusive_group(required=True)
    rgroup.add_argument("--run-dir", type=Path, help="one run directory")
    rgroup.add_argument("--repo", help="latest run of this repo under --output-root")
    rgroup.add_argument(
        "--all-runs", action="store_true",
        help="pool every run containing instances under --output-root",
    )
    rollout_effort.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "out")
    rollout_effort.add_argument("--agent", default="claude-code")
    rollout_effort.add_argument(
        "--model", default="", help="optional exact model-directory filter"
    )
    rollout_effort.add_argument(
        "--complexity-report", type=Path, default=None,
        help="optional intrinsic complexity report to join for grouped analysis",
    )
    rollout_effort.add_argument(
        "--matched-only", action="store_true",
        help="exclude every rollout that did not match the validation oracle",
    )
    rollout_effort.add_argument(
        "--aggregate-instances", action="store_true",
        help="average selected normalized rollout scores per instance across models",
    )
    rollout_effort.add_argument(
        "--evaluation-scope", default="",
        help="downstream evaluation scope whose accuracy is reported by averaged "
        "instance difficulty (for example kimi/kimi-k3)",
    )
    rollout_effort.add_argument(
        "--report", type=Path, default=None,
        help="output JSON path (default: rollout_effort_report.json in the run or output root)",
    )

    perturb = sub.add_parser(
        "perturb",
        help="make intrinsically harder instances by rewriting test INPUTS, "
        "re-harvesting a fresh oracle, and enforcing the frozen combined "
        "complexity target. Output remains a normal run directory.",
    )
    pgroup = perturb.add_mutually_exclusive_group(required=True)
    pgroup.add_argument("--run-dir", type=Path, help="run directory to perturb")
    pgroup.add_argument("--repo", help="perturb the latest run of this repo")
    perturb.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "out")
    perturb.add_argument(
        "--dest", type=Path, default=None,
        help="where to write perturbed instances (default: <output-root>/perturbation)",
    )
    perturb.add_argument(
        "--proposer", default="llm", choices=["llm", "agent"],
        help="how variants are proposed. 'llm': one API call per instance with "
        "read-only repo tools. 'agent': a coding agent inside the repo container "
        "that can RUN the test and fix a variant before proposing it",
    )
    perturb.add_argument(
        "--agent", default="cursor", choices=available_backends(),
        help="agent backend when --proposer agent (default cursor)",
    )
    perturb.add_argument(
        "--agent-model", default="gpt-5.6-sol-medium",
        help="model for the agent backend",
    )
    perturb.add_argument("--agent-timeout", type=int, default=600,
                         help="seconds per agent session (default 600 = 10 min)")
    perturb.add_argument(
        "--agent-parallel", type=int, default=1,
        help="agent containers running in parallel (default 1). Each is a full "
        "repo container, so budget memory accordingly",
    )
    perturb.add_argument(
        "--llm-provider", default="openai",
        choices=["openai", "anthropic", "gemini", "fireworks", "deepseek", "openrouter", "vllm", "kimi"],
        help="provider for the perturbation proposer (--proposer llm)",
    )
    perturb.add_argument("--llm-model", default="",
                         help="proposer model id (required for --proposer llm)")
    perturb.add_argument(
        "--llm-reasoning-effort", default="",
        choices=["", "minimal", "low", "medium", "high", "max"],
    )
    perturb.add_argument("--llm-temperature", type=float, default=1.0)
    perturb.add_argument(
        "--variants", type=int, default=5,
        help="candidate variants proposed per source instance (default 5)",
    )
    perturb.add_argument(
        "--threads", type=int, default=4,
        help="concurrent proposal calls (harvesting stays serial)",
    )
    perturb.add_argument(
        "--complexity-report", type=Path, default=None,
        help="intrinsic complexity report used for source selection, prompt "
        "scorecards, frozen thresholds, and candidate scoring (default: "
        "complexity_report.json in the source run or --output-root)",
    )
    perturb.add_argument(
        "--source-selection", default="validated-easy",
        choices=["validated-easy", "easy", "all"],
        help="source pool (default validated-easy: combined-easy, currently "
        "non-excluded instances with at least one matched Haiku/Fable rollout)",
    )
    perturb.add_argument(
        "--complexity-target", default="medium",
        choices=["increased", "medium", "hard", "very_hard", "none"],
        help="minimum frozen combined-complexity result required to keep a "
        "candidate (default medium; none restores historical behavior)",
    )
    perturb.add_argument(
        "--keep-below-complexity-target", action="store_true",
        help="retain valid candidates that miss --complexity-target so the full "
        "easy/medium/hard/very_hard outcome distribution can be measured",
    )
    perturb.add_argument(
        "--allow-metric-regressions", action="store_true",
        help="allow a candidate to satisfy the combined target even when one of "
        "semantic reasoning, answer construction, or navigation decreases",
    )
    perturb.add_argument(
        "--enforce-structure", action="store_true",
        help="opt in to the legacy AST check that requires definitions and the "
        "complete call multiset to match the original test",
    )
    perturb.add_argument(
        "--reuse-staged-variants", action="store_true",
        help="resume an interrupted run by reusing syntax-valid files already "
        "under <dest>/logs/<instance>/variants instead of regenerating them",
    )
    perturb.add_argument(
        "--flip-check", action="store_true",
        help="OPTIONAL evaluation-guided mode: after harvesting, solve each "
        "perturbed instance with the target "
        "model and record whether it flipped pass->fail (needs the source run's "
        "evaluation_report.json, or evaluates the original on demand)",
    )
    perturb.add_argument(
        "--target-provider", default="",
        choices=["", "openai", "anthropic", "gemini", "fireworks", "openrouter", "vllm", "kimi"],
        help="model being measured (default: the proposer's provider)",
    )
    perturb.add_argument("--target-model", default="",
                         help="model being measured (default: the proposer's model)")
    perturb.add_argument(
        "--target-effort", default="low",
        choices=["", "minimal", "low", "medium", "high", "max"],
        help="reasoning effort for the target model (default low)",
    )
    perturb.add_argument("--target-temperature", type=float, default=0.0)
    perturb.add_argument(
        "--require-flip", action="store_true",
        help="keep ONLY candidates that flip the target model pass->fail",
    )
    perturb.add_argument(
        "--no-baseline-check", dest="baseline_check", action="store_false", default=True,
        help="do not evaluate the original when the source run has no verdict "
        "for it (such instances then get no flip verdict)",
    )
    perturb.add_argument("--float-tol", type=float, default=1e-6)
    perturb.add_argument(
        "--feedback-iterations", type=int, default=0,
        help="refinement rounds for source instances whose variants did not "
        "reach the configured complexity target; the proposer is shown the "
        "measured score deltas (flip mode keeps its pass->fail objective)",
    )
    perturb.add_argument("--only-instances", default="", help="comma-separated source instance ids")
    perturb.add_argument("--max-instances", type=int, default=None)
    perturb.add_argument(
        "--sample-per-category", type=int, default=None,
        help="take at most N source instances per question_kind",
    )
    perturb.add_argument(
        "--only-passing", action="store_true",
        help="perturb only instances the evaluated model already got right "
        "(needs evaluation_report.json in the source run)",
    )
    perturb.add_argument(
        "--no-screen", dest="screen", action="store_false", default=True,
        help="keep harvested candidates even if they fail screening rules",
    )
    perturb.add_argument(
        "--keep-unchanged-oracle", dest="keep_all", action="store_true",
        help="deprecated no-op: candidates whose harvested answer equals the "
        "original's are now always kept and simply recorded as "
        "oracle_changed=false",
    )
    perturb.add_argument("--harvest-timeout", type=int, default=900)
    perturb.add_argument("--repo-map-mode", default="repomap",
                         choices=["repomap", "cheap_repomap", "none"])
    perturb.add_argument("--container-runtime", default="docker", choices=["docker", "apptainer"])
    perturb.add_argument("--env-file", type=Path, default=None)

    listing = sub.add_parser("list", help="list agents, categories, repos")
    listing.add_argument(
        "--repos-file", type=Path, default=PROJECT_ROOT / "repositories.json"
    )
    return parser


def cmd_generate(args: argparse.Namespace) -> int:
    loaded = load_env_file(args.env_file)
    if loaded:
        print(f"[env] loaded {loaded}")
    elif args.env_file:
        print(f"ERROR: env file not found: {args.env_file}", file=sys.stderr)
        return 2

    repos = load_repositories(args.repos_file)
    if args.repo not in repos and not args.image:
        print(
            f"ERROR: repo '{args.repo}' not in {args.repos_file} and no --image given.\n"
            f"Available: {', '.join(sorted(repos))}",
            file=sys.stderr,
        )
        return 2
    image = args.image or repos[args.repo]

    categories = (
        list(ALL_CATEGORIES)
        if args.categories.strip().lower() == "all"
        else [c.strip() for c in args.categories.split(",") if c.strip()]
    )

    config = RunConfig(
        repo_key=args.repo,
        image=image,
        agent_name=args.agent,
        model=args.model,
        num_instances=args.num_instances,
        categories=categories,
        output_root=args.output_root,
        workdir=args.workdir,
        qa_dir_name=args.qa_dir_name,
        seed=args.seed,
        agent_timeout_s=args.agent_timeout,
        agent_parallel=args.agent_parallel,
        parallel=args.parallel,
        max_targets_per_module=args.max_per_module,
        plan_only=args.plan_only,
        targets_json=args.targets_json,
        keep_container=args.keep_container,
    )

    backend = None
    if not config.plan_only:
        backend = create_backend(config.agent_name, config.model, config.agent_settings)

    run_dir = Orchestrator(config, backend).run()
    print(f"\nRun artifacts: {run_dir}")
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    from .screening import Screener

    run_dir = _resolve_run_dir(args)
    if run_dir is None:
        return 2

    print(f"Screening: {run_dir}{' (dry run)' if args.dry_run else ''}")
    verdicts = Screener(run_dir).screen(dry_run=args.dry_run)
    if not verdicts:
        print("No instances found to screen.")
        return 0

    kept = sum(1 for v in verdicts if v.kept)
    for verdict in verdicts:
        if verdict.kept:
            print(f"  KEEP    {verdict.instance_id}")
        else:
            reasons = "; ".join(
                f"{r.rule}: {r.reason}" for r in verdict.results if not r.passed
            )
            print(f"  EXCLUDE {verdict.instance_id}  [{reasons}]")
    print(
        f"\nKept {kept}/{len(verdicts)} instances "
        f"({len(verdicts) - kept} excluded"
        f"{' — would be moved without --dry-run' if args.dry_run else ' — moved to excluded_instances/'})."
    )
    print(f"Report: {run_dir / 'screening_report.json'}")
    if not args.dry_run:
        _refresh_intrinsic_for_run(run_dir, args.output_root)
    return 0


def _resolve_run_dir(args: argparse.Namespace) -> Optional[Path]:
    run_dir = args.run_dir
    if run_dir is None:
        repo_root = args.output_root / args.repo
        runs = sorted(repo_root.glob("run_*")) if repo_root.is_dir() else []
        if not runs:
            print(f"ERROR: no runs found under {repo_root}", file=sys.stderr)
            return None
        run_dir = runs[-1]
    if not (run_dir / "instances").is_dir():
        print(f"ERROR: no instances/ directory in {run_dir}", file=sys.stderr)
        return None
    return run_dir


def _refresh_intrinsic_for_run(run_dir: Path, output_root: Path) -> dict:
    """Refresh canonical intrinsic labels after the current instance set changes."""
    from .complexity import refresh_intrinsic_difficulties

    frozen = _refresh_frozen_perturbation_report(run_dir)
    if frozen is not None:
        print(
            f"Intrinsic difficulty filtered with frozen source thresholds: "
            f"{frozen['instance_count']} instance(s) -> "
            f"{run_dir / 'complexity_report.json'}"
        )
        return frozen

    candidates = sorted(
        path for path in output_root.glob("*/run_*")
        if (path / "instances").is_dir()
    )
    if run_dir.resolve() in {path.resolve() for path in candidates}:
        run_dirs = candidates
        report_path = output_root / "complexity_report.json"
    else:
        run_dirs = [run_dir]
        report_path = run_dir / "complexity_report.json"
    report = refresh_intrinsic_difficulties(
        run_dirs, aggregate_report_path=report_path,
    )
    print(
        f"Intrinsic difficulty refreshed: {report['instance_count']} instance(s) "
        f"-> {report_path}"
    )
    return report


def _refresh_frozen_perturbation_report(run_dir: Path) -> Optional[dict]:
    """Filter a perturbation report without re-binning its small candidate set.

    Perturbation labels are deliberately assigned with the source collection's
    frozen thresholds.  Screening or validation may remove candidates, but it
    must not recalibrate the bins from the survivors in one repository.
    """
    perturbation_path = run_dir / "perturbation_report.json"
    if not perturbation_path.is_file():
        return None
    try:
        perturbation = json.loads(perturbation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    raw_source_report = (
        perturbation.get("complexity_objective", {}).get("report")
    )
    if not raw_source_report:
        return None
    source_report_path = Path(raw_source_report)
    if not source_report_path.is_absolute():
        source_report_path = PROJECT_ROOT / source_report_path
    try:
        source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    active_ids = {
        path.name
        for path in (run_dir / "instances").iterdir()
        if path.is_dir() and (path / "oracle.json").is_file()
    }
    source_run = Path(perturbation.get("source_run_dir", ""))
    if not source_run.is_absolute():
        source_run = PROJECT_ROOT / source_run
    source_records = {}
    for record in source_report.get("instances", []):
        try:
            record_run = Path(record.get("run_dir", ""))
            if not record_run.is_absolute():
                record_run = PROJECT_ROOT / record_run
            if record_run.resolve() != source_run.resolve():
                continue
        except (OSError, TypeError):
            continue
        source_records[str(record.get("instance_id", ""))] = record

    records = []
    for attempt in perturbation.get("attempts", []):
        new_id = str(attempt.get("new_id", ""))
        if not attempt.get("kept") or new_id not in active_ids:
            continue
        original_id = str(attempt.get("original_id", ""))
        source = source_records.get(original_id, {})
        records.append({
            "run_dir": str(run_dir),
            "instance_id": new_id,
            "category": attempt.get("category", source.get("category", "")),
            "answer_archetype": source.get("answer_archetype", ""),
            "scores": attempt.get("candidate_complexity_scores", {}),
            "components": attempt.get("candidate_complexity_components", {}),
            "features": attempt.get("candidate_complexity_features", {}),
            "difficulty": attempt.get("candidate_complexity_difficulties", {}),
            "perturbed_from": original_id,
            "source_difficulty": attempt.get("source_complexity_difficulties", {}),
            "source_scores": attempt.get("source_complexity_scores", {}),
            "score_deltas": attempt.get("complexity_deltas", {}),
        })

    payload = {
        "schema_version": 2,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "methodology": {
            "intrinsic_inputs": [
                "source plan.json", "harvested trace.log", "oracle.json",
                "testcase.py", "eval.sh",
            ],
            "excluded_inputs": [
                "evaluation_report.json", "downstream model outcomes",
                "solver rollout effort",
            ],
            "combined_weights": {
                "semantic_reasoning": 0.40,
                "answer_construction": 0.35,
                "repository_navigation": 0.25,
            },
            "binning": "thresholds frozen from the source complexity report",
        },
        "source_complexity_report": str(source_report_path),
        "run_dirs": [str(run_dir)],
        "instance_count": len(records),
        "thresholds": source_report.get("thresholds", {}),
        "instances": records,
        "accuracy_by_scope": {},
    }
    report_path = run_dir / "complexity_report.json"
    report_path.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return payload


def cmd_validate(args: argparse.Namespace) -> int:
    from .validation import (
        ValidationContext,
        available_evaluators,
        create_validator,
        run_validators,
    )

    loaded = load_env_file(args.env_file)
    if loaded:
        print(f"[env] loaded {loaded}")
    hydrate_provider_env()

    run_dir = _resolve_run_dir(args)
    if run_dir is None:
        return 2

    names = [n.strip() for n in args.validators.split(",") if n.strip()]
    eval_only = [n for n in names if n in available_evaluators()]
    if eval_only:
        print(
            f"ERROR: {eval_only} are evaluation-only; run them with "
            f"'repogen evaluate', not 'validate'.",
            file=sys.stderr,
        )
        return 2
    if "solver_agent" in names and not args.solver_model:
        print(
            "ERROR: --solver-model is required for the solver_agent validator.",
            file=sys.stderr,
        )
        return 2

    validators = []
    for name in names:
        settings = {}
        if name == "solver_agent":
            settings = {
                "agent": args.solver_agent,
                "model": args.solver_model,
                "timeout_s": args.solver_timeout,
                "float_tol": args.float_tol,
                "rollouts": args.rollouts,
                "effort": args.solver_effort,
                "parallel": args.parallel,
            }
        validators.append(create_validator(name, settings))

    discard = not (args.dry_run or args.no_discard)
    ctx = ValidationContext.from_run_dir(run_dir)
    mode = "" if discard else "  (no discard — recording only)"
    print(f"Validating: {run_dir}{mode}")
    report = run_validators(ctx, validators, discard=discard)

    # Show only the runs added by this invocation (the tail of the accumulated log).
    new_runs = report["runs"][-len(validators):] if validators else []
    for run in new_runs:
        scope = run.get("scope", run["validator"])
        verb = "discarded" if run.get("discarded") else "would discard"
        print(f"\nStage '{run['validator']}' [{scope}]: "
              f"{run['passed']}/{run['total']} passed, {run['failed']} {verb}")
        for verdict in run["verdicts"]:
            mark = "PASS   " if verdict["passed"] else "FAIL   "
            reason = f"  [{verdict['reason']}]" if verdict["reason"] else ""
            print(f"  {mark} {verdict['instance_id']}{reason}")
    print(f"\nTotal recorded runs in this dir: {len(report['runs'])}")
    print(f"Remaining instances: {len(report['remaining_instances'])}")
    print(f"Report: {run_dir / 'validation_report.json'}")
    if discard:
        _refresh_intrinsic_for_run(run_dir, args.output_root)
    return 0


def cmd_cascade(args: argparse.Namespace) -> int:
    from .validation import ValidationContext
    from .validation.cascade import CascadeTier, run_cascade

    loaded = load_env_file(args.env_file)
    if loaded:
        print(f"[env] loaded {loaded}")
    hydrate_provider_env()

    run_dir = _resolve_run_dir(args)
    if run_dir is None:
        return 2

    try:
        tiers = [CascadeTier.parse(spec) for spec in args.tiers]
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    backends = set(available_backends())
    bad = [t.agent for t in tiers if t.agent not in backends]
    if bad:
        print(
            f"ERROR: unknown agent backend(s) {sorted(set(bad))}; "
            f"available: {', '.join(sorted(backends))}",
            file=sys.stderr,
        )
        return 2

    ctx = ValidationContext.from_run_dir(run_dir)
    ladder = " -> ".join(f"{t.label}({t.agent}/{t.model})" for t in tiers)
    print(f"Cascade on {run_dir}\n  ladder: {ladder}\n  rollouts per tier: {args.rollouts}")
    try:
        report = run_cascade(
            ctx, tiers,
            rollouts=args.rollouts,
            timeout_s=args.solver_timeout,
            float_tol=args.float_tol,
            effort=args.solver_effort,
            parallel=args.parallel,
            discard=not args.no_discard,
            only_instance_ids=(
                [s.strip() for s in args.only_instances.split(",") if s.strip()]
                if args.only_instances.strip() else None
            ),
        )
    except (ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print("\nCascade validation bands:")
    by_label: dict[str, list[str]] = {}
    for instance_id, record in sorted(report["assignments"].items()):
        band = record.get("validation_band", record.get("difficulty", "unknown"))
        by_label.setdefault(band, []).append(instance_id)
    ordered_bands = []
    for tier in tiers:
        ordered_bands.append(tier.label)
        if tier.partial_label:
            ordered_bands.append(tier.partial_label)
    for band in ordered_bands:
        ids = by_label.get(band, [])
        print(f"  {band} ({len(ids)}):")
        for instance_id in ids:
            print(f"    {instance_id}")
    rejected = report["rejected"]
    verb = "discarded" if report["rejected_discarded"] else "kept (no-discard)"
    print(f"  rejected — failed every tier ({len(rejected)}, {verb}):")
    for instance_id in rejected:
        print(f"    {instance_id}")
    print(f"\nReport: {run_dir / 'cascade_validation_report.json'}")
    print(f"Per-tier runs recorded in: {run_dir / 'validation_report.json'}")
    _refresh_intrinsic_for_run(run_dir, args.output_root)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from .validation import ValidationContext, create_validator, run_evaluators

    loaded = load_env_file(args.env_file)
    if loaded:
        print(f"[env] loaded {loaded}")
    filled = hydrate_provider_env()
    if filled:
        print(f"[env] provider keys resolved: {', '.join(filled)}")

    run_dir = _resolve_run_dir(args)
    if run_dir is None:
        return 2

    names = [n.strip() for n in args.evaluators.split(",") if n.strip()]
    if "solver_llm" in names and not args.llm_model:
        print("ERROR: --llm-model is required for the solver_llm evaluator.", file=sys.stderr)
        return 2

    evaluators = []
    for name in names:
        settings = {}
        if name == "solver_llm":
            settings = {
                "provider": args.llm_provider,
                "model": args.llm_model,
                "repo_map_mode": args.repo_map_mode,
                "container_runtime": args.container_runtime,
                "max_read_lines": args.llm_max_read_lines,
                "temperature": args.llm_temperature,
                "reasoning_effort": args.llm_reasoning_effort,
                "max_repair_rounds": args.llm_max_repair_rounds,
                "float_tol": args.float_tol,
                "only_agent_validated": not args.all_instances,
                "instance_ids": [
                    i.strip() for i in args.only_instances.split(",") if i.strip()
                ],
                "parallel": args.parallel,
            }
        evaluators.append(create_validator(name, settings))

    ctx = ValidationContext.from_run_dir(run_dir)
    print(f"Evaluating (no discard): {run_dir}")
    report = run_evaluators(ctx, evaluators)

    new_runs = report["runs"][-len(evaluators):] if evaluators else []
    for run in new_runs:
        scope = run.get("scope", run["validator"])
        print(f"\nEvaluator '{run['validator']}' [{scope}]: "
              f"{run['passed']}/{run['total']} correct")
        for verdict in run["verdicts"]:
            mark = "CORRECT" if verdict["passed"] else "WRONG  "
            reason = f"  [{verdict['reason']}]" if verdict["reason"] else ""
            print(f"  {mark} {verdict['instance_id']}{reason}")
    print(f"\nEvaluation outputs: {run_dir / 'evaluation'}")
    print(f"Report: {run_dir / 'evaluation_report.json'}")
    return 0


def cmd_complexity(args: argparse.Namespace) -> int:
    from .complexity import (
        METRICS,
        build_report,
        materialize_difficulty_reports,
        write_report,
    )

    if args.all_runs:
        run_dirs = sorted(
            path for path in args.output_root.glob("*/run_*")
            if (path / "instances").is_dir()
        )
        if not run_dirs:
            print(f"ERROR: no runs with instances found under {args.output_root}", file=sys.stderr)
            return 2
        default_report = args.output_root / "complexity_report.json"
    else:
        run_dir = _resolve_run_dir(args)
        if run_dir is None:
            return 2
        run_dirs = [run_dir]
        default_report = run_dir / "complexity_report.json"

    try:
        report = build_report(
            run_dirs,
            evaluation_scope=args.evaluation_scope,
            easy_quantile=args.easy_quantile,
            medium_quantile=args.medium_quantile,
            very_hard_quantile=args.very_hard_quantile,
            stratify_by=args.stratify_by,
            repository_navigation_stratify_by=args.navigation_stratify_by,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    report_path = args.report or default_report
    write_report(report, report_path)
    materialized = materialize_difficulty_reports(report, source_report=report_path)

    print(
        f"Intrinsic complexity: {report['instance_count']} instance(s) across "
        f"{len(report['run_dirs'])} run(s)"
    )
    for metric in METRICS:
        threshold = report["thresholds"].get(metric)
        if threshold:
            print(
                f"  {metric}: {threshold['easy_quantile']:.0%}/"
                f"{threshold['medium_quantile']:.0%}/"
                f"{threshold['very_hard_quantile']:.0%} "
                f"quantiles within {threshold['stratify_by']} "
                f"({len(threshold['strata'])} strata)"
            )
    if not report["accuracy_by_scope"]:
        requested = f" for scope {args.evaluation_scope!r}" if args.evaluation_scope else ""
        print(f"\nNo evaluation outcomes found{requested}; scores and bins were still written.")
    for scope, metric_results in report["accuracy_by_scope"].items():
        print(f"\nHeld-out accuracy [{scope}]:")
        for metric in METRICS:
            cells = []
            for row in metric_results[metric]:
                accuracy = "n/a" if row["accuracy"] is None else f"{100 * row['accuracy']:.1f}%"
                cells.append(
                    f"{row['difficulty']} {row['correct']}/{row['total']} ({accuracy})"
                )
            print(f"  {metric}: " + "; ".join(cells))
    print(f"\nReport: {report_path}")
    print(
        f"Difficulty artifacts: {sum(materialized.values())} instance(s) across "
        f"{len(materialized)} run(s)"
    )
    return 0


def cmd_rollout_effort(args: argparse.Namespace) -> int:
    from .rollout_effort import build_report, write_report

    if args.all_runs:
        run_dirs = sorted(
            path for path in args.output_root.glob("*/run_*")
            if (path / "instances").is_dir()
        )
        if not run_dirs:
            print(f"ERROR: no runs with instances found under {args.output_root}", file=sys.stderr)
            return 2
        default_report = args.output_root / "rollout_effort_report.json"
    else:
        run_dir = _resolve_run_dir(args)
        if run_dir is None:
            return 2
        run_dirs = [run_dir]
        default_report = run_dir / "rollout_effort_report.json"

    complexity_report = args.complexity_report
    if complexity_report is None:
        pooled = args.output_root / "complexity_report.json"
        local = run_dirs[0] / "complexity_report.json"
        complexity_report = pooled if pooled.is_file() else local if local.is_file() else None

    report = build_report(
        run_dirs,
        agent=args.agent,
        model=args.model,
        complexity_report=complexity_report,
        matched_only=args.matched_only,
        aggregate_instances=args.aggregate_instances,
        downstream_evaluation_scope=args.evaluation_scope,
    )
    report_path = args.report or default_report
    write_report(report, report_path)

    overall = report["summary"]["overall"]
    print(
        f"Observed validator effort: {report['rollout_count']} rollout(s), "
        f"{overall['instances']} instance(s), {len(report['parse_failures'])} parse failure(s)"
    )
    if args.matched_only:
        print(
            f"  matched-only filter: excluded {report['excluded_mismatched_rollouts']} "
            f"mismatched and {report['excluded_unknown_outcome_rollouts']} unknown rollout(s)"
        )

    def show_group(title: str, groups: dict) -> None:
        print(f"\n{title}:")
        for name, summary in groups.items():
            metrics = summary["metrics"]
            rate = summary["oracle_match_rate"]
            rate_text = "n/a" if rate is None else f"{100 * rate:.1f}%"
            print(
                f"  {name}: n={summary['rollouts']}, match={rate_text}, "
                f"effort={metrics['observed_effort_score']['mean']:.2f}, "
                f"tools={metrics['tool_calls']['mean']:.1f}, "
                f"source_files={metrics['unique_source_files_read']['mean']:.1f}, "
                f"executions={metrics['execution_commands']['mean']:.1f}, "
                f"thinking≈{metrics['thinking_tokens_estimate']['mean']:.0f} tokens, "
                f"duration={metrics['duration_seconds']['mean']:.1f}s"
            )

    show_group("By model", report["summary"]["by_model"])
    show_group("By oracle-match outcome", report["summary"]["by_outcome"])
    show_group("By observed effort label", report["summary"]["by_observed_effort_label"])
    if report["summary"]["by_intrinsic_combined_difficulty"]:
        show_group(
            "By intrinsic combined difficulty",
            report["summary"]["by_intrinsic_combined_difficulty"],
        )
    if report["downstream_accuracy_by_average_effort_difficulty"]:
        print(f"\nDownstream accuracy [{args.evaluation_scope}] by average instance effort:")
        for row in report["downstream_accuracy_by_average_effort_difficulty"]:
            accuracy = "n/a" if row["accuracy"] is None else f"{100 * row['accuracy']:.1f}%"
            print(
                f"  {row['difficulty']}: {row['correct']}/{row['total']} "
                f"({accuracy}), mean effort={row['mean_average_effort_score']:.2f}"
            )
    print(f"\nReport: {report_path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    print("Agent backends:", ", ".join(available_backends()))
    print("Categories:", ", ".join(ALL_CATEGORIES))
    repos = load_repositories(args.repos_file)
    print("Repositories:")
    for key, image in sorted(repos.items()):
        print(f"  {key}: {image}")
    return 0


def _repo_and_image(run_dir: Path, repo_hint=None) -> tuple:
    """Read repo_key/image out of a run's run_config.json."""
    config_path = run_dir / "run_config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read {config_path}: {exc}", file=sys.stderr)
        return (repo_hint or ""), ""
    repo_key = config.get("repo_key") or config.get("repo") or repo_hint or ""
    return repo_key, config.get("image", "")


def cmd_perturb(args: argparse.Namespace) -> int:
    from .perturbation import PerturbationConfig, PerturbationPipeline
    from .perturbation.feedback import FeedbackRunner

    loaded = load_env_file(args.env_file)
    if loaded:
        print(f"[env] loaded {loaded}")
    filled = hydrate_provider_env()
    if filled:
        print(f"[env] provider keys resolved: {', '.join(filled)}")

    if args.proposer == "llm" and not args.llm_model:
        print("ERROR: --llm-model is required for --proposer llm.", file=sys.stderr)
        return 2
    if args.proposer == "agent" and not args.agent_model:
        print("ERROR: --agent-model is required for --proposer agent.", file=sys.stderr)
        return 2

    run_dir = _resolve_run_dir(args)
    if run_dir is None:
        return 2

    repo_key, image = _repo_and_image(run_dir, getattr(args, "repo", None))
    if not image:
        print(f"ERROR: could not resolve the repo image for {run_dir}", file=sys.stderr)
        return 2

    complexity_report = args.complexity_report
    if complexity_report is None:
        candidates = (
            run_dir / "complexity_report.json",
            args.output_root / "complexity_report.json",
        )
        complexity_report = next((path for path in candidates if path.is_file()), None)
    needs_complexity = (
        args.source_selection != "all" or args.complexity_target != "none"
    )
    if needs_complexity and complexity_report is None:
        print(
            "ERROR: intrinsic perturbation needs complexity_report.json. Run "
            "`python3 -m repogen complexity --run-dir ...` or pass "
            "--complexity-report. Use --source-selection all "
            "--complexity-target none only to restore the legacy behavior.",
            file=sys.stderr,
        )
        return 2

    config = PerturbationConfig(
        run_dir=run_dir,
        repo_key=repo_key,
        image=image,
        output_root=args.dest or args.output_root / "perturbation",
        instance_ids=[i.strip() for i in args.only_instances.split(",") if i.strip()] or None,
        max_instances=args.max_instances,
        source_selection=args.source_selection,
        complexity_report=complexity_report,
        complexity_target=args.complexity_target,
        keep_below_complexity_target=args.keep_below_complexity_target,
        require_all_metric_increases=not args.allow_metric_regressions,
        enforce_structure=args.enforce_structure,
        reuse_staged_variants=args.reuse_staged_variants,
        only_passing=args.only_passing,
        sample_per_category=args.sample_per_category,
        proposer=args.proposer,
        agent=args.agent,
        agent_model=args.agent_model,
        agent_timeout_s=args.agent_timeout,
        agent_parallel=args.agent_parallel,
        provider=args.llm_provider,
        model=args.llm_model,
        temperature=args.llm_temperature,
        reasoning_effort=args.llm_reasoning_effort,
        variants=args.variants,
        threads=args.threads,
        feedback_iterations=args.feedback_iterations,
        flip_check=args.flip_check or args.require_flip,
        target_provider=args.target_provider,
        target_model=args.target_model,
        target_effort=args.target_effort,
        target_temperature=args.target_temperature,
        require_flip=args.require_flip,
        baseline_check=args.baseline_check,
        float_tol=args.float_tol,
        harvest_timeout=args.harvest_timeout,
        screen=args.screen,
        keep_all=args.keep_all,
        repo_map_mode=args.repo_map_mode,
        container_runtime=args.container_runtime,
        env_file=args.env_file,
    )

    try:
        pipeline = PerturbationPipeline(config)
        pipeline.run()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.feedback_iterations > 0:
        FeedbackRunner(pipeline, args.feedback_iterations).run()

    report = pipeline.write_report()
    kept = [a for a in pipeline.attempts if a.kept]
    print(f"\nKept {len(kept)}/{len(pipeline.attempts)} candidate(s)")
    if config.flip_check:
        flipped = [a for a in pipeline.attempts if a.flipped]
        checked = [a for a in pipeline.attempts if a.flipped is not None]
        print(f"Flipped pass->fail: {len(flipped)}/{len(checked)} checked "
              f"({config.flip_provider}/{config.flip_model})")
        if pipeline.infra_aborted:
            print("WARNING: the provider refused mid-run, so the flip stage was "
                  "switched off. Instances are intact; re-run the flip stage "
                  "once the account works to get real numbers.", file=sys.stderr)
    print(f"Perturbed run dir: {pipeline.output_root}")
    print(f"Report: {report}")
    if kept:
        print("\nCombined labels are already frozen in complexity_report.json.")
        print("Next: validate perturbed-instance solvability with the agent gate:")
        print(f"  python3 -m repogen validate --run-dir {pipeline.output_root} \\")
        print("    --validators solver_agent --solver-agent claude-code \\")
        print("    --solver-model claude-haiku-4-5-20251001 --rollouts 1 --parallel 4")
    return 0 if kept else 1


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "generate":
        return cmd_generate(args)
    if args.command == "screen":
        return cmd_screen(args)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "cascade":
        return cmd_cascade(args)
    if args.command == "evaluate":
        return cmd_evaluate(args)
    if args.command == "complexity":
        return cmd_complexity(args)
    if args.command == "rollout-effort":
        return cmd_rollout_effort(args)
    if args.command == "perturb":
        return cmd_perturb(args)
    if args.command == "list":
        return cmd_list(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
