"""Agent-based perturbation proposer.

The LLM proposer reasons about the test from a read-only snapshot: it can read
source, but it cannot execute anything, so it guesses whether its inputs stay in
the function's domain and whether the loop it targeted actually runs. Roughly a
quarter of its proposals die at harvest for exactly that reason.

An agent runs INSIDE the repo's own container, so it can do what the API caller
cannot: run the test, look at what happened, and fix the variant before handing
it over. It is still only a proposer -- every variant it writes is harvested,
screened and scored by the same downstream pipeline.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from ..agents import create_backend
from ..docker_env import Container
from .proposer import structure_preserved, strip_code_fences

_PROMPT = """\
You are building HARDER variants of one pytest test for a code-reasoning
benchmark. Hardness is the intrinsic combined-complexity score described below.
Downstream evaluation outcomes are unavailable and must not be optimized.

# Where everything is

You are inside the repository container. The repository is at:
  {workdir}

The instance has been staged exactly as the benchmark harness stages it:
  instance dir : {instance_dir}
  test file    : {staged_test}          <- the ORIGINAL test, unmodified

The function under test, which the harness traces to build the answer:
  file        : {abs_trace_file}
  function(s) : {trace_func}

The question asked about this test. You do NOT have to answer it -- the answer is
recomputed by running your variant. It tells you which runtime quantities matter:
{question}

# Your task

Write {n} variant versions of the test file to:
  {out_dir}/variant_1.py ... {out_dir}/variant_{n}.py

Each variant must:
{structure_policy}
1. Still PASS when run, and still reach the traced function. If the question is
   about a loop, that loop's body must still execute.
2. Increase the measured combined complexity:
   - SEMANTIC REASONING (40%): raise the diagnosed control-flow, state-tracking,
     interprocedural, exception-semantics, and execution-workload submetrics.
     Create executed branch alternatives, changed-state events, deeper calls,
     distinct lines, and meaningful state-varying repetition. Dead static
     complexity and one identical repeated path are weak.
   - ANSWER CONSTRUCTION (35%): produce more answer leaves/ordered events and,
     where the fixed schema permits, deeper structure or more exact-value detail.
     Prefer varied histories/events over merely increasing one scalar.
   - REPOSITORY NAVIGATION (25%): raise the actionable executed-code-footprint
     submetric by making INPUTS activate more DISTINCT source lines, indirect
     dispatch, callbacks, and helpers. Never game inverse support submetrics by
     deleting imports, paths, symbols, calls, or question clues.

   ALL THREE dimension scores must increase. Do not sacrifice one metric to
   improve the combined average.

   Current intrinsic scorecard and frozen target:
{complexity_context}

   Follow its PRIORITY ORDER. Before editing, identify the lowest actionable
   submetric in each metric and the exact implementation behavior that input
   values can activate. Focus first on metrics labelled EASY, then MEDIUM, while
   preserving and increasing metrics that are already HARD or VERY_HARD.

   The original has {baseline_events} line events across
   {baseline_distinct_lines} distinct executed lines. Increase distinct executed
   lines through harder inputs. Raw repetition alone is not the objective.

# How to make the inputs harder

- Replace small or homogeneous collections with larger, heterogeneous but valid
  collections whose elements exercise different branches in the same run.
- Choose values below, exactly at, and above real comparison thresholds found in
  the implementation; include valid empty/non-empty, zero/sign, duplicate/unique,
  boundary-length, encoding, and nesting cases when supported.
- Increase loop work only when different elements produce different paths or
  answer events. Repeating the same value is not sufficient.
- Prefer inputs that cause the existing calls to traverse additional helpers and
  distinct source lines and produce a larger, more detailed oracle answer.
- Keep every value inside the function's valid domain and preserve passing
  assertions. Verify behavior by execution; do not guess.

# Verify every variant by running it -- do not guess

