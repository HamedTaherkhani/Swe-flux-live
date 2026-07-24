from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

try:
    from .repo_tools import TOOL_DESCRIPTIONS, TOOL_INPUT_SCHEMAS
except ImportError:
    from repo_tools import TOOL_DESCRIPTIONS, TOOL_INPUT_SCHEMAS

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

DEFAULT_GPT_OSS_20B_REQUEST_CAP = int(os.environ.get("REPOBEHAVE_GPT_OSS_20B_MAX_REQUESTS", "25"))
DEFAULT_GEMMA_4_31B_REQUEST_CAP = int(os.environ.get("REPOBEHAVE_GEMMA_4_31B_MAX_REQUESTS", "17"))
DEFAULT_GEMINI_31_PRO_PREVIEW_REQUEST_CAP = int(
    os.environ.get("REPOBEHAVE_GEMINI_31_PRO_PREVIEW_MAX_REQUESTS", "35")
)
# Per-request timeout for Gemini calls (default 6 minutes). A timeout is NOT retried.
DEFAULT_GEMINI_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("REPOBEHAVE_GEMINI_REQUEST_TIMEOUT_SECONDS", "600")
)
# Backoff applied when the Gemini API returns a rate-limit (429 / RESOURCE_EXHAUSTED) error.
DEFAULT_GEMINI_RATE_LIMIT_BACKOFF_SECONDS = float(
    os.environ.get("REPOBEHAVE_GEMINI_RATE_LIMIT_BACKOFF_SECONDS", "60")
)
DEFAULT_GEMINI_RATE_LIMIT_MAX_RETRIES = int(
    os.environ.get("REPOBEHAVE_GEMINI_RATE_LIMIT_MAX_RETRIES", "10")
)
DEFAULT_FIREWORKS_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("REPOBEHAVE_FIREWORKS_REQUEST_TIMEOUT_SECONDS", "360")
)
DEFAULT_FIREWORKS_MAX_RETRIES = int(os.environ.get("REPOBEHAVE_FIREWORKS_MAX_RETRIES", "0"))
DEFAULT_VLLM_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("REPOBEHAVE_VLLM_REQUEST_TIMEOUT_SECONDS", "600")
)
TOOL_PHASE_DONE_SENTINEL = "DONE_WITH_FILE_READING"
TOOL_PHASE_REMINDER_PROMPT = (
    "Do not answer yet. If you still need repository context, continue with tool calls. "
    f"If you are completely done using tools, reply with exactly {TOOL_PHASE_DONE_SENTINEL}."
)


FINAL_JSON_PROMPT = (
    f"You already signaled {TOOL_PHASE_DONE_SENTINEL}. "
    "Tool phase is closed. Return ONLY the final JSON answer object matching the earlier template. "
    "Do not output markdown or explanations."
)

# ---------------------------------------------------------------------------
# Reasoning answer format (gemma4 / reasoning-format runs only)
# ---------------------------------------------------------------------------
# Used when the student/model is trained to derive the answer before emitting
# JSON. Kept here as the single source of truth so the training-time prompts in
# fine-tuning/create_sft_dataset.py and the eval-time prompts in
# run_llm_repomap_eval_host.py stay byte-for-byte in lockstep. The default JSON
# format above is untouched, so non-reasoning models behave exactly as before.
ANSWER_SENTINEL = "## Answer"

# Rules 7-8 of the system prompt in reasoning mode. The first six rules are
# identical to the JSON-mode prompt; only the final-answer contract changes.
ANSWER_RULES_REASONING = (
    "7. After the follow-up prompt closes the tool phase, first write a brief "
    "derivation (a few sentences) explaining how the code you read determines "
    f"the answer, then write '{ANSWER_SENTINEL}' on its own line followed by "
    "exactly one JSON object matching template_answer keys and value types.\n"
    f"8. Put only the JSON object after the '{ANSWER_SENTINEL}' line — no markdown "
    "code fences, and nothing after the JSON."
)

FINAL_REASONING_PROMPT = (
    f"You already signaled {TOOL_PHASE_DONE_SENTINEL}. Tool phase is closed. "
    "First write a brief derivation showing how the code you read determines the "
    f"answer, then write '{ANSWER_SENTINEL}' on its own line followed by exactly one "
    "JSON object matching the earlier template. Put only the JSON after that line — "
    "no markdown code fences, and nothing after the JSON."
)

