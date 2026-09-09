"""Configuration for a perturbation run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PerturbationConfig:
    """Everything tunable about a perturbation run."""

    # -- scope -----------------------------------------------------------------
    run_dir: Path                      # source run to perturb
    repo_key: str
    image: str
    output_root: Optional[Path] = None  # default: out/perturbation
    instance_ids: Optional[list[str]] = None
    max_instances: Optional[int] = None
    # Default source pool: instances that are intrinsically easy according to
    # the frozen combined-complexity report and that at least one Haiku/Fable
    # rollout matched. "easy" and "all" are explicit escape hatches for
    # experiments that do not want the validation gate.
    source_selection: str = "validated-easy"  # validated-easy | easy | all
    complexity_report: Optional[Path] = None
    # Candidates are scored with the same intrinsic metric after harvesting.
    # "medium" means leave the source report's easy bin; "hard" and
    # "very_hard" require progressively higher frozen bins; "increased" accepts
    # any positive combined-score delta; "none" restores historical behavior.
    complexity_target: str = "medium"  # increased | medium | hard | very_hard | none
    # Measurement runs can retain valid below-target candidates so their final
    # easy/medium/hard/very_hard distribution remains visible without censoring.
    keep_below_complexity_target: bool = False
    # A candidate should not trade one dimension away for gains elsewhere.
    require_all_metric_increases: bool = True
    # Only perturb instances the target model currently answers correctly. That
    # is the population where a flip is meaningful; with no evaluation report
    # available every instance is fair game.
    only_passing: bool = False
    sample_per_category: Optional[int] = None

    # -- proposer --------------------------------------------------------------
    # "llm"   : one API call with read-only repo tools (fast, cheap, cannot run
    #           anything, so invalid inputs are only caught later at harvest)
    # "agent" : a coding agent inside the repo container; it can RUN the test
    #           and fix a variant before proposing it
    proposer: str = "llm"
    agent: str = "cursor"              # cursor | claude_code | codex
    agent_model: str = "gpt-5.6-sol-medium"
    agent_timeout_s: int = 600         # one agent session; 10 min
    agent_parallel: int = 1            # containers running agent sessions
    provider: str = "openai"
    model: str = "gpt-5.6-sol"
    temperature: float = 1.0
    reasoning_effort: str = ""
    variants: int = 5                  # candidates proposed per instance
    threads: int = 4                   # concurrent proposal calls
    max_read_lines: int = 300
    repo_map_mode: str = "repomap"
    # Keep the AST structure checker available, but do not apply it unless the
    # caller explicitly requests an input-only experiment.
    enforce_structure: bool = False
    # Resume interrupted agent runs from output_root/logs/*/variants/*.py.
    reuse_staged_variants: bool = False

    # -- optional flip stage (target model) ------------------------------------
    # The model the benchmark is measuring. A perturbation is interesting when
    # this model answered the ORIGINAL correctly but fails the perturbed one.
    # This evaluation-guided mode is deliberately opt-in.  Intrinsic combined
    # complexity is the default perturbation objective.
    flip_check: bool = False
    target_provider: str = ""          # defaults to the proposer's provider
    target_model: str = ""             # defaults to the proposer's model
    target_effort: str = "low"
    target_temperature: float = 0.0
    target_max_read_lines: int = 250
    float_tol: float = 1e-6
    # Keep only candidates that actually flip the target model.
    require_flip: bool = False
    # Evaluate the original too when the source run has no usable verdict for it.
    baseline_check: bool = True

    # -- feedback loop ---------------------------------------------------------
    feedback_iterations: int = 0       # 0 = single-shot proposals only

    # -- execution -------------------------------------------------------------
    harvest_timeout: int = 900
    parallel_harvest: int = 1          # harvests share a container name; keep 1
    screen: bool = True                # drop candidates failing screening rules
    keep_all: bool = False             # keep even candidates whose oracle matches

    # -- misc ------------------------------------------------------------------
    progress: bool = True
    env_file: Optional[Path] = None
    container_runtime: str = "docker"

    @property
    def flip_provider(self) -> str:
        return self.target_provider or self.provider

    @property
    def flip_model(self) -> str:
        return self.target_model or self.model

    def new_instance_id(self, original_id: str, index: int) -> str:
        return f"{original_id}__pert_llm_s{index}"

    def feedback_instance_id(self, base_id: str, iteration: int) -> str:
        return f"{base_id}__fb_i{iteration}"
