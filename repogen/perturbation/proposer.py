"""LLM proposer for harder executable test variants.

By default the model may change test setup and calls while preserving the runtime
question and traced target. An opt-in AST policy limits changes to input-only,
structure-preserving rewrites. The model gets read-only repository tools so it
can inspect the behavior under test before proposing a variant.

The LLM is ONLY a proposer. Every variant is harvested and screened exactly like
a normal instance, so an invalid or degenerate proposal is dropped by execution,
not by trusting the model.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..llm_eval.provider_runner import ProviderRunner
from ..llm_eval.repo_tools import ReadOnlyRepoTools, shrink_tool_payload_for_llm

VARIANT_SEPARATOR = "===PERTURBATION==="

_SYSTEM_PROMPT = """\
You generate perturbed variants of a Python pytest test, to build *harder* \
runtime-behaviour questions for evaluating code-reasoning models. Hardness is \
defined by an intrinsic combined-complexity score. Downstream evaluation \
outcomes are not provided and must not be optimized.

Editing policy:
{structure_policy}

Hard rules:
1. Every variant must be VALID, RUNNABLE Python that executes the behavior \
under test without raising unrelated errors (avoid out-of-domain values \
that crash: month=13, negative sizes, mismatched shapes, indices out of range).
2. Maximize the SAME three dimensions that the pipeline measures:
   - SEMANTIC REASONING (40%): raise the diagnosed control-flow, state-tracking, \
interprocedural, exception-semantics, and execution-workload submetrics. Use \
valid inputs that create more executed branch alternatives, changed-state \
events, call depth, distinct lines, and meaningful state-varying repetition. \
Unexecuted static complexity and one identical repeated path are weak.
   - ANSWER CONSTRUCTION (35%): make the harvested answer contain more leaves, \
more ordered elements, deeper useful structure where the fixed schema permits, \
and exact values with meaningful precision. For counting/history questions, \
increase and vary the events that appear in the answer rather than merely making \
one scalar large.
   - REPOSITORY NAVIGATION (25%): through DATA values, raise the actionable \
executed-code-footprint submetric by activating indirect dispatch, callbacks, \
helpers, and DISTINCT EXECUTED SOURCE LINES. Do not game inverse support \
submetrics by deleting imports, paths, symbols, or question clues.
   ALL THREE dimension scores must increase. Do not trade away one metric for \
an improvement in the combined average.
3. Inspect the implementation and choose values around real branch thresholds: \
below/at/above comparisons, empty/non-empty, zero/sign changes, boundary lengths, \
heterogeneous collections, and inputs that make different iterations take \
different paths. The new execution must remain valid and reach the traced target.
4. The candidate is re-harvested and scored after generation. It is kept only \
if its combined score increases and reaches the requested frozen difficulty bin.
5. Follow the scorecard's PRIORITY ORDER. For every metric, use its listed \
submetric values and next-bin boundary to choose a concrete repository behavior \
that harder inputs can activate. Focus on the easiest metric first without \
regressing the others.

Input-hardening strategy: replace small/homogeneous inputs with larger, \
heterogeneous valid data; use values below/at/above actual branch thresholds; \
combine valid empty/non-empty, zero/sign, duplicate/unique, boundary-length and \
nested cases; and make different elements follow different paths. More iterations \
on one identical path are insufficient. Do not inflate metrics with test code.

Use the read-only tools (get_repo_map, list_dir, read_file) to inspect the \
function under test before deciding on inputs.

Output format: emit exactly {n} complete perturbed test files, each the FULL file \
content, separated by a line containing only:
{sep}
No explanations, no markdown fences -- only file contents and separators.
"""

_USER_PROMPT = """\
Target test file (relative path): {test_path}
Function(s) under test (from the harness trace config):
  TRACE_FILE: {trace_file}
  TRACE_FUNC: {trace_func}

The question this instance asks (the answer is harvested by executing the test, \
so you do not need to answer it -- only to change what the execution does):
{question}

Intrinsic complexity scorecard and target:
{complexity_context}

Original execution footprint:
{trace_stats}

Produce exactly {n} perturbed variants of the test below, following all rules. \
Optimize the weakest measurable dimensions in the scorecard and reach its \
requested combined-difficulty target.

----- ORIGINAL TEST FILE -----
{source}
----- END ORIGINAL TEST FILE -----
"""

_FINAL_VARIANTS_PROMPT = """\
Tool phase is closed. Return ONLY the requested complete Python test file \
variant(s), separated by the required separator line if more than one was \
requested. No JSON, no markdown fences, no explanations.
"""


@dataclass
class ProposerConfig:
    provider: str = "openai"
    model: str = "gpt-5.6-sol"
    temperature: float = 1.0
    reasoning_effort: str = ""
    n: int = 5
    max_read_lines: int = 300
    repo_map_mode: str = "repomap"
    enforce_structure: bool = False


def strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_]*\n", "", t)
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def definition_signatures(tree: ast.AST) -> tuple:
    """(kind, name, arg-names) for every def/class, in source order."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = tuple(a.arg for a in node.args.args)
            out.append(("def", node.name, args))
        elif isinstance(node, ast.ClassDef):
            out.append(("class", node.name, ()))
    return tuple(sorted(out))


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def call_names(tree: ast.AST) -> tuple:
    return tuple(
        _call_name(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)
    )


