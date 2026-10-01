"""Required code per instance, decided once by an agent.

Evidence coverage needs to know which code a solver had to read. Call
distance from the target (repogen/evidence.py) over-approximates it: code can
execute without affecting the answer. Here an agent with full ground truth
(oracle answer, parser, testcase, harvested trace, executed-function list) and
the ability to run code decides which repository code the answer depends on.

The agent judges the instance, never a solver's trajectory, so the result is
independent of every evaluated model and coverage against it stays a
deterministic computation. One instance is one fresh container and one fresh
agent session.
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .agents import create_backend
from .docker_env import Container, DockerError
from .evidence import (
    SourceIndex,
    _qa_dir_name,
    apply_guessable_rule,
    evidence_path,
    instance_dirs,
    testcase_names,
)
from .validation.solver_agent import _detect_infra_failure

SCHEMA_VERSION = 2
DEFAULT_AGENT = "claude-code"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
ROLES = ("target", "callee", "data", "configuration", "other")
NECESSITY = ("essential", "supporting")
VERIFIED = ("executed", "trace", "read")
TOOLS = Path(__file__).resolve().parent / "payload" / "required_code_tools.py"

_PROMPT = """You are analysing one instance of a benchmark about the runtime behaviour of a Python repository. You have full access to this environment: read any file, run the test, and run any code.

Your task is to decide which repository code a person must READ in order to derive the instance's answer by reasoning alone, without executing anything. Your list becomes the reference against which solvers are measured, so both mistakes matter: a missing entry excuses a solver that skipped necessary code, and an unnecessary entry penalises a solver that was right to skip it.

Inputs
- Repository root: {workdir}
- Instance directory: {instance_dir}
  - oracle.json: the question, the answer template, and the correct answer (oracle_answer)
  - eval.sh: how the test is run and which function is traced (TRACE_FILE, TRACE_FUNC)
  - files/testcase.py: the test
  - files/parser.py: the program that turned the trace into oracle_answer
- Ground truth from real executions of this test, in {inputs_dir}:
  - trace.log: line-level trace of the traced target, with changes to local variables
  - evidence.json: every repository function the test executed and the lines that ran
- Views of that ground truth. Use these instead of parsing the files yourself:
  - python3 {tools} functions
      every executed repository function, ordered by call distance from the target
  - python3 {tools} executed FILE [START END]
      the source of FILE with each executed line marked
  - python3 {tools} trace
      calls, exceptions and per-line counts of the traced target
- Re-run the test at any time: {qa_dir}/qa_pipeline.sh {instance_id} {workdir}

What counts as required
A piece of code is required if its behaviour determines any part of oracle_answer, and a reader could not know that behaviour from the question text and the testcase alone:
- the traced target, as far as it executes;
- a called function whose return value, side effect, or raised exception changes the path, the counts, or the values in the answer;
- code that runs before the target and decides what the target receives: how often it is called and with which arguments;
- a definition the answer depends on: a constant, a default, a class attribute, an inheritance relation, a decorator or wrapper.

Judge against the answer, not against each call
The answer is usually an aggregate over many calls: a set of distinct items, a total, a maximum. Code matters only if the answer itself would differ. Apply this test to every candidate:
  "Suppose the solver never reads this code and assumes the most natural behaviour suggested by its name, its call site, and the values in the testcase. Would the solver's answer differ from oracle_answer?"
- If no, the code is not essential. Example: the answer is the set of distinct def-use pairs, and the testcase drives both sides of a branch. The solver needs to see that both sides run, which the target and the testcase show. It does not need the callee that decides which call takes which side.
- If yes, name the part of the answer that would be wrong.

What is not required
- The testcase and other instance files. They are given to the solver.
- A value the testcase sets or passes explicitly, even when the repository also defines it.
- Code outside the repository: the standard library and installed packages.
- Code that executes but does not affect the answer, such as logging, output, caching, or a helper whose result the answer never uses.
- A called function whose effect on the answer is fully evident at the call site from its name and the values in the testcase.

