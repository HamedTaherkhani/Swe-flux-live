"""Evidence coverage: did a solver read the code the test actually executed?

The harvested trace covers only the target function, and solvers almost always
read that, so coverage measured against it cannot separate right answers from
wrong ones. This module re-runs each instance once with a whole-repository
tracer (payload/evidence_plugin.py) and measures coverage against everything
the target's execution reached, by call distance from the target:

  target     the traced target function(s)
  direct     repository functions the target calls
  deeper     functions those call, at any further depth
  upstream   repository code the test runs outside the target (not required)

Harvesting runs containers but calls no model and never changes an instance.
"""

from __future__ import annotations

import ast
import builtins
import datetime as _dt
import json
import keyword
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .docker_env import Container, DockerError
from .scoring import score_answer

SCHEMA_VERSION = 1
PAYLOAD = Path(__file__).resolve().parent / "payload" / "evidence_plugin.py"
NON_INSTANCE_DIRS = {"shared", "qa_artifacts"}
CLASSES = ("target", "direct", "deeper")
UPSTREAM = -1
# An entry counts as read when this share of its code lines was shown to the
# solver: a missed decorator or closing line is not a missed function.
ENTRY_READ_SHARE = 0.9
# A short assignment to a name the testcase itself assigns is a value the
# solver can take from the testcase, so it cannot be essential reading. A
# testcase that only reads the name does not reveal the value.
GUESSABLE_MAX_LINES = 3
GUESSABLE_ROLES = ("data", "configuration")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_COMMON_NAMES = set(keyword.kwlist) | set(dir(builtins)) | {"self", "cls"}
_ASSIGNED_RE = re.compile(r"^\s*(?:self\.)?([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=(?!=)")

_TEST_ID_RE = re.compile(r'^\s*TEST_ID="([^"]+)"', re.MULTILINE)
_READ_RE = re.compile(r"^\[tool\] result read_file ok=True path=(\S+) lines=(\d+)-(\d+)")
_CALL_RE = re.compile(r"^\[tool\] call (\w+)")
_REPO_MAP_RE = re.compile(r"^\[tool\] send_to_llm get_repo_map result=(\{.*\})\s*$")
_TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ )?(\S+?):(\d+) \S+ event=line"
)

Location = Tuple[str, int]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def evidence_path(run_dir: Path, instance_id: str) -> Path:
    return run_dir / "evidence" / f"{instance_id}.json"


def instance_dirs(run_dir: Path) -> List[Path]:
    root = run_dir / "instances"
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_dir() and p.name not in NON_INSTANCE_DIRS and (p / "oracle.json").is_file()
    )


# --------------------------------------------------------------------------
# Harvest
# --------------------------------------------------------------------------


def resolve_image(run_dir: Path, repos_file: Optional[Path] = None) -> Tuple[str, str]:
    """Return (image, workdir). repositories.json wins over the image recorded
    at generation time, which may name a registry the image has since left."""
    config = _read_json(run_dir / "run_config.json") or {}
    image = str(config.get("image") or "")
    repos = _read_json(repos_file) if repos_file else None
    if isinstance(repos, dict) and repos.get(config.get("repo_key")):
        image = str(repos[config["repo_key"]])
    return image, str(config.get("workdir") or "/testbed")


def _qa_dir_name(instance_dir: Path) -> Optional[str]:
    try:
        text = (instance_dir / "eval.sh").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _TEST_ID_RE.search(text)
    if not match:
        return None
    first = match.group(1).split("/", 1)[0]
    return first or None


def _harvest_lines(run_dir: Path, instance_id: str, workdir: str) -> Set[Location]:
    path = run_dir / "logs" / instance_id / "harvest" / "trace.log"
    prefix = workdir.rstrip("/") + "/"
    found: Set[Location] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = _TRACE_LINE_RE.match(line)
                if match:
                    name = match.group(1)
                    if name.startswith(prefix):
                        name = name[len(prefix):]
                    found.add((name, int(match.group(2))))
    except OSError:
        pass
    return found