Unlike a static reader you can execute code and MEASURE the result. For each
variant, repeat this loop until it passes and has genuinely richer behavior:

  1. Read {abs_trace_file} to find the loops in {trace_func} and what bounds
     them, plus the conditions it branches on. Choose inputs against those.

  2. Install the variant and run the harness exactly as the benchmark will:

       cd {workdir}
       cp {out_dir}/variant_1.py {staged_test}
       bash {instance_dir}/eval.sh {workdir}

     This runs the real pytest node id and writes the execution trace to:
       {trace_log}

  3. Measure the trace as a diagnostic:

       grep -c " event=line " {trace_log}

     Also count unique file:line locations and inspect distinct functions,
     branches/transitions, and varied iterations. If the test failed, the traced
     function was never reached, distinct executed lines did not increase, or the
     behavior is just one repeated path, change the INPUT VALUES and retry.

  4. Once it passes and the trace is long enough, keep the file and move on to
     the next variant.

  5. When all {n} variants are done, restore the original test:

       cp {original_backup} {staged_test}

A variant that crashes, never reaches the traced function, or fails to raise the
combined intrinsic score gets discarded later. Execution lets you choose inputs
from observed behavior instead of guessing.

# Rules about what you may change on disk

Write ONLY the files under {out_dir}. Do not modify the repository under
{workdir} (other than the temporary copy-over-and-restore of the staged test
described above), and do not edit any other benchmark file.
"""


@dataclass
class AgentProposerConfig:
    agent: str = "cursor"
    model: str = "gpt-5.6-sol-medium"
    n: int = 5
    timeout_s: int = 1800
    settings: Optional[dict] = None
    enforce_structure: bool = False


class AgentProposer:
    """Runs one agent session per instance inside the repo container."""

    def __init__(
        self, config: AgentProposerConfig, trace: Optional[Callable[[str], None]] = None
    ) -> None:
        self.config = config
        self.trace = trace
        self.last_error = ""
        self.backend = create_backend(config.agent, config.model, config.settings or {})
        self._prepared: set = set()

    def _t(self, msg: str) -> None:
        if self.trace:
            self.trace(msg)

    def prepare(self, container: Container) -> None:
        """Install the agent CLI once per container."""
        key = id(container)
        if key in self._prepared:
            return
        self.backend.prepare(container)
        self._prepared.add(key)

    def propose(
        self,
        *,
        container: Container,
        original_source: str,
        instance_id: str,
        instance_dir: Path,
        test_id: str,
        qa_dir_name: str,
        shared_dir: Optional[Path],
        trace_file: str,
        trace_funcs: List[str],
        question: str,
        workdir: str,
        host_log_dir: Path,
        baseline_events: int = 0,
        baseline_distinct_lines: int = 0,
        complexity_context: str = "(no intrinsic scorecard available)",
        n: Optional[int] = None,
    ) -> List[str]:
        n = n or self.config.n
        self.last_error = ""
        self.prepare(container)

        work = f"/tmp/repogen/pert/{instance_id}"
        out_dir = f"{work}/variants"
        backup = f"{work}/original_testcase.py"
        container.exec(f"rm -rf {shlex.quote(work)} && mkdir -p {shlex.quote(out_dir)}")
        container.write_file(backup, original_source)

        # Stage the instance where the harness stages it, so the agent can run
        # the REAL pytest node id instead of a detached copy under /tmp. A bare
        # container has no qa tree and no conftest, so without this the verify
        # step the prompt asks for would simply fail.
        qa_root = f"{workdir}/{qa_dir_name}"
        container_instance = f"{qa_root}/{instance_id}"
        container.exec(f"mkdir -p {shlex.quote(qa_root)}")
        container.exec(f"rm -rf {shlex.quote(container_instance)}")
        container.cp_to(instance_dir, container_instance)
        if shared_dir is not None and shared_dir.is_dir():
            container.exec(f"rm -rf {shlex.quote(qa_root)}/shared")
            container.cp_to(shared_dir, f"{qa_root}/shared")
        staged_test = f"{container_instance}/files/testcase.py"
        trace_log = f"{workdir}/logs/{qa_dir_name}/{instance_id}/trace.log"

        abs_trace = (
            f"{workdir}/{trace_file}" if trace_file and not trace_file.startswith("/")
            else (trace_file or "(not set)")
        )
        prompt = _PROMPT.format(
            workdir=workdir,
            instance_dir=container_instance,
            staged_test=staged_test,
            original_backup=backup,
            test_id=test_id or f"{qa_dir_name}/{instance_id}/files/testcase.py",
            abs_trace_file=abs_trace,
            trace_func=", ".join(trace_funcs) or "(not set)",
            question=(question or "").strip()[:4000],
            n=n,
            out_dir=out_dir,
            trace_log=trace_log,
            baseline_events=baseline_events,
            baseline_distinct_lines=baseline_distinct_lines,
            complexity_context=complexity_context,
            structure_policy=(
                "Change ONLY concrete input values and preserve imports, definitions, "
                "statements, calls, and assertions exactly."
                if self.config.enforce_structure else
                "REQUIRED INPUT-ONLY EDIT: change concrete data inputs already used "
                "by the test—literal values, collection contents and sizes, nested "
                "structures, constructor data, and keyword argument values. Do NOT "
                "add/remove imports, definitions, statements, calls, assertions, "
                "loops, or helper code. Hardness must come from the inputs."
            ),
        )
        prompt_path = f"/tmp/repogen/pert_{instance_id}.md"
        container.write_file(prompt_path, prompt)

        host_log_dir.mkdir(parents=True, exist_ok=True)
        result = self.backend.run_task(
            container=container,
            prompt_container_path=prompt_path,
            workspace=workdir,
            host_log_dir=host_log_dir,
            tag=f"pert_{instance_id}",
            timeout_s=self.config.timeout_s,
        )
        if not result.ok:
            self.last_error = f"agent exit={result.exit_code} {result.note}".strip()
            self._t(f"[perturb-agent] {instance_id}: {self.last_error}")

        # The agent was told to restore the staged test; do it ourselves too, so
        # a stray edit cannot leak into the next instance sharing this container.
        container.exec(f"cp {shlex.quote(backup)} {shlex.quote(staged_test)} || true")
        return self._collect(container, out_dir, host_log_dir, original_source, n)

    def _collect(
        self, container: Container, out_dir: str, host_log_dir: Path,
        original_source: str, n: int,
    ) -> List[str]:
        """Pull variant_*.py back and keep valid candidates."""
        listing = container.exec(f"ls -1 {shlex.quote(out_dir)} 2>/dev/null || true")
        names = [
            line.strip()
            for line in (getattr(listing, "stdout", "") or str(listing)).splitlines()
            if line.strip().endswith(".py")
        ]
        if not names:
            if not self.last_error:
                self.last_error = "agent wrote no variant files"
            self._t(f"[perturb-agent] {self.last_error}")
            return []

        staged = host_log_dir / "variants"
        staged.mkdir(parents=True, exist_ok=True)
        out: List[str] = []
        seen: set = set()
        for name in sorted(names):
            host_path = staged / name
            if not container.cp_from(f"{out_dir}/{name}", host_path):
                continue
            try:
                src = strip_code_fences(host_path.read_text(encoding="utf-8"))
            except OSError:
                continue
            if not src or src in seen or src.strip() == original_source.strip():
                continue
            if self.config.enforce_structure:
                ok, why = structure_preserved(original_source, src)
                if not ok:
                    self._t(f"[perturb-agent] dropped {name}: {why}")
                    continue
            else:
                try:
                    compile(src, name, "exec")
                except SyntaxError as exc:
                    self._t(f"[perturb-agent] dropped {name}: invalid Python: {exc}")
                    continue
            seen.add(src)
            out.append(src)
            if len(out) >= n:
                break
        self._t(f"[perturb-agent] kept {len(out)}/{len(names)} variant file(s)")
        return out