DEFAULT_TOOL_NAMES = ["get_repo_map", "list_dir", "read_file"]


def _is_timeout_error(exc: BaseException) -> bool:
    """Detect a request/read timeout so it can be left un-retried."""
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (408, 504):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return "timed out" in text or "timeout" in text


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Best-effort detection of a Gemini rate-limit / quota error (HTTP 429)."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429:
        return True
    status = str(getattr(exc, "status", "") or "")
    if status.upper() in {"RESOURCE_EXHAUSTED", "TOO_MANY_REQUESTS"}:
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    needles = ("resource_exhausted", "rate limit", "rate-limit", "ratelimit", "too many requests", "quota")
    if any(n in text for n in needles):
        return True
    return "429" in text


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


def _empty_usage(provider: str, model: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"provider": provider, "model": model}
    for key in USAGE_NUMERIC_KEYS:
        payload[key] = 0
    return payload


def _normalize_protocol_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).strip(" .").lower()


def _is_tool_phase_done_text(text: str) -> bool:
    normalized = _normalize_protocol_text(text)
    accepted = [
        TOOL_PHASE_DONE_SENTINEL.lower(),
        TOOL_PHASE_DONE_SENTINEL.lower().replace("_", " "),
        "i am done with file reading",
        "i'm done with file reading",
        "done with file reading",
        "done reading files",
        "finished reading files",
        "finished with file reading",
    ]
    for marker in accepted:
        if normalized == marker:
            return True
        if normalized.startswith(marker):
            suffix = normalized[len(marker):].lstrip()
            if not suffix or suffix[0] in '{[(:,-':
                return True
    return False