def harvest_instance(
    run_dir: Path,
    instance_dir: Path,
    *,
    image: str,
    workdir: str = "/testbed",
    timeout_s: int = 900,
) -> dict:
    """Run the instance's own pipeline in a fresh container with the evidence
    tracer standing in for the harvest tracer. Returns a status record and,
    on success, writes <run>/evidence/<instance>.json."""
    instance_id = instance_dir.name
    qa_name = _qa_dir_name(instance_dir)
    if qa_name is None:
        return {"instance_id": instance_id, "status": "failed", "reason": "no TEST_ID in eval.sh"}
    qa_dir = f"{workdir.rstrip('/')}/{qa_name}"
    instances_root = instance_dir.parent
    out_path = evidence_path(run_dir, instance_id)
    container_out = f"{workdir.rstrip('/')}/logs/{qa_name}/{instance_id}/evidence.json"

    with Container(image, workdir=workdir) as container:
        container.exec(f"mkdir -p '{qa_dir}'")
        for source in (instances_root / "shared", instances_root / "qa_pipeline.sh", instance_dir):
            container._host(
                ["docker", "cp", str(source), f"{container.name}:{qa_dir}/{source.name}"],
                check=True,
            )
        container.cp_to(PAYLOAD, f"{qa_dir}/shared/files/trace_plugin.py")
        # The pipeline's parser step fails because no trace.log is produced;
        # the evidence file is complete before that step runs.
        result = container.exec(
            f"chmod +x '{qa_dir}/qa_pipeline.sh' && "
            f"'{qa_dir}/qa_pipeline.sh' '{instance_id}' '{workdir}'",
            env={"EVIDENCE_OUT": container_out, "EVIDENCE_ROOT": workdir},
            timeout_s=timeout_s,
        )
        tmp_path = out_path.with_suffix(".tmp")
        if not container.cp_from(container_out, tmp_path):
            tail = (result.stdout + "\n" + result.stderr).strip()[-600:]
            return {"instance_id": instance_id, "status": "failed",
                    "reason": f"no evidence produced (exit {result.exit_code})", "output": tail}

    evidence = _read_json(tmp_path)
    tmp_path.unlink(missing_ok=True)
    if not isinstance(evidence, dict) or not evidence.get("files"):
        return {"instance_id": instance_id, "status": "failed", "reason": "empty evidence"}

    # Depth 0 is by construction what the harvest tracer recorded, so the two
    # line sets should coincide unless the test is not deterministic.
    harvested = _harvest_lines(run_dir, instance_id, workdir)
    target = {
        (name, line)
        for name, functions in evidence["files"].items()
        for function in functions if function["depth"] == 0
        for line in function["lines"]
    }
    union = harvested | target
    evidence.update({
        "instance_id": instance_id,
        "qa_dir": qa_name,
        "image": image,
        "harvested_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "harvest_agreement": round(len(harvested & target) / len(union), 4) if union else None,
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    return {
        "instance_id": instance_id, "status": "ok",
        "functions": sum(len(f) for f in evidence["files"].values()),
        "harvest_agreement": evidence["harvest_agreement"],
    }


def harvest_run(
    run_dir: Path,
    *,
    image: str,
    workdir: str = "/testbed",
    instance_ids: Optional[Iterable[str]] = None,
    refresh: bool = False,
    parallel: int = 1,
    timeout_s: int = 900,
    log=print,
) -> List[dict]:
    wanted = set(instance_ids or [])
    todo = [
        d for d in instance_dirs(run_dir)
        if (not wanted or d.name in wanted)
        and (refresh or not evidence_path(run_dir, d.name).is_file())
    ]
    results: List[dict] = []
    lock = threading.Lock()

    def work(instance_dir: Path) -> None:
        try:
            record = harvest_instance(
                run_dir, instance_dir, image=image, workdir=workdir, timeout_s=timeout_s
            )
        except DockerError as exc:
            record = {"instance_id": instance_dir.name, "status": "failed",
                      "reason": f"docker: {str(exc)[:300]}"}
        with lock:
            results.append(record)
            detail = (
                f"{record['functions']} functions, agreement {record['harvest_agreement']}"
                if record["status"] == "ok" else record["reason"]
            )
            log(f"[evidence][{len(results)}/{len(todo)}] {record['instance_id']}: "
                f"{record['status']} ({detail})")

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            list(pool.map(work, todo))
    return results


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


def _class_of(depth: int) -> str:
    if depth == 0:
        return "target"
    if depth == 1:
        return "direct"
    return "deeper" if depth > 1 else "upstream"


def required_evidence(evidence: dict) -> Dict[str, List[dict]]:
    """Group executed repository functions by class. Instance files (the
    testcase) are left out: they are given to the solver, not discovered."""
    qa_prefix = f"{evidence.get('qa_dir', '')}/"
    groups: Dict[str, List[dict]] = defaultdict(list)
    for name, functions in evidence["files"].items():
        if evidence.get("qa_dir") and name.startswith(qa_prefix):
            continue
        for function in functions:
            groups[_class_of(function["depth"])].append(
                {"file": name, "function": function["function"],
                 "first_line": function["first_line"], "lines": function["lines"]}
            )
    return groups


def read_ranges(trace_log: Path) -> Tuple[Dict[str, Set[int]], int]:
    """Lines a solver was actually given, per path, and its tool-call count.
    Ranges are the ones returned after the per-call line cap, not requested."""
    seen: Dict[str, Set[int]] = defaultdict(set)
    calls = 0
    try:
        with trace_log.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if _CALL_RE.match(line):
                    calls += 1
                    continue
                match = _READ_RE.match(line)
                if match:
                    seen[match.group(1).lstrip("./")].update(
                        range(int(match.group(2)), int(match.group(3)) + 1)
                    )
    except OSError:
        pass
    return seen, calls


class SourceIndex:
    """Repository source as the solver saw it (the run's snapshot)."""

    def __init__(self, run_dir: Path):
        root = run_dir / ".llm_repo_snapshot"
        self._roots = sorted(p for p in root.glob("*") if p.is_dir()) if root.is_dir() else []
        self._text: Dict[str, Optional[List[str]]] = {}
        self._code: Dict[str, Optional[Set[int]]] = {}

    def lines(self, file: str) -> Optional[List[str]]:
        if file not in self._text:
            self._text[file] = None
            for root in self._roots:
                candidate = root / file
                if candidate.is_file():
                    self._text[file] = candidate.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    break
        return self._text[file]

    def code_lines(self, file: str) -> Optional[Set[int]]:
        """Lines that carry code: not blank, not comment-only, not docstring.
        Reading a function does not depend on having been shown its prose."""
        if file not in self._code:
            text = self.lines(file)
            if text is None:
                self._code[file] = None
                return None
            keep = {
                number for number, line in enumerate(text, start=1)
                if line.strip() and not line.strip().startswith("#")
            }
            try:
                tree = ast.parse("\n".join(text))
            except (SyntaxError, ValueError):
                tree = None
            for node in ast.walk(tree) if tree is not None else []:
                body = getattr(node, "body", None)
                if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                         ast.AsyncFunctionDef)) or not body:
                    continue
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                        and isinstance(first.value.value, str):
                    keep -= set(range(first.lineno, (first.end_lineno or first.lineno) + 1))
            self._code[file] = keep
        return self._code[file]