def structure_preserved(original: str, candidate: str) -> tuple[bool, str]:
    """Reject a variant that renamed/added/removed defs or changed the calls.

    This is the cheap structural check the harvest cannot make for us: a variant
    that quietly drops a test method would still harvest fine, but would no
    longer be the same question.
    """
    try:
        a, b = ast.parse(original), ast.parse(candidate)
    except SyntaxError as exc:
        return False, f"invalid Python: {exc}"
    if definition_signatures(a) != definition_signatures(b):
        return False, "class/def signatures changed"
    if sorted(call_names(a)) != sorted(call_names(b)):
        return False, "call set changed"
    return True, ""


class LLMProposer:
    """Generates N perturbed test sources under the configured edit policy."""

    def __init__(self, config: ProposerConfig, trace: Optional[Callable[[str], None]] = None) -> None:
        self.config = config
        self.trace = trace
        self.last_error = ""

    def _t(self, msg: str) -> None:
        if self.trace:
            self.trace(msg)

    def _tool_callback(self, tools: ReadOnlyRepoTools) -> Callable[[str, Dict], Dict]:
        def callback(name: str, args: Dict) -> Dict:
            if name == "get_repo_map":
                res = tools.get_repo_map(focus_paths=args.get("focus_paths"))
            elif name == "list_dir":
                res = tools.list_dir(path=args.get("path", "."), max_entries=args.get("max_entries", 200))
            elif name == "read_file":
                res = tools.read_file(
                    path=args.get("path", ""),
                    start_line=args.get("start_line", 1),
                    end_line=args.get("end_line", 250),
                )
            else:
                return {"ok": False, "error": f"unknown tool: {name}"}
            return shrink_tool_payload_for_llm(name, {"ok": res.ok, **res.payload})

        return callback

    def propose(
        self,
        *,
        original_source: str,
        test_rel_path: str,
        trace_file: str,
        trace_funcs: List[str],
        question: str,
        repo_root: Path,
        instance_dir: Path,
        trace_stats: str = "(unknown)",
        complexity_context: str = "(no intrinsic scorecard available)",
        n: Optional[int] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
    ) -> List[str]:
        n = n or self.config.n
        self.last_error = ""
        try:
            tools = ReadOnlyRepoTools(
                repo_root=repo_root,
                instance_dir=instance_dir,
                max_read_lines=self.config.max_read_lines,
                repo_map_mode=self.config.repo_map_mode,
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"repo tools unavailable: {exc}"
            self._t(f"[perturb] {self.last_error}")
            return []

        runner = ProviderRunner(
            provider=self.config.provider,
            model=self.config.model,
            temperature=self.config.temperature,
            reasoning_effort=self.config.reasoning_effort,
            trace=self.trace,
            final_answer_prompt=_FINAL_VARIANTS_PROMPT,
        )
        structure_policy = (
            "Change only concrete input values and preserve imports, definitions, "
            "statements, calls, and assertions exactly."
            if self.config.enforce_structure else
            "REQUIRED INPUT-ONLY EDIT: change concrete data inputs already used by "
            "the test—literal values, collection contents and sizes, nested structures, "
            "constructor data, and keyword argument values. Do not add/remove imports, "
            "definitions, statements, calls, assertions, loops, or helper code. "
            "Hardness must come from the inputs."
        )
        sys_prompt = system_prompt or _SYSTEM_PROMPT.format(
            n=n, sep=VARIANT_SEPARATOR, structure_policy=structure_policy
        )
        usr_prompt = user_prompt or _USER_PROMPT.format(
            test_path=test_rel_path,
            trace_file=trace_file or "(not set)",
            trace_func=", ".join(trace_funcs) or "(not set)",
            question=(question or "").strip()[:4000],
            trace_stats=trace_stats,
            complexity_context=complexity_context,
            n=n,
            source=original_source,
        )
        try:
            raw = runner.run(
                system_prompt=sys_prompt,
                user_prompt=usr_prompt,
                tool_callback=self._tool_callback(tools),
                tool_names=tools.enabled_tool_names(),
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"generation failed: {exc}"
            self._t(f"[perturb] {self.last_error}")
            return []
        return self.parse_variants(raw, original_source, n)

    def parse_variants(self, raw: str, original_source: str, n: int) -> List[str]:
        """Split the response and keep valid changed sources."""
        variants: List[str] = []
        stripped = (raw or "").strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                data = json.loads(stripped)
                if isinstance(data, dict) and isinstance(data.get("variants"), list):
                    variants = [str(v) for v in data["variants"]]
                elif isinstance(data, list):
                    variants = [str(v) for v in data]
            except Exception:  # noqa: BLE001
                variants = []
        if not variants:
            variants = [p for p in (s.strip() for s in (raw or "").split(VARIANT_SEPARATOR)) if p]

        out: List[str] = []
        seen: set = set()
        for v in variants:
            src = strip_code_fences(v)
            if not src or src in seen:
                continue
            if src.strip() == original_source.strip():
                continue  # no-op proposal
            if self.config.enforce_structure:
                ok, why = structure_preserved(original_source, src)
                if not ok:
                    self._t(f"[perturb] dropped a variant: {why}")
                    continue
            else:
                try:
                    ast.parse(src)
                except SyntaxError as exc:
                    self._t(f"[perturb] dropped a variant: invalid Python: {exc}")
                    continue
            seen.add(src)
            out.append(src)
            if len(out) >= n:
                break
        self._t(f"[perturb] kept {len(out)}/{len(variants)} variants")
        return out
