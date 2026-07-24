"""LLM (non-agent) inference, ported from RepoBehave's evaluation_scripts/llm_eval.

Reuses the provider tool-calling runner, read-only repo tools, container repo
snapshotting, cost accounting (provider_model_costs.json), and the per-instance
run/repair/score flow. The solver_llm validator drives run_single_instance over
a repo snapshot to answer generated instances with a raw LLM instead of an agent.
"""

from .run_llm_repomap_eval_host import (
    compute_usage_cost_for_model,
    load_model_costs_db,
    resolve_model_cost_entry,
    run_single_instance,
)
from .container_runtime import build_container_runtime, CONTAINER_RUNTIME_CHOICES

__all__ = [
    "run_single_instance",
    "compute_usage_cost_for_model",
    "resolve_model_cost_entry",
    "load_model_costs_db",
    "build_container_runtime",
    "CONTAINER_RUNTIME_CHOICES",
]