def testcase_names(instance_dir: Path) -> Set[str]:
    """Names the files given to the solver assign a value to, as a variable
    (`limit = 3`) or as an attribute (`option.limit = 3`)."""
    names: Set[str] = set()
    files = instance_dir / "files"
    for path in sorted(files.rglob("*.py")) if files.is_dir() else []:
        if path.name.startswith("parse") or "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            else:
                continue
            for target in targets:
                for item in ast.walk(target):
                    if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
                        names.add(item.id)
                    elif isinstance(item, ast.Attribute) and isinstance(item.ctx, ast.Store):
                        names.add(item.attr)
    return names - _COMMON_NAMES


def apply_guessable_rule(required: dict, source: SourceIndex, given: Set[str]) -> dict:
    """Return the result with short, guessable definitions marked supporting.
    The agent's own choice is kept in `necessity_agent`, and the rule always
    starts from it, so applying the rule twice changes nothing."""
    entries = []
    for item in required.get("required", []):
        item = dict(item)
        chosen = item.get("necessity_agent") or item.get("necessity", "essential")
        item["necessity"] = chosen
        item.pop("necessity_agent", None)
        item.pop("downgraded", None)
        lines = source.lines(item["file"])
        short = item["end_line"] - item["start_line"] + 1 <= GUESSABLE_MAX_LINES
        if chosen == "essential" and short and item.get("role") in GUESSABLE_ROLES and lines:
            # Only the name being assigned counts: sharing an incidental
            # word such as `args` says nothing about the value.
            assigned = {
                match.group(1)
                for match in map(_ASSIGNED_RE.match, lines[item["start_line"] - 1:item["end_line"]])
                if match
            }
            shared = sorted((assigned - _COMMON_NAMES) & given)
            if shared:
                item["necessity"] = "supporting"
                item["necessity_agent"] = chosen
                item["downgraded"] = (
                    "short assignment to a name the testcase also assigns: "
                    + ", ".join(shared[:4])
                )
        entries.append(item)
    return {**required, "required": entries}


