"""CLI entry point: python -m repogen generate --repo faker_qa --agent cursor --model <m>"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
        "defaults to ./.env then <project root>/.env",
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
    if args.command == "list":
        return cmd_list(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
