"""LLM input perturbation: turn solved instances into harder ones.

Ported from the RepoBehave `perturbation` package, LLM proposer only (the AST
boundary strategies are deliberately not carried over).

The proposer hardens concrete test inputs while keeping the runtime question,
parser contract, and test structure meaningful, then re-harvests a fresh oracle
by executing the new test. An opt-in legacy AST policy additionally requires an
exact definition/call multiset match. The harvest pipeline is its own validator:
a perturbation that breaks execution produces no oracle and is dropped.

What differs from RepoBehave: the output is written as a normal repogen run
directory, so `repogen screen`, `repogen cascade`, and `repogen evaluate` all
work on perturbed instances with no special-casing.
"""

from .config import PerturbationConfig
from .pipeline import PerturbationPipeline

__all__ = ["PerturbationConfig", "PerturbationPipeline"]