def repo_map_lines(trace_log: Path, source: SourceIndex) -> Dict[str, Set[int]]:
    """Source lines the repo map showed the solver. The map prints code lines
    without numbers, so each is located in its file, in file order. Logs
    written before the map was stored in full cannot be parsed and give none."""
    shown: Dict[str, Set[int]] = defaultdict(set)
    try:
        text = trace_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return shown
    for raw in text.splitlines():
        match = _REPO_MAP_RE.match(raw)
        if not match:
            continue
        try:
            repo_map = json.loads(match.group(1)).get("repo_map")
        except json.JSONDecodeError:
            continue
        if not isinstance(repo_map, str):
            continue
        file: Optional[str] = None
        lines: Optional[List[str]] = None
        cursor = 0
        for entry in repo_map.splitlines():
            if entry.startswith("│"):
                if lines is None or file is None:
                    continue
                wanted = entry[1:].rstrip()
                if not wanted.strip():
                    continue
                for index in range(cursor, len(lines)):
                    if lines[index].rstrip() == wanted:
                        shown[file].add(index + 1)
                        cursor = index + 1
                        break
            elif entry.endswith(":") and not entry.startswith("⋮"):
                file = entry[:-1].strip()
                lines = source.lines(file)
                cursor = 0
    return shown


def _lines_seen(seen: Dict[str, Set[int]], file: str) -> Set[int]:
    found: Set[int] = set()
    for path, lines in seen.items():
        if path == file or file.endswith("/" + path) or path.endswith("/" + file):
            found |= lines
    return found


def score_coverage(evidence: dict, seen: Dict[str, Set[int]]) -> dict:
    groups = required_evidence(evidence)
    out: Dict[str, Any] = {"classes": {}}
    required_lines = required_hit = required_functions = required_read = 0
    executed: Dict[str, Set[int]] = defaultdict(set)
    for name, functions in groups.items():
        lines = hit = read = 0
        for function in functions:
            got = _lines_seen(seen, function["file"])
            wanted = set(function["lines"])
            executed[function["file"]] |= wanted
            lines += len(wanted)
            hit += len(wanted & got)
            read += wanted <= got
        out["classes"][name] = {
            "functions": len(functions),
            "functions_read": read,
            "lines": lines,
            "lines_read": hit,
            "recall": round(hit / lines, 4) if lines else None,
        }
        if name in CLASSES:
            required_lines += lines
            required_hit += hit
            required_functions += len(functions)
            required_read += read

    # Precision over repository source only: reading the given testcase is
    # neither evidence found nor effort wasted.
    qa_prefix = f"{evidence.get('qa_dir', '')}/"
    source_read = useful = 0
    for path, lines in seen.items():
        if path.startswith("files/") or path.startswith(qa_prefix):
            continue
        source_read += len(lines)
        for file, wanted in executed.items():
            if path == file or file.endswith("/" + path) or path.endswith("/" + file):
                useful += len(lines & wanted)
                break
    out.update({
        "recall": round(required_hit / required_lines, 4) if required_lines else None,
        "function_recall": round(required_read / required_functions, 4)
        if required_functions else None,
        "sufficient": required_functions > 0 and required_read == required_functions,
        "precision": round(useful / source_read, 4) if source_read else None,
        "required_functions": required_functions,
        "required_lines": required_lines,
        "source_lines_read": source_read,
    })
    return out


