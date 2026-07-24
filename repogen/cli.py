"""CLI entry point: python -m repogen generate --repo faker_qa --agent cursor --model <m>"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from .agents import available_backends, create_backend
from .config import (
    ALL_CATEGORIES,
    PROJECT_ROOT,
    RunConfig,
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
    gen.add_argument("--agent-timeout", type=int, default=2400, help="seconds per instance")
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

    from .validation import available_validators

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
        help=f"comma-separated validator names to run in order "
        f"(available: {', '.join(available_validators())})",
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
    # --- solver_llm (raw LLM inference, no agent) ---
    validate.add_argument(
        "--llm-provider", default="openai",
        choices=["openai", "anthropic", "gemini", "fireworks", "openrouter", "vllm"],
        help="provider for the solver_llm validator",
    )
    validate.add_argument(
        "--llm-model", default="",
        help="model id for the solver_llm validator (required when using solver_llm)",
    )
    validate.add_argument(
        "--repo-map-mode", default="repomap",
        choices=["repomap", "cheap_repomap", "none"],
        help="repo context mode for solver_llm (repomap needs aider-chat)",
    )
    validate.add_argument(
        "--container-runtime", default="docker", choices=["docker", "apptainer"],
        help="runtime used to snapshot the repo for solver_llm",
    )
    validate.add_argument("--llm-max-read-lines", type=int, default=250)
    validate.add_argument("--llm-temperature", type=float, default=0.0)
    validate.add_argument("--llm-max-repair-rounds", type=int, default=2)
    validate.add_argument("--float-tol", type=float, default=1e-6)
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


def cmd_validate(args: argparse.Namespace) -> int:
    from .validation import ValidationContext, create_validator, run_validators

    loaded = load_env_file(args.env_file)
    if loaded:
        print(f"[env] loaded {loaded}")

    run_dir = _resolve_run_dir(args)
    if run_dir is None:
        return 2

    names = [n.strip() for n in args.validators.split(",") if n.strip()]
    if "solver_agent" in names and not args.solver_model:
        print(
            "ERROR: --solver-model is required for the solver_agent validator.",
            file=sys.stderr,
        )
        return 2
    if "solver_llm" in names and not args.llm_model:
        print(
            "ERROR: --llm-model is required for the solver_llm validator.",
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
            }
        elif name == "solver_llm":
            settings = {
                "provider": args.llm_provider,
                "model": args.llm_model,
                "repo_map_mode": args.repo_map_mode,
                "container_runtime": args.container_runtime,
                "max_read_lines": args.llm_max_read_lines,
                "temperature": args.llm_temperature,
                "max_repair_rounds": args.llm_max_repair_rounds,
                "float_tol": args.float_tol,
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
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    print("Agent backends:", ", ".join(available_backends()))
    print("Categories:", ", ".join(ALL_CATEGORIES))
    repos = load_repositories(args.repos_file)
    print("Repositories:")
    for key, image in sorted(repos.items()):
        print(f"  {key}: {image}")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "generate":
        return cmd_generate(args)
    if args.command == "screen":
        return cmd_screen(args)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "list":
        return cmd_list(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
