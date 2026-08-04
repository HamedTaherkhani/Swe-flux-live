#!/usr/bin/env python3
"""Run read-only repository QA evaluation on host using LLM tool-calling.

This runner does not execute repository code/tests.
It runs the evaluation directly on host using local repo snapshots.

Output layout:
  <output-root>/llm/<provider>/<model>/<repo>/<instance>/answer.json
  <output-root>/llm/<provider>/<model>/<repo>/<instance>/traj.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
import math
import os
import re
import shutil
import subprocess
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

SCRIPT_DIR = Path(__file__).resolve().parent


def _find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "Repositories.json").exists() and (parent / "qa_instances_eval").exists():
            return parent
    # Fallback to expected layout: <repo>/evaluation_scripts/llm_eval/<this-file>.
    return start.parents[2]


REPO_ROOT = _find_repo_root(SCRIPT_DIR)

# ---------------------------
# Shared helpers
# ---------------------------


def sanitize_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s.strip())


def output_model_segment(provider: str, model: str) -> str:
    raw = (model or "").strip()
    if provider == "fireworks":
        lower = raw.lower()
        for prefix in ("accounts/fireworks/models/", "fireworks/"):
            if lower.startswith(prefix):
                raw = raw[len(prefix):]
                break
        # Fireworks model identifiers can still contain slashes for account-scoped names.
        if "/" in raw:
            raw = raw.split("/")[-1]
    segment = sanitize_name(raw)
    return segment or sanitize_name(model or "model")


def run_checked(cmd: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        check=True,
        text=True,
        capture_output=capture,
    )
def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def select_instances(
    repo_instances_dir: Path,
    num_instances: str,
    only_instances: Optional[Sequence[str]] = None,
) -> List[str]:
    qfiles = sorted(repo_instances_dir.glob("*/question.json"))
    instance_ids = [p.parent.name for p in qfiles]
    if only_instances:
        wanted = list(only_instances)
        available = set(instance_ids)
        missing = [iid for iid in wanted if iid not in available]
        if missing:
            raise SystemExit(
                f"Requested task instance(s) not found under {repo_instances_dir}: {', '.join(missing)}"
            )
        # Preserve the on-disk ordering while restricting to the requested ids.
        wanted_set = set(wanted)
        return [iid for iid in instance_ids if iid in wanted_set]
    if num_instances == "all":
        return instance_ids
    limit = int(num_instances)
    return instance_ids[: max(0, min(limit, len(instance_ids)))]


USAGE_NUMERIC_KEYS = [
    "requests",
    "usage_missing_requests",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
]

# Ported into repobehave-gen: the pricing DB ships alongside this module.
# Fall back to the original RepoBehave location if the package-local copy is
# ever removed, so cost lookups still work in the source tree.
_PACKAGE_MODEL_COSTS_PATH = SCRIPT_DIR / "provider_model_costs.json"
MODEL_COSTS_PATH = (
    _PACKAGE_MODEL_COSTS_PATH
    if _PACKAGE_MODEL_COSTS_PATH.exists()
    else REPO_ROOT / "evaluations" / "llm" / "provider_model_costs.json"
)
_MODEL_COSTS_CACHE: Optional[Dict[str, Any]] = None


def _to_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(float(s))
        except Exception:
            return None
    return None


def _to_float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def empty_usage(provider: str, model: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"provider": provider, "model": model}
    for key in USAGE_NUMERIC_KEYS:
        payload[key] = 0
    return payload


def merge_usage(into: Dict[str, Any], usage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(usage, dict):
        return into
    for key in USAGE_NUMERIC_KEYS:
        inc = _to_int_or_none(usage.get(key))
        if inc is None:
            continue
        into[key] = int(into.get(key, 0)) + max(0, inc)
    if int(into.get("total_tokens", 0)) <= 0:
        into["total_tokens"] = int(into.get("input_tokens", 0)) + int(into.get("output_tokens", 0))
    return into


def _compute_usage_cost_with_rates(
    *,
    usage: Dict[str, Any],
    input_cost_per_1m: Optional[float],
    output_cost_per_1m: Optional[float],
    cached_input_cost_per_1m: Optional[float],
) -> Dict[str, Any]:
    in_rate = _to_float_or_none(input_cost_per_1m)
    out_rate = _to_float_or_none(output_cost_per_1m)
    cache_rate = _to_float_or_none(cached_input_cost_per_1m)

    pricing = {
        "input_cost_per_1m": in_rate,
        "output_cost_per_1m": out_rate,
        "cached_input_cost_per_1m": cache_rate if cache_rate is not None else in_rate,
    }

    if in_rate is None or out_rate is None:
        return {
            "configured": False,
            "currency": "USD",
            "pricing": pricing,
            "cost_usd": None,
        }

    input_tokens = max(0, int(_to_int_or_none(usage.get("input_tokens")) or 0))
    output_tokens = max(0, int(_to_int_or_none(usage.get("output_tokens")) or 0))
    cached_input_tokens = max(0, int(_to_int_or_none(usage.get("cached_input_tokens")) or 0))
    cached_input_tokens = min(cached_input_tokens, input_tokens)
    uncached_input_tokens = max(0, input_tokens - cached_input_tokens)
    eff_cache_rate = in_rate if cache_rate is None else cache_rate

    input_cost = (uncached_input_tokens / 1_000_000.0) * in_rate
    cached_input_cost = (cached_input_tokens / 1_000_000.0) * eff_cache_rate
    output_cost = (output_tokens / 1_000_000.0) * out_rate
    total_cost = input_cost + cached_input_cost + output_cost

    return {
        "configured": True,
        "currency": "USD",
        "pricing": pricing,
        "billable_tokens": {
            "input_uncached": uncached_input_tokens,
            "input_cached": cached_input_tokens,
            "output": output_tokens,
        },
        "cost_breakdown_usd": {
            "input_uncached": input_cost,
            "input_cached": cached_input_cost,
            "output": output_cost,
        },
        "cost_usd": total_cost,
    }


def _model_candidates(model: str) -> List[str]:
    raw = (model or "").strip()
    if not raw:
        return []
    out: List[str] = [raw]

    # Common version/date suffixes, e.g. gpt-5.4-2026-03-05.
    m = re.match(r"^(.*)-\d{4}-\d{2}-\d{2}$", raw)
    if m:
        out.append(m.group(1))
    m2 = re.match(r"^(.*)-\d{8}$", raw)
    if m2:
        out.append(m2.group(1))

    # Common stability tags.
    if raw.endswith("-latest"):
        out.append(raw[: -len("-latest")])
    if raw.endswith("-preview"):
        out.append(raw[: -len("-preview")])

    # Deduplicate, preserve order.
    dedup: List[str] = []
    seen = set()
    for c in out:
        if c and c not in seen:
            dedup.append(c)
            seen.add(c)
    return dedup


def load_model_costs_db() -> Dict[str, Any]:
    global _MODEL_COSTS_CACHE
    if _MODEL_COSTS_CACHE is not None:
        return _MODEL_COSTS_CACHE
    if not MODEL_COSTS_PATH.exists():
        _MODEL_COSTS_CACHE = {}
        return _MODEL_COSTS_CACHE
    try:
        payload = load_json(MODEL_COSTS_PATH)
    except Exception:
        payload = {}
    _MODEL_COSTS_CACHE = payload if isinstance(payload, dict) else {}
    return _MODEL_COSTS_CACHE


def resolve_model_cost_entry(provider: str, model: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    db = load_model_costs_db()
    provider_obj = db.get(provider, {})
    if not isinstance(provider_obj, dict):
        return None, {
            "provider": provider,
            "model": model,
            "pricing_file": str(MODEL_COSTS_PATH),
            "matched": False,
            "reason": f"provider '{provider}' not found in pricing file",
        }

    model_table = provider_obj.get("models", provider_obj)
    if not isinstance(model_table, dict):
        return None, {
            "provider": provider,
            "model": model,
            "pricing_file": str(MODEL_COSTS_PATH),
            "matched": False,
            "reason": f"provider '{provider}' has invalid model table in pricing file",
        }

    aliases = provider_obj.get("aliases", {})
    if not isinstance(aliases, dict):
        aliases = {}

    candidates = _model_candidates(model)
    for cand in candidates:
        if cand in aliases:
            alias_target = str(aliases[cand])
            entry = model_table.get(alias_target)
            if isinstance(entry, dict):
                return dict(entry), {
                    "provider": provider,
                    "model": model,
                    "matched": True,
                    "matched_model": alias_target,
                    "match_type": "alias",
                    "pricing_file": str(MODEL_COSTS_PATH),
                }

    for cand in candidates:
        entry = model_table.get(cand)
        if isinstance(entry, dict):
            return dict(entry), {
                "provider": provider,
                "model": model,
                "matched": True,
                "matched_model": cand,
                "match_type": "exact",
                "pricing_file": str(MODEL_COSTS_PATH),
            }

    # Prefix fallback (supports versioned model ids that share a base name).
    keys = sorted([str(k) for k in model_table.keys()], key=len, reverse=True)
    for cand in candidates:
        for key in keys:
            if cand.startswith(key):
                entry = model_table.get(key)
                if isinstance(entry, dict):
                    return dict(entry), {
                        "provider": provider,
                        "model": model,
                        "matched": True,
                        "matched_model": key,
                        "match_type": "prefix",
                        "pricing_file": str(MODEL_COSTS_PATH),
                    }

    return None, {
        "provider": provider,
        "model": model,
        "matched": False,
        "match_type": "none",
        "pricing_file": str(MODEL_COSTS_PATH),
        "reason": f"model entry not found in cost json for provider='{provider}', model='{model}'",
    }


def compute_usage_cost_for_model(*, provider: str, model: str, usage: Dict[str, Any]) -> Dict[str, Any]:
    entry, lookup = resolve_model_cost_entry(provider, model)
    if entry is None:
        return {
            "configured": False,
            "currency": "USD",
            "cost_usd": None,
            "model_lookup": lookup,
            "reason": str(lookup.get("reason", "model entry not found in cost json")),
        }

    cost = _compute_usage_cost_with_rates(
        usage=usage,
        input_cost_per_1m=_to_float_or_none(entry.get("input_cost_per_1m")),
        output_cost_per_1m=_to_float_or_none(entry.get("output_cost_per_1m")),
        cached_input_cost_per_1m=_to_float_or_none(entry.get("cached_input_cost_per_1m")),
    )
    cost["model_lookup"] = lookup
    cost["pricing_file"] = str(MODEL_COSTS_PATH)
    return cost


def write_repo_usage_file(repo_out_root: Path, provider: str, model: str) -> None:
    repo_out_root = repo_out_root.resolve()
    all_usage = empty_usage(provider, model)
    instances: List[Dict[str, Any]] = []
    total_cost = 0.0
    has_unknown_cost = False

    for inst_dir in sorted(p for p in repo_out_root.iterdir() if p.is_dir()):
        usage_path = inst_dir / "usage.json"
        if not usage_path.exists():
            continue
        try:
            payload = load_json(usage_path)
        except Exception:
            instances.append(
                {
                    "instance": inst_dir.name,
                    "status": "error",
                    "usage_path": str(usage_path),
                    "error": "failed to parse usage.json",
                }
            )
            has_unknown_cost = True
            continue

        inst_usage = payload.get("usage")
        if isinstance(inst_usage, dict):
            merge_usage(all_usage, inst_usage)

        cost_obj = payload.get("cost")
        inst_cost = None
        if isinstance(cost_obj, dict):
            inst_cost = _to_float_or_none(cost_obj.get("cost_usd"))
        if inst_cost is None:
            has_unknown_cost = True
        else:
            total_cost += inst_cost

        instances.append(
            {
                "instance": str(payload.get("instance", inst_dir.name)),
                "status": str(payload.get("status", "unknown")),
                "cost_usd": inst_cost,
                "usage_path": str(usage_path),
            }
        )

    out = {
        "repo": repo_out_root.name,
        "provider": provider,
        "model": model,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "instance_count": len(instances),
        "all_usage": all_usage,
        "all_cost_usd": None if has_unknown_cost else total_cost,
        "instances": instances,
    }
    dump_json(repo_out_root / "usage.json", out)


def extract_first_json_object(text: str) -> Optional[Any]:
    text = text.strip()
    if not text:
        return None

    # direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # strip fenced code blocks
    code_fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if code_fence:
        cand = code_fence.group(1)
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass

    # brace scanning fallback
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    cand = text[start : i + 1]
                    try:
                        return json.loads(cand)
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)

    return None


def extract_answer_for_format(text: str, answer_format: str) -> Optional[Any]:
    """
    Extract the final JSON answer, honoring the answer format.

    For "reasoning" responses the model emits a derivation followed by
    `## Answer` and then the JSON. The free-form derivation may itself contain
    braces (dict-like prose, format specs, etc.), so we must NOT grab the first
    balanced object in the whole text. Strategy:
      1. If a `## Answer` sentinel is present, parse only the text after the LAST
         one.
      2. Within that region, prefer the LAST balanced {...} / [...] object.
    Falls back to the JSON-mode extractor (first balanced object) otherwise, so
    bare-JSON models are unaffected.
    """
    if answer_format != "reasoning":
        return extract_first_json_object(text)

    region = text
    idx = text.rfind(ANSWER_SENTINEL)
    if idx != -1:
        region = text[idx + len(ANSWER_SENTINEL):]
    region = region.strip()
    region = re.sub(r"^```(?:json)?\s*", "", region, flags=re.MULTILINE)
    region = re.sub(r"\s*```$", "", region, flags=re.MULTILINE).strip()

    # Prefer the LAST balanced object in the answer region.
    for pat in (r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", r"\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]"):
        hits = list(re.finditer(pat, region, re.DOTALL))
        if hits:
            try:
                return json.loads(hits[-1].group())
            except json.JSONDecodeError:
                pass
    # Fall back to a direct parse of the region, then the generic extractor.
    try:
        return json.loads(region)
    except json.JSONDecodeError:
        pass
    return extract_first_json_object(region if idx != -1 else text)


def _type_label(x: Any) -> str:
    if isinstance(x, bool):
        return "bool"
    if isinstance(x, int):
        return "int"
    if isinstance(x, float):
        return "float"
    if isinstance(x, str):
        return "str"
    if isinstance(x, list):
        return "list"
    if isinstance(x, dict):
        return "dict"
    return type(x).__name__


def _spec_container_kind(token: str) -> Optional[str]:
    """Recognize the outer container of a type-spec DSL string.

    Templates may describe shapes like 'list[{file: str, func: str, line: int}]',
    'list[int]', 'tuple[int, int]' or 'dict[str, object]'. Only unambiguous specs
    (no top-level union '|') are classified so a JSON string answer can be parsed
    back into a real list/dict instead of being kept/coerced as a string.
    """
    t = (token or "").strip().lower()
    if not t or "|" in t:
        return None
    if re.match(r"^(list|array|sequence|tuple)\s*\[", t):
        return "list"
    if re.match(r"^(dict|mapping)\s*\[", t):
        return "dict"
    return None


# Tokens that, when used as a template_answer dict key or value, describe the
# expected *shape* rather than literal content. A correct answer carries real
# keys/values (e.g. "Env", "StackName"), so these must be matched leniently --
# otherwise validation rejects the correct answer and the repair loop rewrites
# it into the literal template skeleton (a degenerate "echo" that then scores
# wrong against the oracle).
# Only unambiguous primitive type names are treated as wildcard *keys* (e.g. a
# template `{"str": true}` means "any string key -> bool"). Tokens like "key",
# "value", "object" are intentionally excluded: templates legitimately use them
# as literal field names (e.g. reflex `{"object": ..., "key": ...}`), so treating
# them as wildcards would wrongly drop a required key.
_WILDCARD_TYPE_TOKENS = {
    "str", "string", "int", "integer", "float", "number", "bool", "boolean",
}


def _is_placeholder_token(value: Any) -> bool:
    """True if a template string denotes shape, not literal content.

    Recognizes angle-bracket placeholders ('<key>', '<value>', '<str|object>',
    '<matching value>') and bare primitive type tokens ('str', 'int', ...). Such
    tokens constrain shape only and must never be required verbatim in the answer.
    """
    if not isinstance(value, str):
        return False
    t = value.strip()
    if len(t) > 2 and t.startswith("<") and t.endswith(">"):
        return True
    return t.lower() in _WILDCARD_TYPE_TOKENS


def validate_against_template(answer: Any, template: Any, path: str = "$") -> List[str]:
    errors: List[str] = []

    if isinstance(template, dict):
        if not isinstance(answer, dict):
            return [f"{path}: expected dict, got {_type_label(answer)}"]
        # Split required (literal) keys from wildcard keys ('<top_key>', 'str', ...).
        literal_items = {k: v for k, v in template.items() if not _is_placeholder_token(k)}
        wildcard_specs = [v for k, v in template.items() if _is_placeholder_token(k)]
        for key, tval in literal_items.items():
            if key not in answer:
                errors.append(f"{path}: missing key '{key}'")
                continue
            errors.extend(validate_against_template(answer[key], tval, f"{path}.{key}"))
        # A wildcard key matches arbitrary answer keys; validate each remaining
        # answer value against the wildcard value-spec, but never require the
        # literal placeholder key to be present.
        if wildcard_specs:
            spec = wildcard_specs[0]
            for akey, aval in answer.items():
                if akey in literal_items:
                    continue
                errors.extend(validate_against_template(aval, spec, f"{path}.{akey}"))
        return errors

    if isinstance(template, list):
        if not isinstance(answer, list):
            return [f"{path}: expected list, got {_type_label(answer)}"]
        # No strict shape constraints from template lists unless items are provided.
        if template:
            item_t = template[0]
            for i, item in enumerate(answer):
                errors.extend(validate_against_template(item, item_t, f"{path}[{i}]"))
        return errors

    if isinstance(template, str):
        token = template.strip().lower()
        container_kind = _spec_container_kind(token)
        if container_kind == "list":
            return [] if isinstance(answer, list) else [f"{path}: expected list, got {_type_label(answer)}"]
        if container_kind == "dict":
            return [] if isinstance(answer, dict) else [f"{path}: expected dict, got {_type_label(answer)}"]
        if token in {"int", "integer"} and not (isinstance(answer, int) and not isinstance(answer, bool)):
            return [f"{path}: expected int, got {_type_label(answer)}"]
        if token in {"float", "number"} and not (
            (isinstance(answer, int) and not isinstance(answer, bool)) or isinstance(answer, float)
        ):
            return [f"{path}: expected float/number, got {_type_label(answer)}"]
        if token in {"str", "string"} and not isinstance(answer, str):
            return [f"{path}: expected str, got {_type_label(answer)}"]
        if token in {"bool", "boolean"} and not isinstance(answer, bool):
            return [f"{path}: expected bool, got {_type_label(answer)}"]
        if token in {"list", "array"} and not isinstance(answer, list):
            return [f"{path}: expected list, got {_type_label(answer)}"]
        if token in {"dict", "object"} and not isinstance(answer, dict):
            return [f"{path}: expected dict, got {_type_label(answer)}"]
        return []

    # A bare null in a template is a shape placeholder (e.g. [null, null, ...]),
    # not a requirement that the answer be None.
    if template is None:
        return []

    # If template has concrete literal values, match type only (keeps template flexible).
    if type(answer) is not type(template):
        return [f"{path}: expected {_type_label(template)}, got {_type_label(answer)}"]
    return []


def _json_loads_if_possible(value: Any) -> Tuple[Any, bool]:
    if not isinstance(value, str):
        return value, False
    s = value.strip()
    if not s:
        return value, False
    try:
        return json.loads(s), True
    except json.JSONDecodeError:
        return value, False


def _coerce_to_bool(value: Any) -> Tuple[Any, bool]:
    if isinstance(value, bool):
        return value, False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value), True
    if isinstance(value, str):
        s = value.strip().lower()
        true_set = {"true", "t", "yes", "y", "on", "1"}
        false_set = {"false", "f", "no", "n", "off", "0", ""}
        if s in true_set:
            return True, True
        if s in false_set:
            return False, True
        parsed, changed = _json_loads_if_possible(value)
        if changed:
            return _coerce_to_bool(parsed)
    return value, False


def _coerce_to_int(value: Any) -> Tuple[Any, bool]:
    if isinstance(value, bool):
        return int(value), True
    if isinstance(value, int):
        return value, False
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value), True
        return value, False
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "t", "yes", "y", "on"}:
            return 1, True
        if s in {"false", "f", "no", "n", "off"}:
            return 0, True
        s_num = s.replace(",", "").replace("_", "")
        if re.fullmatch(r"[+-]?\d+", s_num):
            try:
                return int(s_num), True
            except Exception:
                pass
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", s_num):
            try:
                fv = float(s_num)
                if math.isfinite(fv) and fv.is_integer():
                    return int(fv), True
            except Exception:
                pass
        parsed, changed = _json_loads_if_possible(value)
        if changed:
            return _coerce_to_int(parsed)
    return value, False


def _coerce_to_float(value: Any) -> Tuple[Any, bool]:
    if isinstance(value, bool):
        return float(value), True
    if isinstance(value, int) and not isinstance(value, bool):
        return float(value), True
    if isinstance(value, float):
        return value, False
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "t", "yes", "y", "on"}:
            return 1.0, True
        if s in {"false", "f", "no", "n", "off"}:
            return 0.0, True
        s_num = s.replace(",", "").replace("_", "")
        try:
            return float(s_num), True
        except Exception:
            pass
        parsed, changed = _json_loads_if_possible(value)
        if changed:
            return _coerce_to_float(parsed)
    return value, False


def _coerce_to_str(value: Any) -> Tuple[Any, bool]:
    if isinstance(value, str):
        return value, False
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")), True
    if value is None:
        return "null", True
    return str(value), True


def _coerce_to_list(value: Any) -> Tuple[Any, bool]:
    if isinstance(value, list):
        return value, False
    if isinstance(value, (tuple, set)):
        return list(value), True
    if isinstance(value, str):
        parsed, changed = _json_loads_if_possible(value)
        if changed:
            if isinstance(parsed, list):
                return parsed, True
            return [parsed], True
    if value is None:
        return [], True
    return [value], True


def _coerce_to_dict(value: Any) -> Tuple[Any, bool]:
    if isinstance(value, dict):
        return value, False
    if isinstance(value, str):
        parsed, changed = _json_loads_if_possible(value)
        if changed:
            if isinstance(parsed, dict):
                return parsed, True
            if isinstance(parsed, list):
                try:
                    return dict(parsed), True
                except Exception:
                    pass
    if isinstance(value, (list, tuple)):
        try:
            return dict(value), True
        except Exception:
            return value, False
    return value, False


def _template_kind(template: Any) -> Optional[str]:
    if isinstance(template, str):
        token = template.strip().lower()
        if token in {"int", "integer"}:
            return "int"
        if token in {"float", "number"}:
            return "float"
        if token in {"str", "string"}:
            return "str"
        if token in {"bool", "boolean"}:
            return "bool"
        if token in {"list", "array"}:
            return "list"
        if token in {"dict", "object"}:
            return "dict"
        container_kind = _spec_container_kind(token)
        if container_kind is not None:
            return container_kind
        # Unrecognized/descriptive or union specs (e.g. 'null | list', 'str_or_null',
        # 'yes_or_no', '<value>'): leave the model's native JSON value untouched rather
        # than force-stringify it, which previously turned lists/dicts/null into strings.
        return None
    if isinstance(template, bool):
        return "bool"
    if isinstance(template, int):
        return "int"
    if isinstance(template, float):
        return "float"
    if isinstance(template, list):
        return "list"
    if isinstance(template, dict):
        return "dict"
    return None


def _coerce_by_kind(value: Any, kind: str) -> Tuple[Any, bool]:
    if kind == "bool":
        return _coerce_to_bool(value)
    if kind == "int":
        return _coerce_to_int(value)
    if kind == "float":
        return _coerce_to_float(value)
    if kind == "str":
        return _coerce_to_str(value)
    if kind == "list":
        return _coerce_to_list(value)
    if kind == "dict":
        return _coerce_to_dict(value)
    return value, False


def coerce_against_template(answer: Any, template: Any, path: str = "$") -> Tuple[Any, List[str]]:
    notes: List[str] = []

    if isinstance(template, dict):
        container, changed = _coerce_to_dict(answer)
        if changed:
            notes.append(f"{path}: coerced {_type_label(answer)}->dict")
        if not isinstance(container, dict):
            return container, notes
        out = dict(container)
        for key, tval in template.items():
            if key not in out:
                continue
            coerced, child_notes = coerce_against_template(out[key], tval, f"{path}.{key}")
            out[key] = coerced
            notes.extend(child_notes)
        return out, notes

    if isinstance(template, list):
        container, changed = _coerce_to_list(answer)
        if changed:
            notes.append(f"{path}: coerced {_type_label(answer)}->list")
        if not isinstance(container, list):
            return container, notes
        if not template:
            return container, notes
        item_template = template[0]
        out_list: List[Any] = []
        for idx, item in enumerate(container):
            coerced, child_notes = coerce_against_template(item, item_template, f"{path}[{idx}]")
            out_list.append(coerced)
            notes.extend(child_notes)
        return out_list, notes

    kind = _template_kind(template)
    if kind is None:
        return answer, notes

    coerced, changed = _coerce_by_kind(answer, kind)
    if changed:
        notes.append(f"{path}: coerced {_type_label(answer)}->{kind}")
    return coerced, notes


# ---------------------------
# RepoMap + provider modules
# ---------------------------

try:
    from .provider_runner import (
        ANSWER_RULES_REASONING,
        ANSWER_SENTINEL,
        FINAL_REASONING_PROMPT,
        ProviderRunner,
        TOOL_PHASE_DONE_SENTINEL,
    )
    from .repo_tools import INSTANCE_PREVIEW_LIMIT, ReadOnlyRepoTools, shrink_tool_payload_for_llm
    from .container_runtime import CONTAINER_RUNTIME_CHOICES, ContainerRuntime, build_container_runtime
except ImportError:
    from provider_runner import (
        ANSWER_RULES_REASONING,
        ANSWER_SENTINEL,
        FINAL_REASONING_PROMPT,
        ProviderRunner,
        TOOL_PHASE_DONE_SENTINEL,
    )
    from repo_tools import INSTANCE_PREVIEW_LIMIT, ReadOnlyRepoTools, shrink_tool_payload_for_llm
    from container_runtime import CONTAINER_RUNTIME_CHOICES, ContainerRuntime, build_container_runtime


# ---------------------------------------------------------------------------
# Answer format (JSON vs reasoning) — reasoning is used for gemma4 models only
# ---------------------------------------------------------------------------

def resolve_answer_format(answer_format: str, model: str) -> str:
    """
    Resolve the --answer-format choice to a concrete format.

    "auto" → "reasoning" for gemma4 models (trained to derive the answer before
    emitting JSON), "json" for everything else. This keeps every non-gemma4
    model on the exact original protocol.
    """
    if answer_format != "auto":
        return answer_format
    name = (model or "").lower()
    if "gemma4" in name or "gemma-4" in name:
        return "reasoning"
    return "json"

REASONING_TRACE_EVENTS_LIMIT = int(os.environ.get("REPOBEHAVE_REASONING_TRACE_EVENTS_LIMIT", "80"))
REASONING_TRACE_TEXT_MAX_CHARS = int(os.environ.get("REPOBEHAVE_REASONING_TRACE_MAX_CHARS", "18000"))


# ---------------------------
# Worker mode
# ---------------------------


def make_system_prompt(*, repo_map_mode: str, max_read_lines: int, answer_format: str = "json") -> str:
    first_step = (
        "Call get_repo_map first, then use list_dir/read_file only as needed."
        if repo_map_mode != "none"
        else "Use list_dir/read_file tools only (get_repo_map is disabled)."
    )
    # Rules 7-8 differ between the bare-JSON protocol (all existing models) and
    # the reasoning protocol (gemma4 models trained to derive then answer). The
    # reasoning rules are imported from provider_runner so they stay identical
    # to the training-time student prompt in create_sft_dataset.py.
    if answer_format == "reasoning":
        answer_rules = ANSWER_RULES_REASONING
    else:
        answer_rules = (
            "7. After the follow-up prompt closes the tool phase, return exactly one JSON object matching "
            "template_answer keys and value types.\n"
            "8. Do not output markdown or explanations in the final answer."
        )
    return (
        "Solve repository QA in read-only mode with tool calls only.\n"
        "Rules:\n"
        f"1. {first_step}\n"
        "2. Prefer relative paths. Repo files are usually like src/...; instance files are usually files/....\n"
        "3. Minimize unnecessary reads and repeated failed paths.\n"
        f"4. read_file has a hard per-call limit: at most {max_read_lines} lines.\n"
        f"5. When you are completely done using tools, reply with exactly {TOOL_PHASE_DONE_SENTINEL}.\n"
        "6. Do not combine the completion signal with the final JSON answer.\n"
        f"{answer_rules}"
    )


def make_repair_system_prompt() -> str:
    return (
        "Repair the answer into valid JSON.\n"
        "Rules:\n"
        "1. Return exactly one JSON object matching the requested template.\n"
        "2. Do not call tools.\n"
        "3. Do not output markdown or explanations."
    )


def build_user_prompt(
    *,
    question_data: Dict[str, Any],
    repo_root: Path,
    instance_dir: Path,
    instance_files_preview: List[str],
    answer_format: str = "json",
) -> str:
    question = question_data.get("question", "")
    template_answer = question_data.get("template_answer", {})
    question_kind = question_data.get("question_kind", "unknown")
    template_str = json.dumps(template_answer, sort_keys=True, separators=(",", ":"))

    preview_files = instance_files_preview[:INSTANCE_PREVIEW_LIMIT]
    preview_lines = [f"- {p}" for p in preview_files]
    omitted_count = len(instance_files_preview) - len(preview_files)
    if omitted_count > 0:
        preview_lines.append(f"- ... ({omitted_count} more files)")
    preview_str = "\n".join(preview_lines)

    # Host paths intentionally omitted — the model must use relative paths
    # (e.g. files/..., src/...) so the prompt is portable across hosts and
    # matches the training distribution from create_sft_dataset.py.
    _ = (repo_root, instance_dir)  # kept in signature for downstream callers
    phase2 = (
        "Task phase 2: after the follow-up closes tool use, first give a brief derivation, "
        f"then '{ANSWER_SENTINEL}' on its own line, then the final JSON answer object."
        if answer_format == "reasoning"
        else "Task phase 2: after the follow-up closes tool use, return only the final JSON answer object."
    )
    return (
        f"Question kind: {question_kind}\n\n"
        f"Question:\n{question}\n\n"
        f"Template answer (must match exactly):\n{template_str}\n\n"
        "Instance file preview (read with tools using relative paths; "
        "repo files live at e.g. src/...):\n"
        f"{preview_str if preview_str else '- (no files)'}\n\n"
        f"Task phase 1: use tools as needed, then reply with exactly {TOOL_PHASE_DONE_SENTINEL}.\n"
        f"{phase2}"
    )


def make_reasoning_trace_system_prompt() -> str:
    return (
        "Produce a concise rationale trace for a completed repository QA answer.\n"
        "Return exactly one JSON object with keys: "
        '{"concise_thought":"string","execution_steps":["string"],"key_evidence":["string"],"uncertainties":["string"]}.\n'
        "Do not call tools. Do not output markdown."
    )


def build_reasoning_trace_prompt(
    *,
    question_data: Dict[str, Any],
    final_answer: Dict[str, Any],
    trajectory_events: List[str],
) -> str:
    question = str(question_data.get("question", ""))
    final_answer_str = json.dumps(final_answer, sort_keys=True, separators=(",", ":"))

    normalized_events: List[str] = []
    for raw in trajectory_events[-max(1, REASONING_TRACE_EVENTS_LIMIT):]:
        line = " ".join((raw or "").split())
        if not line:
            continue
        if len(line) > 500:
            line = line[:500] + "...<truncated>"
        normalized_events.append(f"- {line}")

    kept_events: List[str] = []
    used_chars = 0
    for line in normalized_events:
        extra = len(line) + 1
        if used_chars + extra > max(500, REASONING_TRACE_TEXT_MAX_CHARS):
            break
        kept_events.append(line)
        used_chars += extra

    events_str = "\n".join(kept_events) if kept_events else "- (no trace events captured)"

    return (
        f"Question:\n{question}\n\n"
        f"Final answer JSON:\n{final_answer_str}\n\n"
        "Execution trace events from tool/model interaction:\n"
        f"{events_str}\n\n"
        "Now return the rationale trace JSON object with the required keys."
    )


def run_single_instance(
    *,
    provider: str,
    model: str,
    question_path: Path,
    repo_root: Path,
    max_read_lines: int,
    repo_map_mode: str,
    cheap_repomap_max_files: int,
    temperature: float,
    max_repair_rounds: int,
    answer_format: str = "json",
    reasoning_effort: str = "",
    trace: Optional[Callable[[str], None]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    question_data = load_json(question_path)
    instance_dir = question_path.parent

    instance_files = []
    files_dir = instance_dir / "files"
    if files_dir.exists():
        instance_files = [str(p.relative_to(instance_dir)) for p in sorted(files_dir.rglob("*")) if p.is_file()]

    tools = ReadOnlyRepoTools(
        repo_root=repo_root,
        instance_dir=instance_dir,
        max_read_lines=max_read_lines,
        repo_map_mode=repo_map_mode,
        cheap_repomap_max_files=cheap_repomap_max_files,
    )
    enabled_tool_names = tools.enabled_tool_names()

    local_trace_events: List[str] = []

    def _emit_trace(msg: str) -> None:
        local_trace_events.append(msg)
        if trace:
            trace(msg)

    def _trace_tool_result(name: str, payload: Dict[str, Any]) -> None:
        try:
            serialized = json.dumps(payload, ensure_ascii=False)
        except Exception:
            serialized = str(payload)
        max_chars = 5000
        if len(serialized) > max_chars:
            serialized = serialized[:max_chars] + "...<truncated>"
        _emit_trace(f"[tool] send_to_llm {name} result={serialized}")

    def tool_callback(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        _emit_trace(f"[tool] call {name} args={json.dumps(args, ensure_ascii=False)}")
        if name == "get_repo_map":
            result = tools.get_repo_map(focus_paths=args.get("focus_paths"))
            out = {"ok": result.ok, **result.payload}
            out = shrink_tool_payload_for_llm(name, out)
            preview = (out.get("repo_map", "") or "")[:500].replace("\n", " ")
            _emit_trace(f"[tool] result {name} ok={out.get('ok')} preview={preview}")
            _trace_tool_result(name, out)
            return out
        if name == "list_dir":
            result = tools.list_dir(path=args.get("path", "."), max_entries=args.get("max_entries", 200))
            out = {"ok": result.ok, **result.payload}
            out = shrink_tool_payload_for_llm(name, out)
            _emit_trace(f"[tool] result {name} ok={out.get('ok')} entries={len(out.get('entries', []))}")
            _trace_tool_result(name, out)
            return out
        if name == "read_file":
            result = tools.read_file(
                path=args.get("path", ""),
                start_line=args.get("start_line", 1),
                end_line=args.get("end_line", 250),
            )
            out = {"ok": result.ok, **result.payload}
            out = shrink_tool_payload_for_llm(name, out)
            _emit_trace(
                f"[tool] result {name} ok={out.get('ok')} path={out.get('path')} "
                f"lines={out.get('start_line')}-{out.get('end_line')}"
            )
            _trace_tool_result(name, out)
            return out
        return {"ok": False, "error": f"unknown tool: {name}"}

    runner = ProviderRunner(
        provider=provider,
        model=model,
        temperature=temperature,
        trace=_emit_trace,
        final_answer_prompt=(FINAL_REASONING_PROMPT if answer_format == "reasoning" else None),
        reasoning_effort=reasoning_effort,
    )

    system_prompt = make_system_prompt(
        repo_map_mode=repo_map_mode,
        max_read_lines=max_read_lines,
        answer_format=answer_format,
    )
    user_prompt = build_user_prompt(
        question_data=question_data,
        repo_root=repo_root,
        instance_dir=instance_dir,
        instance_files_preview=instance_files,
        answer_format=answer_format,
    )

    template = question_data.get("template_answer", {})
    raw_response = runner.run(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tool_callback=tool_callback,
        tool_names=enabled_tool_names,
    )
    _emit_trace(f"[final-raw] {raw_response}")
    parsed = extract_answer_for_format(raw_response, answer_format)

    coercion_notes: List[str] = []

    def _apply_coercion() -> None:
        nonlocal parsed
        if parsed is None:
            return
        coerced, notes = coerce_against_template(parsed, template)
        parsed = coerced
        if not notes:
            return
        remaining = 200 - len(coercion_notes)
        if remaining > 0:
            coercion_notes.extend(notes[:remaining])
        preview = "; ".join(notes[:12])
        if len(notes) > 12:
            preview += "; ..."
        _emit_trace(f"[coerce] {preview}")

    _apply_coercion()

    repair_messages: List[str] = []
    repair_attempts = 0
    while repair_attempts < max_repair_rounds:
        if parsed is None:
            err = "Model response was not valid JSON."
        else:
            errs = validate_against_template(parsed, template)
            if not errs:
                break
            err = "Template validation failed: " + "; ".join(errs)

        repair_attempts += 1
        repair_prompt = (
            f"Your previous answer was invalid.\n"
            f"Error: {err}\n"
            f"Return ONLY one valid JSON object matching this template:\n"
            f"{json.dumps(template, sort_keys=True, separators=(',', ':'))}"
        )
        repair_messages.append(err)

        raw_response = runner.run(
            system_prompt=make_repair_system_prompt(),
            user_prompt=repair_prompt,
            tool_callback=tool_callback,
            enable_tools=False,
            tool_names=enabled_tool_names,
        )
        parsed = extract_first_json_object(raw_response)
        _apply_coercion()

    if parsed is None:
        raise RuntimeError("Could not extract valid JSON from model response")

    final_errors = validate_against_template(parsed, template)
    if final_errors:
        raise RuntimeError("Final answer failed template validation: " + "; ".join(final_errors))

    reasoning_trace_raw = ""
    reasoning_trace_error = ""
    reasoning_trace: Optional[Dict[str, Any]] = None
    try:
        reasoning_prompt = build_reasoning_trace_prompt(
            question_data=question_data,
            final_answer=parsed,
            trajectory_events=local_trace_events,
        )
        reasoning_trace_raw = runner.run(
            system_prompt=make_reasoning_trace_system_prompt(),
            user_prompt=reasoning_prompt,
            tool_callback=tool_callback,
            enable_tools=False,
            tool_names=enabled_tool_names,
        )
        if len(reasoning_trace_raw) > 30000:
            reasoning_trace_raw = reasoning_trace_raw[:30000] + "...<truncated>"
        reasoning_candidate = extract_first_json_object(reasoning_trace_raw)
        if isinstance(reasoning_candidate, dict):
            reasoning_trace = reasoning_candidate
        else:
            reasoning_trace = {
                "concise_thought": "",
                "execution_steps": [],
                "key_evidence": [],
                "uncertainties": [],
                "raw": reasoning_trace_raw,
            }
        _emit_trace("[reasoning-trace] capture_complete")
    except Exception as exc:
        reasoning_trace_error = str(exc)
        _emit_trace(f"[reasoning-trace] capture_failed: {reasoning_trace_error}")

    usage = runner.usage_summary()
    cost = compute_usage_cost_for_model(provider=provider, model=model, usage=usage)

    debug = {
        "question_path": str(question_path),
        "repair_attempts": repair_attempts,
        "repair_errors": repair_messages,
        "coercion_note_count": len(coercion_notes),
        "coercion_notes": coercion_notes,
        "usage": usage,
        "cost": cost,
        "raw_response": raw_response,
        "reasoning_trace": reasoning_trace,
        "reasoning_trace_raw": reasoning_trace_raw,
        "reasoning_trace_error": reasoning_trace_error,
    }
    return parsed, debug




def single_line_console_preview(msg: str, *, max_chars: int = 400) -> str:
    lines = (msg or "").splitlines()
    first = lines[0] if lines else ""
    first = first.strip()
    truncated = len(lines) > 1
    if len(first) > max_chars:
        first = first[:max_chars] + "...<truncated>"
        truncated = False
    elif truncated:
        first += " ...<truncated>"
    return first

def parse_repo_root_from_question(question_text: str) -> Optional[Path]:
    m = re.search(r"(/testbed/[A-Za-z0-9_.-]+/)", question_text or "")
    if not m:
        return None
    candidate = Path(m.group(1)).resolve()
    if candidate.exists():
        return candidate
    return None


def default_repo_candidates(repo_name: str, base: Path) -> List[Path]:
    aliases = {
        "Sympy": ["sympy", "Sympy"],
        "Keras": ["keras", "Keras"],
        "Telegram_bot": ["python-telegram-bot", "telegram_bot", "Telegram_bot"],
        "Faker": ["faker", "Faker"],
        "Xarray": ["xarray", "Xarray"],
    }
    names = aliases.get(repo_name, [repo_name, repo_name.lower()])
    return [(base / n).resolve() for n in names]


def infer_repo_subdir_from_question(repo_instances_dir: Path) -> Optional[str]:
    qfiles = sorted(repo_instances_dir.glob("*/question.json"))
    if not qfiles:
        return None
    first_q = load_json(qfiles[0])
    question = str(first_q.get("question", ""))
    m = re.search(r"(/testbed/[A-Za-z0-9_.-]+/)", question)
    if not m:
        return None
    p = Path(m.group(1))
    parts = p.parts
    # e.g. /testbed/sympy/
    if len(parts) >= 3:
        return parts[2]
    return None


def _extract_repo_hint_paths_from_question(repo_instances_dir: Path) -> List[str]:
    qfiles = sorted(repo_instances_dir.glob("*/question.json"))
    if not qfiles:
        return []

    first_q = load_json(qfiles[0])
    question = str(first_q.get("question", ""))
    hints: List[str] = []
    seen: set[str] = set()

    # Prefer concrete python source paths that can validate the candidate repo root.
    for raw in re.findall(r"`([^`]+)`", question):
        p = raw.strip().strip("/")
        if not p or "/" not in p:
            continue
        if not p.endswith(".py"):
            continue
        if p.startswith("tests/") or p.startswith("files/tests/"):
            continue
        if p in seen:
            continue
        seen.add(p)
        hints.append(p)

    return hints


def list_testbed_dirs(image: str, *, container_runtime: ContainerRuntime) -> List[str]:
    return container_runtime.list_dir_entries(image=image, dir_path="/testbed")


def infer_repo_subdir_for_image(
    repo_name: str,
    repo_instances_dir: Path,
    image: str,
    *,
    container_runtime: ContainerRuntime,
) -> str:
    from_question = infer_repo_subdir_from_question(repo_instances_dir)
    hint_paths = _extract_repo_hint_paths_from_question(repo_instances_dir)
    dirs = list_testbed_dirs(image, container_runtime=container_runtime)
    aliases = [p.name for p in default_repo_candidates(repo_name, Path("/testbed"))]

    # Some images place repository root directly at /testbed (no nested subdir).
    root_markers = {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "README.md",
        "README.rst",
        ".git",
    }
    root_looks_like_repo = any(marker in dirs for marker in root_markers)

    candidate_subdirs: List[str] = []
    seen_candidates: set[str] = set()

    def _add_candidate(candidate: str) -> None:
        c = (candidate or "").strip()
        if not c or c in seen_candidates:
            return
        seen_candidates.add(c)
        candidate_subdirs.append(c)

    if from_question:
        _add_candidate(from_question)
    for alias in aliases:
        if alias in dirs:
            _add_candidate(alias)
    if root_looks_like_repo:
        _add_candidate(".")
    if len(dirs) == 1:
        _add_candidate(dirs[0])
    for d in dirs:
        _add_candidate(d)

    if hint_paths:
        for candidate in candidate_subdirs:
            prefix = "/testbed" if candidate == "." else f"/testbed/{candidate}"
            for hint_rel in hint_paths:
                if container_runtime.path_exists(image=image, path=f"{prefix}/{hint_rel}"):
                    return candidate

    # Fall back to old behavior when no hints were available or no candidate matched.
    if from_question:
        return from_question
    for alias in aliases:
        if alias in dirs:
            return alias
    if root_looks_like_repo:
        return "."
    if len(dirs) == 1:
        return dirs[0]
    raise RuntimeError(
        f"Could not infer /testbed repo subdir for {repo_name}. Found dirs: {dirs}"
    )


def materialize_repo_snapshot(
    *,
    repo_name: str,
    image: str,
    repo_instances_dir: Path,
    mount_root: Path,
    refresh: bool,
    container_runtime: ContainerRuntime,
) -> Tuple[Path, bool]:
    if not container_runtime.is_available():
        raise RuntimeError(
            f"{container_runtime.name.capitalize()} is required for snapshot materialization but is not available"
        )

    mount_root = mount_root.resolve()
    dest = mount_root / repo_name
    if dest.exists() and any(dest.iterdir()) and not refresh:
        print(f"[{repo_name}] Using existing mounted snapshot: {dest}")
        return dest, False

    if refresh and dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    container_runtime.ensure_image_available(image, repo_name=repo_name)

    repo_subdir = infer_repo_subdir_for_image(
        repo_name,
        repo_instances_dir,
        image,
        container_runtime=container_runtime,
    )
    src_label = "/testbed" if repo_subdir == "." else f"/testbed/{repo_subdir}"
    print(f"[{repo_name}] Materializing {src_label} -> {dest}")

    copy_src = "/testbed" if repo_subdir == "." else f"/testbed/{repo_subdir}"
    container_runtime.copy_dir_contents(image=image, src_dir=copy_src, dest=dest, name_hint=repo_name)

    if not any(dest.iterdir()):
        raise RuntimeError(f"Snapshot materialization produced empty directory: {dest}")

    return dest, True


def _repo_snapshot_url(spec: Dict[str, Any]) -> str:
    for key in ("github_url", "repo_url", "url", "clone_url"):
        value = str(spec.get(key, "") or "").strip()
        if value:
            return value
    raise RuntimeError("repo snapshot entry is missing github_url/repo_url/url")


def _repo_snapshot_commit(spec: Dict[str, Any]) -> str:
    for key in ("hash_commit", "base_commit", "commit", "commit_hash", "sha"):
        value = str(spec.get(key, "") or "").strip()
        if value:
            return value
    raise RuntimeError("repo snapshot entry is missing hash_commit/base_commit/commit")


def load_repo_snapshot_specs(path: Path) -> Dict[str, Dict[str, str]]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise SystemExit(f"--repo-snapshots-file must be a JSON object (repo->snapshot): {path}")

    specs: Dict[str, Dict[str, str]] = {}
    for repo_name, raw_spec in data.items():
        if not isinstance(raw_spec, dict):
            raise SystemExit(
                f"--repo-snapshots-file entry for {repo_name!r} must be an object with github_url and hash_commit"
            )
        try:
            github_url = _repo_snapshot_url(raw_spec)
            hash_commit = _repo_snapshot_commit(raw_spec)
        except RuntimeError as exc:
            raise SystemExit(f"Invalid --repo-snapshots-file entry for {repo_name!r}: {exc}") from exc
        if not re.fullmatch(r"[0-9a-fA-F]{40}", hash_commit):
            raise SystemExit(
                f"Invalid --repo-snapshots-file entry for {repo_name!r}: "
                f"hash_commit must be a full 40-character git SHA"
            )
        specs[str(repo_name)] = {
            "github_url": github_url,
            "hash_commit": hash_commit.lower(),
        }
    return specs


def materialize_repo_snapshot_from_git(
    *,
    repo_name: str,
    snapshot_spec: Dict[str, str],
    mount_root: Path,
    refresh: bool,
) -> Tuple[Path, bool]:
    if shutil.which("git") is None:
        raise RuntimeError("git is required for snapshot materialization but is not available")

    github_url = _repo_snapshot_url(snapshot_spec)
    hash_commit = _repo_snapshot_commit(snapshot_spec).lower()
    mount_root = mount_root.resolve()
    dest = mount_root / repo_name
    if dest.exists() and any(dest.iterdir()) and not refresh:
        print(f"[{repo_name}] Using existing mounted snapshot: {dest}")
        return dest, False

    mount_root.mkdir(parents=True, exist_ok=True)
    tmp_dest = mount_root / f".{sanitize_name(repo_name)}.git-clone-{os.getpid()}"
    if tmp_dest.exists():
        shutil.rmtree(tmp_dest)

    print(f"[{repo_name}] Materializing git snapshot {hash_commit} from {github_url} -> {dest}")
    try:
        try:
            run_checked(["git", "clone", "--filter=blob:none", "--no-checkout", github_url, str(tmp_dest)])
        except subprocess.CalledProcessError:
            if tmp_dest.exists():
                shutil.rmtree(tmp_dest)
            run_checked(["git", "clone", "--no-checkout", github_url, str(tmp_dest)])

        run_checked(["git", "-C", str(tmp_dest), "fetch", "--depth=1", "origin", hash_commit])
        run_checked(["git", "-C", str(tmp_dest), "checkout", "--detach", hash_commit])
        run_checked(["git", "-C", str(tmp_dest), "submodule", "update", "--init", "--recursive"])
        actual = run_checked(["git", "-C", str(tmp_dest), "rev-parse", "HEAD"], capture=True).stdout.strip()
        if actual.lower() != hash_commit:
            raise RuntimeError(
                f"git checkout produced {actual}, expected {hash_commit}"
            )

        if dest.exists():
            shutil.rmtree(dest)
        tmp_dest.replace(dest)
    except Exception:
        if tmp_dest.exists():
            shutil.rmtree(tmp_dest)
        raise

    if not any(dest.iterdir()):
        raise RuntimeError(f"Git snapshot materialization produced empty directory: {dest}")

    return dest, True


def resolve_repo_root(
    *,
    repo_name: str,
    repo_instances_dir: Path,
    explicit_repo_root: Optional[str],
    repo_roots_map: Dict[str, str],
    repo_root_base: Path,
) -> Path:
    if explicit_repo_root:
        p = Path(explicit_repo_root).resolve()
        if not p.exists():
            raise RuntimeError(f"Configured repo root does not exist: {p}")
        return p

    mapped = repo_roots_map.get(repo_name)
    if mapped:
        p = Path(mapped).resolve()
        if not p.exists():
            raise RuntimeError(f"Mapped repo root does not exist for {repo_name}: {p}")
        return p

    qfiles = sorted(repo_instances_dir.glob("*/question.json"))
    if qfiles:
        first_q = load_json(qfiles[0])
        inferred = parse_repo_root_from_question(str(first_q.get("question", "")))
        if inferred:
            return inferred

    for candidate in default_repo_candidates(repo_name, repo_root_base):
        if candidate.exists():
            return candidate

    raise RuntimeError(
        f"Could not resolve repo root for {repo_name}. "
        "Use --repo-root (single repo) or --repo-roots-file (all/multiple repos)."
    )


def run_repo(
    *,
    provider: str,
    model: str,
    repo_name: str,
    repo_root: Path,
    instances_dir: Path,
    out_repo_root: Path,
    num_instances: str,
    max_read_lines: int,
    repo_map_mode: str,
    cheap_repomap_max_files: int,
    temperature: float,
    max_repair_rounds: int,
    print_llm_trace: bool,
    resume: bool,
    resume_skip_errors: bool,
    num_threads: int,
    answer_format: str = "json",
    only_instances: Optional[Sequence[str]] = None,
) -> None:
    selected_ids = select_instances(instances_dir, num_instances, only_instances)
    if not selected_ids:
        print(f"[{repo_name}] Skipping: no instances selected")
        return

    out_repo_root.mkdir(parents=True, exist_ok=True)

    print(f"[{repo_name}] repo_root={repo_root}")
    print(f"[{repo_name}] running {len(selected_ids)} instances...")
    if resume:
        print(f"[{repo_name}] resume mode enabled: completed instances will be skipped")
        if resume_skip_errors:
            print(f"[{repo_name}] resume mode: previously errored instances will also be skipped")

    effective_threads = max(1, min(int(num_threads), len(selected_ids)))
    print(f"[{repo_name}] threads={effective_threads}")

    indexed_instances: List[Tuple[int, str]] = list(enumerate(selected_ids, start=1))

    def _run_one(item: Tuple[int, str]) -> None:
        idx, instance_id = item
        qpath = instances_dir / instance_id / "question.json"
        out_dir = out_repo_root / instance_id
        out_dir.mkdir(parents=True, exist_ok=True)
        answer_path = out_dir / "answer.json"
        log_path = out_dir / "llm.log"
        traj_path = out_dir / "traj.json"
        usage_path = out_dir / "usage.json"

        if resume and answer_path.exists() and answer_path.stat().st_size > 0:
            print(f"[{repo_name}][{idx}/{len(selected_ids)}] {instance_id} (skip: answer exists)")
            return
        if resume and resume_skip_errors and usage_path.exists():
            try:
                usage_payload = load_json(usage_path)
                if str(usage_payload.get("status", "")).lower() == "error":
                    print(f"[{repo_name}][{idx}/{len(selected_ids)}] {instance_id} (skip: previous error)")
                    return
            except Exception:
                pass

        print(f"[{repo_name}][{idx}/{len(selected_ids)}] {instance_id}")
        trace_prefix = f"[{repo_name}/{instance_id}] "
        trajectory_events: List[str] = []

        def _trace(msg: str) -> None:
            trajectory_events.append(msg)
            if print_llm_trace:
                print(trace_prefix + single_line_console_preview(msg))

        try:
            answer, debug = run_single_instance(
                provider=provider,
                model=model,
                question_path=qpath,
                repo_root=repo_root,
                max_read_lines=max_read_lines,
                repo_map_mode=repo_map_mode,
                cheap_repomap_max_files=cheap_repomap_max_files,
                temperature=temperature,
                max_repair_rounds=max_repair_rounds,
                answer_format=answer_format,
                trace=_trace,
            )
            dump_json(answer_path, answer)
            dump_json(
                usage_path,
                {
                    "status": "ok",
                    "instance": instance_id,
                    "provider": provider,
                    "model": model,
                    "usage": debug.get("usage", empty_usage(provider, model)),
                    "cost": debug.get(
                        "cost",
                        compute_usage_cost_for_model(
                            provider=provider,
                            model=model,
                            usage=empty_usage(provider, model),
                        ),
                    ),
                },
            )
            traj_payload: Dict[str, Any] = {
                "status": "ok",
                "instance": instance_id,
                "events": trajectory_events,
                "reasoning_trace": debug.get("reasoning_trace"),
            }
            if debug.get("reasoning_trace_error"):
                traj_payload["reasoning_trace_error"] = debug.get("reasoning_trace_error")
            if debug.get("reasoning_trace_raw"):
                traj_payload["reasoning_trace_raw"] = debug.get("reasoning_trace_raw")
            dump_json(traj_path, traj_payload)
            log_payload = {"status": "ok", "instance": instance_id, "debug": debug}
            # Defensive guarantee: success should always have answer.json.
            if not answer_path.exists():
                dump_json(answer_path, answer)
        except Exception as exc:
            dump_json(
                traj_path,
                {
                    "status": "error",
                    "instance": instance_id,
                    "events": trajectory_events,
                    "error": str(exc),
                },
            )
            log_payload = {
                "status": "error",
                "instance": instance_id,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
            dump_json(
                usage_path,
                {
                    "status": "error",
                    "instance": instance_id,
                    "provider": provider,
                    "model": model,
                    "usage": empty_usage(provider, model),
                    "cost": compute_usage_cost_for_model(
                        provider=provider,
                        model=model,
                        usage=empty_usage(provider, model),
                    ),
                    "error": str(exc),
                },
            )

        log_path.write_text(json.dumps(log_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if effective_threads <= 1:
        for item in indexed_instances:
            _run_one(item)
    else:
        with ThreadPoolExecutor(max_workers=effective_threads) as executor:
            futures = [executor.submit(_run_one, item) for item in indexed_instances]
            for fut in futures:
                fut.result()

    write_repo_usage_file(out_repo_root, provider, model)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run host-side read-only LLM RepoMap QA eval")
    p.add_argument(
        "--provider",
        choices=["openai", "gemini", "anthropic", "fireworks", "openrouter", "vllm"],
        required=True,
    )
    p.add_argument("--model", required=True)
    p.add_argument(
        "--answer-format",
        choices=["auto", "json", "reasoning"],
        default="auto",
        help=(
            "Final-answer protocol. 'json' (the original) asks for a bare JSON object. "
            "'reasoning' asks for a derivation then '## Answer' then JSON — use for gemma4 "
            "models fine-tuned with the reasoning dataset. 'auto' (default) picks 'reasoning' "
            "for gemma4 models and 'json' for everything else, so non-gemma4 runs are unchanged."
        ),
    )
    p.add_argument("--repo", default="all", help="Repo name under qa_instances_eval, or all")
    p.add_argument(
        "--task-ids",
        nargs="+",
        default=None,
        help=(
            "Run only specific instances. Each task id is '<repo>/<instance_id>' "
            "(e.g. Keras/optimizers_adam_v_vs_m2_invariant). May be repeated/space-separated. "
            "Overrides --repo and --num-instances selection."
        ),
    )
    p.add_argument("--instances-root", default=str(REPO_ROOT / "qa_instances_eval"))
    p.add_argument("--output-root", default=str(REPO_ROOT / "evaluations"))
    p.add_argument("--num-instances", default="all", help="'all' or integer")
    p.add_argument("--num-threads", type=int, default=1, help="Number of worker threads to run instances in parallel")
    p.add_argument("--resume", action="store_true", help="Skip instances that already have non-empty answer.json")
    p.add_argument(
        "--resume-skip-errors",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="With --resume, also skip instances that already have usage.json status=error",
    )
    p.add_argument(
        "--repos-file",
        default=str(REPO_ROOT / "Repositories.json"),
        help="Repo->container-image mapping for snapshot materialization",
    )
    p.add_argument(
        "--repo-snapshots-file",
        default=str(REPO_ROOT / "RepoSnapshots.json"),
        help="Repo->GitHub URL and hash_commit mapping used when --container-runtime is none",
    )
    p.add_argument(
        "--container-runtime",
        default="docker",
        help=(
            "Snapshot materialization backend: docker, apptainer, or none/None/null "
            "to git clone and checkout --repo-snapshots-file commits"
        ),
    )
    p.add_argument(
        "--mount-root",
        default=str(REPO_ROOT / ".tmp_mounted_repos"),
        help="Temporary mount root inside RepoBehave for materialized repos",
    )
    p.add_argument(
        "--materialize-missing-from-image",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If repo root is missing, materialize the repo snapshot into --mount-root",
    )
    p.add_argument(
        "--refresh-mounted-repos",
        action="store_true",
        help="Re-materialize snapshots even if mounted repo folder already exists",
    )
    p.add_argument(
        "--cleanup-mounted-repos",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Delete repos that were materialized into --mount-root after evaluation completes",
    )

    p.add_argument(
        "--repo-root",
        default="",
        help="Absolute/local path to mounted source repo root (valid only with single --repo)",
    )
    p.add_argument(
        "--repo-roots-file",
        default="",
        help="JSON file mapping repo name -> local mounted repo root path",
    )
    p.add_argument(
        "--repo-root-base",
        default="/testbed",
        help="Base path used for fallback repo-root discovery (default: /testbed)",
    )

    p.add_argument("--max-read-lines", type=int, default=300)
    p.add_argument(
        "--repo-map-mode",
        choices=["repomap", "cheap_repomap", "none"],
        default="repomap",
        help="Repository map tool mode: full aider repomap, cheap python-file listing, or none",
    )
    p.add_argument(
        "--cheap-repomap-max-files",
        type=int,
        default=2000,
        help="Max python file paths returned when --repo-map-mode=cheap_repomap",
    )
    p.add_argument("--max-repair-rounds", type=int, default=2)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument(
        "--print-llm-trace",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print full LLM/tool interaction trace to console",
    )
    return p


def normalize_container_runtime_name(raw: Optional[str]) -> Optional[str]:
    normalized = str(raw or "").strip().lower()
    if normalized in {"", "none", "null"}:
        return None
    if normalized not in CONTAINER_RUNTIME_CHOICES:
        raise SystemExit(
            f"Unsupported container runtime '{raw}'. Supported: "
            f"{', '.join(CONTAINER_RUNTIME_CHOICES)}, none"
        )
    return normalized


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    args = build_parser().parse_args()

    if args.num_instances != "all":
        try:
            n = int(args.num_instances)
        except ValueError as exc:
            raise SystemExit("--num-instances must be 'all' or an integer") from exc
        if n < 0:
            raise SystemExit("--num-instances must be >= 0")

    if args.num_threads < 1:
        raise SystemExit("--num-threads must be >= 1")

    instances_root = Path(args.instances_root).resolve()
    if not instances_root.exists():
        raise SystemExit(f"Instances root not found: {instances_root}")

    repo_dirs = sorted(p.name for p in instances_root.iterdir() if p.is_dir())

    # Optional: restrict to specific instances via --task-ids ("<repo>/<instance>").
    task_filter: Dict[str, List[str]] = {}
    if args.task_ids:
        for raw in args.task_ids:
            for token in str(raw).split(","):
                token = token.strip().strip("/")
                if not token:
                    continue
                if "/" not in token:
                    raise SystemExit(
                        f"--task-ids entry must be '<repo>/<instance_id>', got: {token!r}"
                    )
                repo_name, instance_id = token.split("/", 1)
                repo_name = repo_name.strip()
                instance_id = instance_id.strip().strip("/")
                if not repo_name or not instance_id:
                    raise SystemExit(
                        f"--task-ids entry must be '<repo>/<instance_id>', got: {token!r}"
                    )
                task_filter.setdefault(repo_name, [])
                if instance_id not in task_filter[repo_name]:
                    task_filter[repo_name].append(instance_id)

    if task_filter:
        missing_repos = [r for r in task_filter if r not in repo_dirs]
        if missing_repos:
            raise SystemExit(
                f"Repo(s) {missing_repos} from --task-ids not found in {instances_root}. Available: {repo_dirs}"
            )
        if args.repo != "all" and (len(task_filter) != 1 or args.repo not in task_filter):
            raise SystemExit("--repo conflicts with --task-ids; omit --repo or keep them consistent")
        target_repos = sorted(task_filter.keys())
    elif args.repo == "all":
        target_repos = repo_dirs
    else:
        if args.repo not in repo_dirs:
            raise SystemExit(f"Repo '{args.repo}' not found in {instances_root}. Available: {repo_dirs}")
        target_repos = [args.repo]

    if args.repo_root and len(target_repos) != 1:
        raise SystemExit("--repo-root can only be used with a single --repo (not all)")

    repo_roots_map: Dict[str, str] = {}
    if args.repo_roots_file:
        mapping = load_json(Path(args.repo_roots_file).resolve())
        if not isinstance(mapping, dict):
            raise SystemExit("--repo-roots-file must contain a JSON object {repo: path}")
        repo_roots_map = {str(k): str(v) for k, v in mapping.items()}

    container_runtime_name = normalize_container_runtime_name(args.container_runtime)

    repos_images: Dict[str, str] = {}
    repo_snapshot_specs: Dict[str, Dict[str, str]] = {}
    if args.materialize_missing_from_image:
        if container_runtime_name is None:
            repo_snapshots_file = Path(args.repo_snapshots_file).resolve()
            if not repo_snapshots_file.exists():
                raise SystemExit(f"--repo-snapshots-file not found: {repo_snapshots_file}")
            repo_snapshot_specs = load_repo_snapshot_specs(repo_snapshots_file)
        else:
            repos_file = Path(args.repos_file).resolve()
            if not repos_file.exists():
                raise SystemExit(f"--repos-file not found: {repos_file}")
            data = load_json(repos_file)
            if not isinstance(data, dict):
                raise SystemExit(f"--repos-file must be a JSON object (repo->image): {repos_file}")
            repos_images = {str(k): str(v) for k, v in data.items()}

    model_segment = output_model_segment(args.provider, args.model)
    out_model_root = Path(args.output_root).resolve() / "llm" / args.provider / model_segment
    out_model_root.mkdir(parents=True, exist_ok=True)
    mount_root = Path(args.mount_root).resolve()
    container_runtime = (
        None if container_runtime_name is None else build_container_runtime(container_runtime_name)
    )

    resolved_answer_format = resolve_answer_format(args.answer_format, args.model)

    print(f"Provider:            {args.provider}")
    print(f"Model:               {args.model}")
    print(f"Answer format:       {resolved_answer_format} (--answer-format={args.answer_format})")
    print(f"Output root:         {out_model_root}")
    print(f"Target repos:        {' '.join(target_repos)}")
    print(f"Instances root:      {instances_root}")
    print(f"Repo root base:      {Path(args.repo_root_base).resolve()}")
    print(f"Mount root:          {mount_root}")
    print(f"Container runtime:   {container_runtime.name if container_runtime else 'none'}")
    print(f"Snapshot source:     {'git clone' if container_runtime is None else 'container image'}")
    print(f"Repo map mode:       {args.repo_map_mode}")
    if args.repo_map_mode == "cheap_repomap":
        print(f"Cheap map max files: {args.cheap_repomap_max_files}")
    print(f"Resume mode:         {'enabled' if args.resume else 'disabled'}")
    print("Mode:                host-side read-only (no code execution)")
    print()

    mounted_to_cleanup: List[Path] = []

    def materialize_repo_for_eval(repo_name: str, instances_dir: Path) -> Tuple[Path, bool]:
        if container_runtime is None:
            snapshot_spec = repo_snapshot_specs.get(repo_name)
            if not snapshot_spec:
                raise RuntimeError(
                    f"missing git snapshot mapping in {args.repo_snapshots_file}"
                )
            return materialize_repo_snapshot_from_git(
                repo_name=repo_name,
                snapshot_spec=snapshot_spec,
                mount_root=mount_root,
                refresh=args.refresh_mounted_repos,
            )

        image = repos_images.get(repo_name)
        if not image:
            raise RuntimeError(f"missing image mapping in {args.repos_file}")
        return materialize_repo_snapshot(
            repo_name=repo_name,
            image=image,
            repo_instances_dir=instances_dir,
            mount_root=mount_root,
            refresh=args.refresh_mounted_repos,
            container_runtime=container_runtime,
        )

    try:
        for repo_name in target_repos:
            instances_dir = instances_root / repo_name
            if not instances_dir.exists():
                print(f"[{repo_name}] Skipping: missing {instances_dir}")
                continue
            explicit_repo_root = args.repo_root if len(target_repos) == 1 else ""
            mapped_repo_root = repo_roots_map.get(repo_name, "")
            default_mount_repo_root = (mount_root / repo_name).resolve()

            # Default behavior: use .tmp mount root by repo name when no explicit/mapped repo root.
            if not explicit_repo_root and not mapped_repo_root:
                if (
                    default_mount_repo_root.exists()
                    and any(default_mount_repo_root.iterdir())
                    and not args.refresh_mounted_repos
                ):
                    repo_root = default_mount_repo_root
                    print(f"[{repo_name}] Using default mounted repo root: {repo_root}")
                elif args.materialize_missing_from_image:
                    try:
                        repo_root, created_now = materialize_repo_for_eval(repo_name, instances_dir)
                        if created_now:
                            mounted_to_cleanup.append(repo_root)
                    except Exception as mount_exc:
                        print(f"[{repo_name}] Skipping: failed to materialize snapshot: {mount_exc}")
                        continue
                else:
                    print(
                        f"[{repo_name}] Skipping: default mounted repo root missing and materialization disabled: "
                        f"{default_mount_repo_root}"
                    )
                    continue
            else:
                try:
                    repo_root = resolve_repo_root(
                        repo_name=repo_name,
                        repo_instances_dir=instances_dir,
                        explicit_repo_root=explicit_repo_root,
                        repo_roots_map=repo_roots_map,
                        repo_root_base=Path(args.repo_root_base).resolve(),
                    )
                except Exception as exc:
                    if not args.materialize_missing_from_image:
                        print(f"[{repo_name}] Skipping: {exc}")
                        continue
                    try:
                        repo_root, created_now = materialize_repo_for_eval(repo_name, instances_dir)
                        if created_now:
                            mounted_to_cleanup.append(repo_root)
                    except Exception as mount_exc:
                        print(f"[{repo_name}] Skipping: failed to materialize snapshot: {mount_exc}")
                        continue

            run_repo(
                provider=args.provider,
                model=args.model,
                repo_name=repo_name,
                repo_root=repo_root,
                instances_dir=instances_dir,
                out_repo_root=out_model_root / repo_name,
                num_instances=args.num_instances,
                max_read_lines=args.max_read_lines,
                repo_map_mode=args.repo_map_mode,
                cheap_repomap_max_files=args.cheap_repomap_max_files,
                temperature=args.temperature,
                max_repair_rounds=args.max_repair_rounds,
                print_llm_trace=args.print_llm_trace,
                resume=args.resume,
                resume_skip_errors=args.resume_skip_errors,
                num_threads=args.num_threads,
                answer_format=resolved_answer_format,
                only_instances=task_filter.get(repo_name),
            )
    finally:
        if args.cleanup_mounted_repos and mounted_to_cleanup:
            print()
            print("Cleaning up materialized repo snapshots...")
            for p in mounted_to_cleanup:
                try:
                    shutil.rmtree(p)
                    print(f"- removed {p}")
                except Exception as exc:
                    print(f"- failed to remove {p}: {exc}")

    print()
    print(f"Done. Outputs at: {out_model_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