Two levels of necessity
- essential: without reading it, a careful reader cannot derive some part of the answer.
- supporting: the answer can be derived without it, but reading it is what rules out a plausible wrong assumption, for example that a call might raise or change a value.
When you cannot decide between supporting and not required, leave it out and name it under "excluded".

How to work
1. Read oracle.json and eval.sh. Then read files/parser.py in full: it defines exactly which events, lines and variables enter the answer, and therefore what the answer can depend on.
2. Run the functions view and the trace view. Read the testcase and the target with the executed view.
3. Go through the executed functions. For each one that could matter, decide whether the answer depends on it. Base the decision on what executed, not on what the code could do in general.
4. Verify what you are unsure about by running code: re-run the test, or import the repository in a short script and call the function with the values from the testcase. Reading alone is not verification for an entry you mark essential and are not certain about.
5. Choose line ranges with the executed view open:
   - one entry per function, or per contiguous part of a function;
   - start at the def line, not at a decorator above it, unless the decorator changes behaviour the answer depends on;
   - the signature belongs to its function's entry; never make a separate entry for a signature, a decorator, or a docstring;
   - when a function has a block of about 15 or more lines that did not execute, end the entry before the block and start another after it; keep the line of the condition that skipped the block, because the reader must see why it was skipped;
   - code that matters although it never executes, such as a constant or a class statement, is a separate entry with role data or configuration. Mark it essential only if the answer test above says yes and the testcase does not already give the value.
6. Write the output file, then run: python3 {tools} check {output}
   Fix every ERROR. For each WARNING either change the entry or explain in "notes" why it stands.

Rules
- Do not modify files under {instance_dir} or the repository source. Put scratch files in /tmp.
- Line numbers refer to the files as they are now in {workdir}. Paths are relative to {workdir}.
- Do not ask for confirmation.