class ProviderRunner:
    def __init__(
        self,
        provider: str,
        model: str,
        temperature: float = 0.0,
        trace: Optional[Callable[[str], None]] = None,
        final_answer_prompt: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.trace = trace
        # The follow-up prompt that closes the tool phase and requests the final
        # answer. Defaults to bare-JSON (unchanged for all existing models); the
        # caller passes FINAL_REASONING_PROMPT for reasoning-format (gemma4) runs.
        self.final_answer_prompt = final_answer_prompt or FINAL_JSON_PROMPT
        self._usage = _empty_usage(provider, model)

    def _t(self, msg: str) -> None:
        if self.trace:
            self.trace(msg)

    @staticmethod
    def _get_field(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _inc_usage(self, key: str, value: Any) -> None:
        n = _to_int_or_none(value)
        if n is None:
            return
        self._usage[key] = int(self._usage.get(key, 0)) + max(0, n)

    def _record_usage(self, source: str, usage_obj: Any) -> None:
        self._inc_usage("requests", 1)
        if usage_obj is None:
            self._inc_usage("usage_missing_requests", 1)
            return

        g = self._get_field
        if source.startswith("openai-chat"):
            self._inc_usage("input_tokens", g(usage_obj, "prompt_tokens"))
            self._inc_usage("output_tokens", g(usage_obj, "completion_tokens"))
            self._inc_usage("total_tokens", g(usage_obj, "total_tokens"))
            pdetails = g(usage_obj, "prompt_tokens_details")
            cdetails = g(usage_obj, "completion_tokens_details")
            self._inc_usage("cached_input_tokens", g(pdetails, "cached_tokens"))
            self._inc_usage("reasoning_tokens", g(cdetails, "reasoning_tokens"))
        elif source.startswith("openai-responses"):
            self._inc_usage("input_tokens", g(usage_obj, "input_tokens"))
            self._inc_usage("output_tokens", g(usage_obj, "output_tokens"))
            self._inc_usage("total_tokens", g(usage_obj, "total_tokens"))
            idetails = g(usage_obj, "input_tokens_details")
            odetails = g(usage_obj, "output_tokens_details")
            self._inc_usage("cached_input_tokens", g(idetails, "cached_tokens"))
            self._inc_usage("cached_input_tokens", g(idetails, "cached_input_tokens"))
            self._inc_usage("reasoning_tokens", g(odetails, "reasoning_tokens"))
        elif source.startswith("gemini"):
            self._inc_usage("input_tokens", g(usage_obj, "prompt_token_count"))
            self._inc_usage("output_tokens", g(usage_obj, "candidates_token_count"))
            self._inc_usage("total_tokens", g(usage_obj, "total_token_count"))
            self._inc_usage("cached_input_tokens", g(usage_obj, "cached_content_token_count"))
        elif source.startswith("anthropic"):
            self._inc_usage("input_tokens", g(usage_obj, "input_tokens"))
            self._inc_usage("output_tokens", g(usage_obj, "output_tokens"))
            self._inc_usage("cache_creation_input_tokens", g(usage_obj, "cache_creation_input_tokens"))
            self._inc_usage("cache_read_input_tokens", g(usage_obj, "cache_read_input_tokens"))
            # Anthropic cache read tokens are input-side cached tokens.
            self._inc_usage("cached_input_tokens", g(usage_obj, "cache_read_input_tokens"))
        else:
            self._inc_usage("input_tokens", g(usage_obj, "input_tokens"))
            self._inc_usage("output_tokens", g(usage_obj, "output_tokens"))
            self._inc_usage("total_tokens", g(usage_obj, "total_tokens"))

        if int(self._usage.get("total_tokens", 0)) <= 0:
            self._usage["total_tokens"] = int(self._usage.get("input_tokens", 0)) + int(
                self._usage.get("output_tokens", 0)
            )

    def usage_summary(self) -> Dict[str, Any]:
        out = dict(self._usage)
        if int(out.get("total_tokens", 0)) <= 0:
            out["total_tokens"] = int(out.get("input_tokens", 0)) + int(out.get("output_tokens", 0))
        return out

    def _request_cap_for_model(self) -> Optional[int]:
        lower = (self.model or "").strip().lower()
        if not lower:
            return None

        # Treat separators consistently across providers/output naming variants.
        normalized = lower.replace("_", "-")

        if "gpt-oss-20b" in normalized:
            return max(1, int(DEFAULT_GPT_OSS_20B_REQUEST_CAP))
        if "gemma-4" in normalized or "local-vllm" in normalized:
            return max(1, int(DEFAULT_GEMMA_4_31B_REQUEST_CAP))
        if "gemini-3.1-pro-preview" in normalized:
            return max(1, int(DEFAULT_GEMINI_31_PRO_PREVIEW_REQUEST_CAP))
        return None

    def _is_request_cap_reached(self, request_counter: List[int]) -> bool:
        cap = self._request_cap_for_model()
        if cap is None:
            return False
        return int(request_counter[0]) >= cap

    def _check_request_cap(self, request_counter: List[int]) -> None:
        if not self._is_request_cap_reached(request_counter):
            return
        cap = self._request_cap_for_model()
        if int(request_counter[0]) >= cap:
            msg = (
                f"Aborting run: reached hard request cap ({cap}) for model '{self.model}'. "
                "This model may be stuck in a tool-calling loop."
            )
            self._t(f"[cap] {msg}")
            raise RuntimeError(msg)

    @staticmethod
    def _extract_openai_responses_text(response: Any) -> str:
        def _g(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        text = getattr(response, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text

        text_parts: List[str] = []
        for item in list(getattr(response, "output", []) or []):
            if _g(item, "type", "") != "message":
                continue
            for part in list(_g(item, "content", []) or []):
                ptype = _g(part, "type", "")
                if ptype in {"output_text", "text"}:
                    value = _g(part, "text", "")
                    if value:
                        text_parts.append(str(value))
        return "\n".join(x for x in text_parts if x).strip()

    def run(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tool_callback,
        enable_tools: bool = True,
        tool_names: Optional[List[str]] = None,
    ) -> str:
        active_tool_names = list(tool_names) if tool_names is not None else list(DEFAULT_TOOL_NAMES)
        if self.provider == "openai":
            return self._run_openai(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_callback=tool_callback,
                enable_tools=enable_tools,
                tool_names=active_tool_names,
            )
        if self.provider == "gemini":
            return self._run_gemini(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_callback=tool_callback,
                enable_tools=enable_tools,
                tool_names=active_tool_names,
            )
        if self.provider == "anthropic":
            return self._run_anthropic(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_callback=tool_callback,
                enable_tools=enable_tools,
                tool_names=active_tool_names,
            )
        if self.provider == "fireworks":
            return self._run_fireworks(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_callback=tool_callback,
                enable_tools=enable_tools,
                tool_names=active_tool_names,
            )
        if self.provider == "openrouter":
            return self._run_openrouter(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_callback=tool_callback,
                enable_tools=enable_tools,
                tool_names=active_tool_names,
            )
        if self.provider == "vllm":
            return self._run_vllm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_callback=tool_callback,
                enable_tools=enable_tools,
                tool_names=active_tool_names,
            )
        raise ValueError(f"Unsupported provider: {self.provider}")

    def _run_openai(
        self, *, system_prompt: str, user_prompt: str, tool_callback, enable_tools: bool, tool_names: List[str]
    ) -> str:
        import openai

        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("openai_api_key")
        if not hasattr(openai, "OpenAI"):
            raise RuntimeError(
                "Modern OpenAI SDK required. Install or upgrade the 'openai' package in the host environment."
            )

        client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()
        request_counter = [0]
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        responses_err: Optional[Exception] = None
        try:
            return self._run_openai_responses(
                client=client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_callback=tool_callback,
                enable_tools=enable_tools,
                tool_names=tool_names,
                request_counter=request_counter,
            )
        except Exception as exc:
            responses_err = exc
            self._t(
                f"[openai] responses fallback triggered: {exc.__class__.__name__}: {exc}"
            )

        try:
            return self._run_openai_chat(
                client=client,
                messages=messages,
                tool_callback=tool_callback,
                enable_tools=enable_tools,
                tool_names=tool_names,
                request_counter=request_counter,
            )
        except Exception as chat_exc:
            if responses_err is None:
                raise
            raise RuntimeError(
                "OpenAI run failed with both endpoints: "
                f"responses=({responses_err.__class__.__name__}: {responses_err}); "
                f"chat.completions=({chat_exc.__class__.__name__}: {chat_exc})"
            ) from chat_exc

    def _run_openai_chat(
        self,
        *,
        client,
        messages: List[Dict[str, Any]],
        tool_callback,
        enable_tools: bool,
        tool_names: Optional[List[str]] = None,
        trace_label: str = "openai-chat",
        usage_source: str = "openai-chat",
        request_counter: Optional[List[int]] = None,
        enforce_request_cap: bool = True,
    ) -> str:
        counter = request_counter if request_counter is not None else [0]
        if not enable_tools:
            if enforce_request_cap:
                self._check_request_cap(counter)
            self._t(f"[{trace_label}] request")
            resp = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
            )
            counter[0] = int(counter[0]) + 1
            self._record_usage(usage_source, getattr(resp, "usage", None))
            msg = resp.choices[0].message
            self._t(f"[{trace_label}] assistant: {msg.content or ''}")
            return msg.content or ""

        active_tool_names = list(tool_names) if tool_names is not None else list(DEFAULT_TOOL_NAMES)
        if not active_tool_names:
            return self._run_openai_chat(
                client=client,
                messages=messages,
                tool_callback=tool_callback,
                enable_tools=False,
                trace_label=trace_label,
                usage_source=usage_source,
                request_counter=counter,
                enforce_request_cap=enforce_request_cap,
            )

        tools = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": TOOL_DESCRIPTIONS[name],
                    "parameters": TOOL_INPUT_SCHEMAS[name],
                },
            }
            for name in active_tool_names
        ]

        while True:
            if self._is_request_cap_reached(counter):
                self._t(f"[{trace_label}] request cap reached during tool phase; forcing final JSON request")
                messages.append({"role": "user", "content": self.final_answer_prompt})
                return self._run_openai_chat(
                    client=client,
                    messages=messages,
                    tool_callback=tool_callback,
                    enable_tools=False,
                    trace_label=trace_label,
                    usage_source=usage_source,
                    request_counter=counter,
                    enforce_request_cap=False,
                    tool_names=active_tool_names,
                )
            self._t(f"[{trace_label}] request")
            request_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": self.temperature,
            }
            try:
                resp = client.chat.completions.create(**request_kwargs)
            except Exception as exc:
                err_text = str(exc)
                auto_tool_choice_err = (
                    '"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set'
                )
                if "vllm" in trace_label and auto_tool_choice_err in err_text:
                    # Older/misconfigured vLLM servers may reject explicit tool_choice="auto".
                    # Retry once without the explicit tool_choice key so runs can continue.
                    self._t(
                        f"[{trace_label}] server rejected tool_choice=auto; retrying without explicit tool_choice. "
                        "For reliable tool-calling, start vLLM with --enable-auto-tool-choice "
                        "and --tool-call-parser <parser>."
                    )
                    request_kwargs.pop("tool_choice", None)
                    resp = client.chat.completions.create(**request_kwargs)
                else:
                    raise
            counter[0] = int(counter[0]) + 1
            self._record_usage(usage_source, getattr(resp, "usage", None))
            msg = resp.choices[0].message
            self._t(f"[{trace_label}] assistant: {msg.content or ''}")

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    self._t(f"[{trace_label}] tool_call {tc.function.name} args={tc.function.arguments}")
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                    }
                )

                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    args_raw = tc.function.arguments or "{}"
                    try:
                        args = json.loads(args_raw)
                    except json.JSONDecodeError:
                        args = {}
                    result = tool_callback(fn_name, args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": fn_name,
                            "content": json.dumps(result),
                        }
                    )
                continue

            content = msg.content or ""
            messages.append({"role": "assistant", "content": content})
            if _is_tool_phase_done_text(content):
                self._t(f"[{trace_label}] tool phase complete")
                messages.append({"role": "user", "content": self.final_answer_prompt})
                return self._run_openai_chat(
                    client=client,
                    messages=messages,
                    tool_callback=tool_callback,
                    enable_tools=False,
                    trace_label=trace_label,
                    usage_source=usage_source,
                    request_counter=counter,
                    enforce_request_cap=False,
                    tool_names=active_tool_names,
                )

            self._t(f"[{trace_label}] assistant did not signal tool completion; reminding")
            messages.append({"role": "user", "content": TOOL_PHASE_REMINDER_PROMPT})

    def _run_fireworks(
        self, *, system_prompt: str, user_prompt: str, tool_callback, enable_tools: bool, tool_names: List[str]
    ) -> str:
        import openai

        api_key = (
            os.environ.get("FIREWORKS_API_KEY")
            or os.environ.get("fireworks_api_key")
            or os.environ.get("FIREWORKS_API_TOKEN")
        )
        if not api_key:
            raise RuntimeError(
                "Fireworks API key not found. Set FIREWORKS_API_KEY (or fireworks_api_key) in your environment/.env."
            )
        if not hasattr(openai, "OpenAI"):
            raise RuntimeError(
                "Modern OpenAI SDK required. Install or upgrade the 'openai' package in the host environment."
            )

        base_url = (
            os.environ.get("FIREWORKS_BASE_URL")
            or os.environ.get("FIREWORKS_API_BASE")
            or "https://api.fireworks.ai/inference/v1"
        )
        timeout_seconds = max(1.0, float(DEFAULT_FIREWORKS_REQUEST_TIMEOUT_SECONDS))
        max_retries = max(0, int(DEFAULT_FIREWORKS_MAX_RETRIES))
        client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        request_counter = [0]
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._run_openai_chat(
            client=client,
            messages=messages,
            tool_callback=tool_callback,
            enable_tools=enable_tools,
            tool_names=tool_names,
            trace_label="fireworks-chat",
            usage_source="openai-chat-fireworks",
            request_counter=request_counter,
        )

    def _run_openrouter(
        self, *, system_prompt: str, user_prompt: str, tool_callback, enable_tools: bool, tool_names: List[str]
    ) -> str:
        import openai

        api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("openrouter_api_key")
        if not api_key:
            raise RuntimeError(
                "OpenRouter API key not found. Set OPENROUTER_API_KEY (or openrouter_api_key) in your environment/.env."
            )
        if not hasattr(openai, "OpenAI"):
            raise RuntimeError(
                "Modern OpenAI SDK required. Install or upgrade the 'openai' package in the host environment."
            )

        base_url = (
            os.environ.get("OPENROUTER_BASE_URL")
            or os.environ.get("OPENROUTER_API_BASE")
            or "https://openrouter.ai/api/v1"
        )
        default_headers: Dict[str, str] = {}
        http_referer = os.environ.get("OPENROUTER_HTTP_REFERER") or os.environ.get("OPENROUTER_REFERER")
        x_title = os.environ.get("OPENROUTER_X_TITLE") or os.environ.get("OPENROUTER_TITLE")
        if http_referer:
            default_headers["HTTP-Referer"] = http_referer
        if x_title:
            default_headers["X-Title"] = x_title

        client_kwargs: Dict[str, Any] = {"api_key": api_key, "base_url": base_url}
        if default_headers:
            client_kwargs["default_headers"] = default_headers
        client = openai.OpenAI(**client_kwargs)

        request_counter = [0]
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._run_openai_chat(
            client=client,
            messages=messages,
            tool_callback=tool_callback,
            enable_tools=enable_tools,
            tool_names=tool_names,
            trace_label="openrouter-chat",
            usage_source="openai-chat-openrouter",
            request_counter=request_counter,
        )

    def _run_vllm(
        self, *, system_prompt: str, user_prompt: str, tool_callback, enable_tools: bool, tool_names: List[str]
    ) -> str:
        import openai

        # vLLM exposes an OpenAI-compatible Chat Completions endpoint.
        base_url = (
            os.environ.get("VLLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("OPENAI_API_BASE")
            or "http://127.0.0.1:8000/v1"
        )
        api_key = (
            os.environ.get("VLLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("openai_api_key")
            or "EMPTY"
        )
        timeout_seconds = max(1.0, float(DEFAULT_VLLM_REQUEST_TIMEOUT_SECONDS))
        client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )
        request_counter = [0]
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._run_openai_chat(
            client=client,
            messages=messages,
            tool_callback=tool_callback,
            enable_tools=enable_tools,
            tool_names=tool_names,
            trace_label="vllm-chat",
            usage_source="openai-chat-vllm",
            request_counter=request_counter,
        )

    def _run_openai_responses(
        self,
        *,
        client,
        system_prompt: str,
        user_prompt: str,
        tool_callback,
        enable_tools: bool,
        tool_names: Optional[List[str]] = None,
        request_counter: Optional[List[int]] = None,
        enforce_request_cap: bool = True,
    ) -> str:
        counter = request_counter if request_counter is not None else [0]

        def _responses_create(*, bypass_cap: bool = False, **kwargs):
            if not bypass_cap and enforce_request_cap:
                self._check_request_cap(counter)
            resp = client.responses.create(**kwargs)
            counter[0] = int(counter[0]) + 1
            return resp

        def _g(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        active_tool_names = list(tool_names) if tool_names is not None else list(DEFAULT_TOOL_NAMES)
        tools = [
            {
                "type": "function",
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": TOOL_INPUT_SCHEMAS[name],
            }
            for name in active_tool_names
        ]

        create_kwargs: Dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
            ],
            "temperature": self.temperature,
        }
        if enable_tools and tools:
            create_kwargs["tools"] = tools

        response = _responses_create(bypass_cap=not enforce_request_cap, **create_kwargs)
        self._record_usage("openai-responses", getattr(response, "usage", None))
        if not enable_tools:
            text = self._extract_openai_responses_text(response)
            self._t(f"[openai-responses] assistant: {text}")
            return text

        def _force_final_from_cap(current_response: Any) -> str:
            self._t("[openai-responses] request cap reached during tool phase; forcing final JSON request")
            final_response = _responses_create(
                model=self.model,
                previous_response_id=getattr(current_response, "id", None),
                input=[
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": self.final_answer_prompt}],
                    }
                ],
                temperature=self.temperature,
                bypass_cap=True,
            )
            self._record_usage("openai-responses", getattr(final_response, "usage", None))
            final_text = self._extract_openai_responses_text(final_response)
            self._t(f"[openai-responses] assistant: {final_text}")
            return final_text

        while True:
            self._t("[openai-responses] request")
            output_items = list(getattr(response, "output", []) or [])
            function_calls = [item for item in output_items if _g(item, "type", "") == "function_call"]

            if function_calls:
                tool_outputs: List[Dict[str, Any]] = []
                for fc in function_calls:
                    fn_name = str(_g(fc, "name", "") or "")
                    args_raw = str(_g(fc, "arguments", "") or "{}")
                    self._t(f"[openai-responses] function_call {fn_name} args={args_raw}")
                    try:
                        args = json.loads(args_raw)
                    except json.JSONDecodeError:
                        args = {}
                    result = tool_callback(fn_name, args)
                    call_id = str(_g(fc, "call_id", "") or _g(fc, "id", "") or "")
                    tool_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(result),
                        }
                    )

                if self._is_request_cap_reached(counter):
                    return _force_final_from_cap(response)
                response = _responses_create(
                    model=self.model,
                    previous_response_id=getattr(response, "id", None),
                    input=tool_outputs,
                    tools=tools,
                    temperature=self.temperature,
                )
                self._record_usage("openai-responses", getattr(response, "usage", None))
                continue

            text = self._extract_openai_responses_text(response)
            self._t(f"[openai-responses] assistant: {text}")
            if _is_tool_phase_done_text(text):
                self._t("[openai-responses] tool phase complete")
                response = _responses_create(
                    model=self.model,
                    previous_response_id=getattr(response, "id", None),
                    input=[
                        {
                            "role": "user",
                            "content": [{"type": "input_text", "text": self.final_answer_prompt}],
                        }
                    ],
                    temperature=self.temperature,
                    bypass_cap=True,
                )
                self._record_usage("openai-responses", getattr(response, "usage", None))
                final_text = self._extract_openai_responses_text(response)
                self._t(f"[openai-responses] assistant: {final_text}")
                return final_text

            self._t("[openai-responses] assistant did not signal tool completion; reminding")
            if self._is_request_cap_reached(counter):
                return _force_final_from_cap(response)
            response = _responses_create(
                model=self.model,
                previous_response_id=getattr(response, "id", None),
                input=[
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": TOOL_PHASE_REMINDER_PROMPT}],
                    }
                ],
                tools=tools,
                temperature=self.temperature,
            )
            self._record_usage("openai-responses", getattr(response, "usage", None))

    def _gemini_generate(self, client: Any, **kwargs: Any) -> Any:
        """Call Gemini generate_content, retrying with a fixed backoff on rate-limit errors."""
        backoff = max(0.0, DEFAULT_GEMINI_RATE_LIMIT_BACKOFF_SECONDS)
        max_retries = max(0, DEFAULT_GEMINI_RATE_LIMIT_MAX_RETRIES)
        attempt = 0
        while True:
            try:
                return client.models.generate_content(**kwargs)
            except Exception as exc:
                # Timeouts are never retried on the same instance.
                if _is_timeout_error(exc):
                    print(f"[gemini] request timed out ({type(exc).__name__}); not retrying: {exc}", flush=True)
                    self._t(f"[gemini] request timed out; not retrying: {exc}")
                    raise
                if not _is_rate_limit_error(exc) or attempt >= max_retries:
                    raise
                attempt += 1
                msg = (
                    f"[gemini] rate-limit error ({type(exc).__name__}); "
                    f"backing off {backoff:.0f}s then retry {attempt}/{max_retries}: {exc}"
                )
                # Always surface to the console, and also feed the trace.
                print(msg, flush=True)
                self._t(msg)
                time.sleep(backoff)

    def _run_gemini(
        self, *, system_prompt: str, user_prompt: str, tool_callback, enable_tools: bool, tool_names: List[str]
    ) -> str:
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        # HttpOptions.timeout is in milliseconds. Default 6 minutes; a timeout is not retried.
        timeout_ms = int(max(1.0, float(DEFAULT_GEMINI_REQUEST_TIMEOUT_SECONDS)) * 1000)
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_ms),
        )

        fn_decls = [
            types.FunctionDeclaration(
                name=name,
                description=TOOL_DESCRIPTIONS[name],
                parameters=TOOL_INPUT_SCHEMAS[name],
            )
            for name in tool_names
        ]

        contents: List[Any] = [types.UserContent(parts=[types.Part.from_text(text=user_prompt)])]
        if enable_tools and not tool_names:
            enable_tools = False

        if not enable_tools:
            self._t("[gemini] request")
            resp = self._gemini_generate(
                client,
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=self.temperature,
                ),
            )
            self._record_usage("gemini", getattr(resp, "usage_metadata", None))
            self._t(f"[gemini] assistant: {resp.text or ''}")
            return resp.text or ""

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=fn_decls)],
            temperature=self.temperature,
        )

        while True:
            self._t("[gemini] request")
            resp = self._gemini_generate(
                client,
                model=self.model,
                contents=contents,
                config=config,
            )
            self._record_usage("gemini", getattr(resp, "usage_metadata", None))

            function_calls = list(resp.function_calls or [])
            if function_calls:
                candidates = list(getattr(resp, "candidates", []) or [])
                candidate_content = getattr(candidates[0], "content", None) if candidates else None
                if candidate_content is not None:
                    # Preserve thought_signature and any other metadata in the model's functionCall parts.
                    contents.append(candidate_content)

                function_response_parts: List[Any] = []
                for fc in function_calls:
                    fn_name = fc.name or ""
                    fn_args = fc.args or {}
                    self._t(f"[gemini] function_call {fn_name} args={json.dumps(fn_args, ensure_ascii=False)}")
                    if candidate_content is None:
                        # Fallback for unexpected response shapes without candidates/content.
                        contents.append(
                            types.ModelContent(
                                parts=[types.Part.from_function_call(name=fn_name, args=fn_args)]
                            )
                        )
                    result = tool_callback(fn_name, fn_args)
                    function_response_parts.append(
                        types.Part.from_function_response(name=fn_name, response=result)
                    )

                if function_response_parts:
                    contents.append(types.UserContent(parts=function_response_parts))
                continue

            text = resp.text or ""
            self._t(f"[gemini] assistant: {text}")
            if text:
                contents.append(types.ModelContent(parts=[types.Part.from_text(text=text)]))
            if _is_tool_phase_done_text(text):
                self._t("[gemini] tool phase complete")
                contents.append(types.UserContent(parts=[types.Part.from_text(text=self.final_answer_prompt)]))
                final_resp = self._gemini_generate(
                    client,
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=self.temperature,
                    ),
                )
                self._record_usage("gemini", getattr(final_resp, "usage_metadata", None))
                self._t(f"[gemini] assistant: {final_resp.text or ''}")
                return final_resp.text or ""

            self._t("[gemini] assistant did not signal tool completion; reminding")
            contents.append(types.UserContent(parts=[types.Part.from_text(text=TOOL_PHASE_REMINDER_PROMPT)]))

    def _run_anthropic(
        self, *, system_prompt: str, user_prompt: str, tool_callback, enable_tools: bool, tool_names: List[str]
    ) -> str:
        import anthropic

        client = anthropic.Anthropic()
        if enable_tools and not tool_names:
            enable_tools = False
        tools = [
            {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "input_schema": TOOL_INPUT_SCHEMAS[name],
            }
            for name in tool_names
        ]

        messages: List[Dict[str, Any]] = [{"role": "user", "content": user_prompt}]

        if not enable_tools:
            self._t("[anthropic] request")
            resp = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                temperature=self.temperature,
            )
            self._record_usage("anthropic", getattr(resp, "usage", None))
            text_parts = [block.text for block in resp.content if block.type == "text"]
            self._t(f"[anthropic] assistant: {' '.join(text_parts).strip()}")
            return "\n".join(text_parts).strip()

        while True:
            self._t("[anthropic] request")
            resp = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=tools,
                temperature=self.temperature,
            )
            self._record_usage("anthropic", getattr(resp, "usage", None))

            tool_uses = [block for block in resp.content if block.type == "tool_use"]
            if tool_uses:
                assistant_blocks = [b.model_dump() for b in resp.content]
                for block in tool_uses:
                    self._t(
                        f"[anthropic] tool_use {block.name} args={json.dumps(block.input or {}, ensure_ascii=False)}"
                    )
                messages.append({"role": "assistant", "content": assistant_blocks})

                tool_results = []
                for block in tool_uses:
                    result = tool_callback(block.name, block.input or {})
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )
                messages.append({"role": "user", "content": tool_results})
                continue

            assistant_blocks = [b.model_dump() for b in resp.content]
            messages.append({"role": "assistant", "content": assistant_blocks})
            text_parts = [block.text for block in resp.content if block.type == "text"]
            text = "\n".join(text_parts).strip()
            self._t(f"[anthropic] assistant: {' '.join(text_parts).strip()}")
            if _is_tool_phase_done_text(text):
                self._t("[anthropic] tool phase complete")
                messages.append({"role": "user", "content": self.final_answer_prompt})
                final_resp = client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=messages,
                    temperature=self.temperature,
                )
                self._record_usage("anthropic", getattr(final_resp, "usage", None))
                final_text_parts = [block.text for block in final_resp.content if block.type == "text"]
                self._t(f"[anthropic] assistant: {' '.join(final_text_parts).strip()}")
                return "\n".join(final_text_parts).strip()

            self._t("[anthropic] assistant did not signal tool completion; reminding")
            messages.append({"role": "user", "content": TOOL_PHASE_REMINDER_PROMPT})