def score_required(
    required: dict, seen: Dict[str, Set[int]], source: Optional[SourceIndex] = None
) -> dict:
    """Coverage of the code an agent judged necessary for the answer
    (repogen/required_code.py), as opposed to everything the target reached.
    With `source`, only lines that carry code are counted."""
    total = hit = entries_read = 0
    essential = essential_hit = essential_entries = essential_read = 0
    for item in required.get("required", []):
        wanted = set(range(item["start_line"], item["end_line"] + 1))
        code = source.code_lines(item["file"]) if source is not None else None
        if code is not None and wanted & code:
            wanted &= code
        got = wanted & _lines_seen(seen, item["file"])
        read = len(got) >= ENTRY_READ_SHARE * len(wanted)
        total += len(wanted)
        hit += len(got)
        entries_read += read
        if item.get("necessity", "essential") == "essential":
            essential += len(wanted)
            essential_hit += len(got)
            essential_entries += 1
            essential_read += read
    entries = len(required.get("required", []))
    return {
        "entries": entries,
        "entries_read": entries_read,
        "lines": total,
        "lines_read": hit,
        "recall": round(hit / total, 4) if total else None,
        "complete": entries > 0 and entries_read == entries,
        "essential_recall": round(essential_hit / essential, 4) if essential else None,
        "essential_complete": essential_entries > 0 and essential_read == essential_entries,
    }


def _mean(values: List[Optional[float]]) -> Optional[float]:
    kept = [v for v in values if v is not None]
    return round(sum(kept) / len(kept), 4) if kept else None


def _summary(rows: List[dict]) -> dict:
    if not rows:
        return {"instances": 0}
    out = {
        "instances": len(rows),
        "recall": _mean([r["recall"] for r in rows]),
        "function_recall": _mean([r["function_recall"] for r in rows]),
        "sufficient_rate": round(sum(1 for r in rows if r["sufficient"]) / len(rows), 4),
        "precision": _mean([r["precision"] for r in rows]),
        "tool_calls": _mean([float(r["tool_calls"]) for r in rows]),
        "recall_by_class": {
            name: _mean([r["classes"].get(name, {}).get("recall") for r in rows])
            for name in CLASSES + ("upstream",)
        },
    }
    judged = [r["agent_required"] for r in rows if r.get("agent_required")]
    if judged:
        out["agent_required"] = {
            "instances": len(judged),
            "recall": _mean([j["recall"] for j in judged]),
            "complete_rate": round(sum(1 for j in judged if j["complete"]) / len(judged), 4),
            "essential_recall": _mean([j.get("essential_recall") for j in judged]),
            "essential_complete_rate": round(
                sum(1 for j in judged if j.get("essential_complete")) / len(judged), 4
            ),
        }
    return out


def _required_cross(rows: List[dict]) -> Optional[dict]:
    """Headline table: instances where every essential piece of required code
    was read, against answer correctness. Supporting entries are not counted."""
    judged = [r for r in rows if r.get("agent_required")]
    if not judged:
        return None
    table = {"instances": len(judged), "fully_read": 0,
             "fully_read_correct": 0, "fully_read_wrong": 0,
             "not_fully_read_correct": 0, "not_fully_read_wrong": 0, "no_answer": 0}
    for row in judged:
        full = bool(row["agent_required"]["essential_complete"])
        table["fully_read"] += full
        if row["correct"] is None:
            table["no_answer"] += 1
            continue
        key = ("fully_read" if full else "not_fully_read") + (
            "_correct" if row["correct"] else "_wrong"
        )
        table[key] += 1
    table["fully_read_rate"] = round(table["fully_read"] / len(judged), 4)
    return table


def _cross(rows: List[dict]) -> dict:
    table = {"sufficient_correct": 0, "sufficient_wrong": 0,
             "insufficient_correct": 0, "insufficient_wrong": 0}
    for row in rows:
        if row["correct"] is None:
            continue
        key = ("sufficient" if row["sufficient"] else "insufficient") + (
            "_correct" if row["correct"] else "_wrong"
        )
        table[key] += 1
    return table