Output
Write exactly one JSON object to {output} and nothing else to that file:
{{
  "required": [
    {{
      "file": "path/relative/to/repository/root.py",
      "function": "QualifiedName.of_function, or empty for module-level code",
      "start_line": 1,
      "end_line": 1,
      "role": "target | callee | data | configuration | other",
      "necessity": "essential | supporting",
      "verified": "executed | trace | read",
      "reason": "one sentence naming the part of the answer that depends on this code"
    }}
  ],
  "excluded": [
    {{"file": "path.py", "function": "name", "reason": "one sentence: why this executed code is not required"}}
  ],
  "confidence": "high | medium | low",
  "notes": "what a reviewer should know, including unresolved warnings, or empty"
}}
- role: callee is code the target calls, directly or indirectly. Use other for code that runs before or around the target.
- necessity: decided by the answer test above, not by whether the code ran.
- verified: executed if you ran code to confirm the dependency, trace if trace.log or the views show it, read if you only read the source.
- excluded: executed functions that a reader might expect to matter and that you decided against. Do not list every executed function.
"""


def required_path(run_dir: Path, instance_id: str) -> Path:
    return run_dir / "required_code" / f"{instance_id}.json"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------
# Checking the agent's output
# --------------------------------------------------------------------------


def _source_lengths(run_dir: Path) -> "callable":
    roots = sorted(p for p in (run_dir / ".llm_repo_snapshot").glob("*") if p.is_dir())
    cache: Dict[str, Optional[int]] = {}

    def length(rel: str) -> Optional[int]:
        if rel not in cache:
            cache[rel] = None
            for root in roots:
                candidate = root / rel
                if candidate.is_file():
                    with candidate.open("rb") as handle:
                        cache[rel] = sum(1 for _ in handle)
                    break
        return cache[rel]

    return length


def normalise(raw: Any, *, workdir: str, qa_dir: str, length_of=None) -> Tuple[dict, List[str]]:
    """Validate the agent's object and return (clean result, problems).
    Entries that cannot be used are dropped and named, never repaired."""
    problems: List[str] = []
    if not isinstance(raw, dict) or not isinstance(raw.get("required"), list):
        return {"required": []}, ["output is not an object with a 'required' list"]

    prefix = workdir.rstrip("/") + "/"
    kept: List[dict] = []
    for index, item in enumerate(raw["required"]):
        where = f"required[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: not an object")
            continue
        file = str(item.get("file") or "").replace("\\", "/")
        if file.startswith(prefix):
            file = file[len(prefix):]
        file = file.lstrip("./")
        start, end = item.get("start_line"), item.get("end_line")
        if not file or not isinstance(start, int) or not isinstance(end, int) \
                or isinstance(start, bool) or isinstance(end, bool):
            problems.append(f"{where}: needs file, start_line and end_line")
            continue
        if start < 1 or end < start:
            problems.append(f"{where}: invalid range {start}-{end}")
            continue
        if qa_dir and file.startswith(f"{qa_dir}/"):
            problems.append(f"{where}: instance file is given to the solver ({file})")
            continue
        if length_of is not None:
            total = length_of(file)
            if total is None:
                problems.append(f"{where}: file not in the repository ({file})")
                continue
            if start > total:
                problems.append(f"{where}: range {start}-{end} is past the end of {file}")
                continue
            if end > total:
                problems.append(f"{where}: end_line {end} clipped to {total}")
                end = total
        role = str(item.get("role") or "other").strip().lower()
        # Results written before the two levels existed count as essential.
        necessity = str(item.get("necessity") or "essential").strip().lower()
        verified = str(item.get("verified") or "").strip().lower()
        kept.append({
            "file": file,
            "function": str(item.get("function") or ""),
            "start_line": start,
            "end_line": end,
            "role": role if role in ROLES else "other",
            "necessity": necessity if necessity in NECESSITY else "essential",
            "verified": verified if verified in VERIFIED else "",
            "reason": str(item.get("reason") or ""),
        })

    excluded = [
        {"file": str(e.get("file") or ""), "function": str(e.get("function") or ""),
         "reason": str(e.get("reason") or "")}
        for e in raw.get("excluded") or [] if isinstance(e, dict)
    ]
    confidence = str(raw.get("confidence") or "").strip().lower()
    return {
        "required": kept,
        "excluded": excluded,
        "confidence": confidence if confidence in ("high", "medium", "low") else "",
        "notes": str(raw.get("notes") or ""),
    }, problems


def required_lines(result: dict, *, essential_only: bool = False) -> Dict[str, Set[int]]:
    lines: Dict[str, Set[int]] = {}
    for item in result.get("required", []):
        if essential_only and item.get("necessity", "essential") != "essential":
            continue
        lines.setdefault(item["file"], set()).update(
            range(item["start_line"], item["end_line"] + 1)
        )
    return lines


def _executed(evidence: Optional[dict]) -> Tuple[Dict[str, Set[int]], Dict[str, Set[int]]]:
    """Executed lines per file: (everything, target-reachable only)."""
    everything: Dict[str, Set[int]] = {}
    reachable: Dict[str, Set[int]] = {}
    for file, functions in ((evidence or {}).get("files") or {}).items():
        for function in functions:
            everything.setdefault(file, set()).update(function["lines"])
            if function["depth"] >= 0:
                reachable.setdefault(file, set()).update(function["lines"])
    return everything, reachable


def describe(result: dict, evidence: Optional[dict]) -> dict:
    """How the agent's choice relates to what executed. Required code that
    never ran is legitimate (a constant, a definition) but worth seeing."""
    lines = required_lines(result)
    total = sum(len(v) for v in lines.values())
    everything, reachable = _executed(evidence)
    ran = sum(len(v & everything.get(f, set())) for f, v in lines.items())
    reachable_total = sum(len(v) for v in reachable.values())
    kept = sum(len(v & lines.get(f, set())) for f, v in reachable.items())
    return {
        "entries": len(result.get("required", [])),
        "essential_entries": sum(
            1 for item in result.get("required", [])
            if item.get("necessity", "essential") == "essential"
        ),
        "files": len(lines),
        "lines": total,
        "essential_lines": sum(
            len(v) for v in required_lines(result, essential_only=True).values()
        ),
        "executed_lines": ran,
        "verified": {
            how: sum(1 for item in result.get("required", []) if item.get("verified") == how)
            for how in VERIFIED
            if any(item.get("verified") == how for item in result.get("required", []))
        },
        "share_of_reachable_executed_lines": round(kept / reachable_total, 4)
        if reachable_total else None,
        "roles": {
            role: sum(1 for item in result.get("required", []) if item["role"] == role)
            for role in ROLES
            if any(item["role"] == role for item in result.get("required", []))
        },
    }


# --------------------------------------------------------------------------
# One instance
# --------------------------------------------------------------------------


def analyse_instance(
    run_dir: Path,
    instance_dir: Path,
    *,
    backend,
    image: str,
    workdir: str = "/testbed",
    timeout_s: int = 1200,
    length_of=None,
) -> dict:
    instance_id = instance_dir.name
    base = {"schema_version": SCHEMA_VERSION, "instance_id": instance_id}
    qa_name = _qa_dir_name(instance_dir)
    if qa_name is None:
        return {**base, "status": "failed", "reason": "no TEST_ID in eval.sh"}
    evidence_file = evidence_path(run_dir, instance_id)
    if not evidence_file.is_file():
        return {**base, "status": "failed",
                "reason": "no evidence file; run 'repogen evidence --harvest' first"}
    trace_file = run_dir / "logs" / instance_id / "harvest" / "trace.log"

    root = workdir.rstrip("/")
    qa_dir = f"{root}/{qa_name}"
    inputs_dir = f"{root}/required_code_inputs/{instance_id}"
    output = f"{root}/required_code_output/{instance_id}.json"
    instances_root = instance_dir.parent
    log_dir = run_dir / "required_code" / "logs" / instance_id

    with Container(image, workdir=workdir) as container:
        backend.prepare(container)
        container.exec(f"mkdir -p '{qa_dir}' '{inputs_dir}' '{root}/required_code_output'")
        for source in (instances_root / "shared", instances_root / "qa_pipeline.sh", instance_dir):
            container._host(
                ["docker", "cp", str(source), f"{container.name}:{qa_dir}/{source.name}"],
                check=True,
            )
        container.exec(f"chmod +x '{qa_dir}/qa_pipeline.sh'")
        container.cp_to(evidence_file, f"{inputs_dir}/evidence.json")
        if trace_file.is_file():
            container.cp_to(trace_file, f"{inputs_dir}/trace.log")
        container.cp_to(TOOLS, f"{inputs_dir}/tools.py")
        container.write_file(
            f"{inputs_dir}/config.json",
            json.dumps({
                "root": root, "qa_dir": qa_name,
                "testcase": f"{qa_dir}/{instance_id}/files/testcase.py",
            }),
        )

        prompt = _PROMPT.format(
            workdir=root, instance_dir=f"{qa_dir}/{instance_id}", inputs_dir=inputs_dir,
            qa_dir=qa_dir, instance_id=instance_id, output=output,
            tools=f"{inputs_dir}/tools.py",
        )
        prompt_path = f"/tmp/repogen/required_code_{instance_id}.md"
        container.write_file(prompt_path, prompt)
        agent = backend.run_task(
            container=container,
            prompt_container_path=prompt_path,
            workspace=root,
            host_log_dir=log_dir,
            tag=instance_id,
            timeout_s=timeout_s,
        )
        raw_path = log_dir / "output.json"
        produced = container.cp_from(output, raw_path)

    base.update({
        "agent": backend.name,
        "model": backend.model,
        "effort": backend.settings.get("effort", ""),
        "image": image,
        "analysed_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "agent_exit_code": agent.exit_code,
    })
    if agent.note:
        base["agent_note"] = agent.note
    raw = _read_json(raw_path) if produced else None
    if raw is None:
        infra = _detect_infra_failure(log_dir)
        reason = f"agent could not run ({infra})" if infra else "agent wrote no valid JSON"
        return {**base, "status": "infra_failed" if infra else "failed", "reason": reason}

    result, problems = normalise(raw, workdir=workdir, qa_dir=qa_name, length_of=length_of)
    if not result["required"]:
        return {**base, "status": "failed", "reason": "no usable required entries",
                "problems": problems}
    result = apply_guessable_rule(result, SourceIndex(run_dir), testcase_names(instance_dir))
    return {
        **base,
        "status": "ok",
        **result,
        "problems": problems,
        "summary": describe(result, _read_json(evidence_file)),
    }


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------


def analyse_run(
    run_dir: Path,
    *,
    image: str,
    workdir: str = "/testbed",
    agent: str = DEFAULT_AGENT,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    instance_ids: Optional[Iterable[str]] = None,
    limit: int = 0,
    refresh: bool = False,
    parallel: int = 1,
    timeout_s: int = 1200,
    log=print,
) -> List[dict]:
    """Analyse every instance that has no result yet. Results are written as
    each instance finishes, so an interrupted run resumes where it stopped."""
    wanted = set(instance_ids or [])
    todo = []
    for instance_dir in instance_dirs(run_dir):
        if wanted and instance_dir.name not in wanted:
            continue
        existing = _read_json(required_path(run_dir, instance_dir.name))
        if not refresh and isinstance(existing, dict) and existing.get("status") == "ok":
            continue
        todo.append(instance_dir)
    if limit > 0:
        todo = todo[:limit]
    if not todo:
        return []

    backend = create_backend(agent, model, {"effort": effort} if effort else {})
    length_of = _source_lengths(run_dir)
    results: List[dict] = []
    lock = threading.Lock()
    # A provider refusal (usage limit, auth) will repeat for every instance:
    # stop handing out work instead of recording hundreds of failures.
    halted = threading.Event()

    def work(instance_dir: Path) -> None:
        if halted.is_set():
            return
        try:
            record = analyse_instance(
                run_dir, instance_dir, backend=backend, image=image, workdir=workdir,
                timeout_s=timeout_s, length_of=length_of,
            )
        except (DockerError, RuntimeError) as exc:
            record = {"schema_version": SCHEMA_VERSION, "instance_id": instance_dir.name,
                      "status": "failed", "reason": f"{type(exc).__name__}: {str(exc)[:300]}"}
        if record["status"] == "infra_failed":
            halted.set()
        else:
            path = required_path(run_dir, instance_dir.name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        with lock:
            results.append(record)
            if record["status"] == "ok":
                summary = record["summary"]
                detail = (f"{summary['entries']} entries, {summary['lines']} lines, "
                          f"confidence {record['confidence'] or 'n/a'}")
            else:
                detail = record["reason"]
            log(f"[required-code][{len(results)}/{len(todo)}] {record['instance_id']}: "
                f"{record['status']} ({detail})")

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        list(pool.map(work, todo))
    if halted.is_set():
        log("[required-code] stopped early: the provider refused requests; "
            "rerun the same command to continue with the remaining instances")
    return results


def summarise(run_dirs: Iterable[Path]) -> dict:
    total = ok = 0
    failed: List[dict] = []
    confidence: Dict[str, int] = {}
    lines: List[int] = []
    shares: List[float] = []
    for run_dir in run_dirs:
        for instance_dir in instance_dirs(run_dir):
            total += 1
            record = _read_json(required_path(run_dir, instance_dir.name))
            if not isinstance(record, dict):
                continue
            if record.get("status") != "ok":
                failed.append({"run_dir": str(run_dir), "instance_id": instance_dir.name,
                               "reason": record.get("reason", "")})
                continue
            ok += 1
            key = record.get("confidence") or "unstated"
            confidence[key] = confidence.get(key, 0) + 1
            lines.append(record["summary"]["lines"])
            share = record["summary"].get("share_of_reachable_executed_lines")
            if share is not None:
                shares.append(share)
    lines.sort()
    return {
        "instances": total,
        "analysed": ok,
        "failed": failed,
        "confidence": confidence,
        "median_required_lines": lines[len(lines) // 2] if lines else None,
        "mean_share_of_reachable_executed_lines": round(sum(shares) / len(shares), 4)
        if shares else None,
    }