def score_run(run_dir: Path, *, evaluation_scope: str = "", float_tol: float = 1e-6) -> Dict[str, List[dict]]:
    rows: Dict[str, List[dict]] = defaultdict(list)
    root = run_dir / "evaluation" / "llm"
    source = SourceIndex(run_dir)
    for instance_dir in instance_dirs(run_dir):
        evidence = _read_json(evidence_path(run_dir, instance_dir.name))
        if not isinstance(evidence, dict):
            continue
        oracle = _read_json(instance_dir / "oracle.json") or {}
        required = _read_json(run_dir / "required_code" / f"{instance_dir.name}.json")
        if not isinstance(required, dict) or required.get("status") != "ok":
            required = None
        else:
            required = apply_guessable_rule(required, source, testcase_names(instance_dir))
        for trace_log in sorted(root.glob(f"*/*/{instance_dir.name}/trace.log")):
            scope = f"{trace_log.parents[2].name}/{trace_log.parents[1].name}"
            if evaluation_scope and scope != evaluation_scope:
                continue
            seen, calls = read_ranges(trace_log)
            mapped = repo_map_lines(trace_log, source)
            for file, lines in mapped.items():
                seen[file] |= lines
            row = score_coverage(evidence, seen)
            row["repo_map_lines"] = sum(len(lines) for lines in mapped.values())
            if required is not None:
                row["agent_required"] = score_required(required, seen, source)
            answer = _read_json(trace_log.parent / "answer.json")
            correct = None
            if answer is not None and "oracle_answer" in oracle:
                correct, _ = score_answer(oracle["oracle_answer"], answer, float_tol=float_tol)
            row.update({
                "run_dir": str(run_dir),
                "instance_id": instance_dir.name,
                "category": oracle.get("question_kind", ""),
                "correct": correct,
                "tool_calls": calls,
                "harvest_agreement": evidence.get("harvest_agreement"),
            })
            rows[scope].append(row)
    return rows


def build_report(run_dirs: Iterable[Path], *, evaluation_scope: str = "", float_tol: float = 1e-6) -> dict:
    run_dirs = list(run_dirs)
    coverage = {"instances": 0, "with_evidence": 0, "low_agreement": []}
    rows_by_scope: Dict[str, List[dict]] = defaultdict(list)
    for run_dir in run_dirs:
        for instance_dir in instance_dirs(run_dir):
            coverage["instances"] += 1
            evidence = _read_json(evidence_path(run_dir, instance_dir.name))
            if not isinstance(evidence, dict):
                continue
            coverage["with_evidence"] += 1
            agreement = evidence.get("harvest_agreement")
            if agreement is not None and agreement < 0.95:
                coverage["low_agreement"].append(
                    {"run_dir": str(run_dir), "instance_id": instance_dir.name,
                     "harvest_agreement": agreement}
                )
        for scope, rows in score_run(
            run_dir, evaluation_scope=evaluation_scope, float_tol=float_tol
        ).items():
            rows_by_scope[scope].extend(rows)

    scopes = {}
    for scope, rows in sorted(rows_by_scope.items()):
        by_category: Dict[str, List[dict]] = defaultdict(list)
        for row in rows:
            by_category[row["category"] or "unknown"].append(row)
        scopes[scope] = {
            "summary": _summary(rows),
            "correct": _summary([r for r in rows if r["correct"]]),
            "wrong": _summary([r for r in rows if r["correct"] is False]),
            "sufficiency_by_correctness": _cross(rows),
            "required_code": _required_cross(rows),
            "by_category": {
                name: {**_summary(members), "sufficiency_by_correctness": _cross(members),
                       "required_code": _required_cross(members)}
                for name, members in sorted(by_category.items())
            },
            "instances": rows,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "method": "whole_repository_evidence_coverage",
        "required_classes": list(CLASSES),
        "run_dirs": [str(p) for p in run_dirs],
        "evidence": coverage,
        "scopes": scopes,
    }


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
