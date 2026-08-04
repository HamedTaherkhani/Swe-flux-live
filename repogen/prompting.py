"""Prompt assembly (Template Method over markdown parts).

A prompt = base contract + category card + target dossier, joined by literal
`{{TOKEN}}` substitution so markdown braces stay untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import PROMPTS_DIR, RunConfig
from .planner import PlannedInstance
from .screening import screening_contract


class PromptBuilder:
    def __init__(self, config: RunConfig, prompts_dir: Path = PROMPTS_DIR):
        self.config = config
        self.base_template = (prompts_dir / "base_contract.md").read_text(encoding="utf-8")
        self.categories_dir = prompts_dir / "categories"
        self.canonical_templates = json.loads(
            (prompts_dir / "canonical_templates.json").read_text(encoding="utf-8")
        )

    @staticmethod
    def _render_callers(target: dict) -> str:
        """Known same-module callers of the target (from the scout), used to
        steer the test toward exercising the target indirectly."""
        one = target.get("callers") or []
        two = target.get("callers_2hop") or []
        if not one and not two:
            return ("(none known in the same module — indirect exercise may still "
                    "be possible through other modules' entry points)")
        parts = []
        if one:
            parts.append("direct callers: " + ", ".join(f"`{c}`" for c in one))
        if two:
            parts.append("two hops up: " + ", ".join(f"`{c}`" for c in two))
        return "; ".join(parts)

    def _render_canonical_templates(self, category: str) -> str:
        """Render the category's canonical template_answer shapes for the prompt."""
        entry = self.canonical_templates.get(category)
        if not entry:
            return "(no canonical templates registered for this category)"
        lines: list[str] = []
        for i, t in enumerate(entry["templates"], start=1):
            lines.append(f"{i}. `{json.dumps(t['template'], sort_keys=True)}`")
            lines.append(f"   - use for: {t['use_for']}")
            lines.append(f"   - what may vary: {t['varies']}")
        if entry.get("notes"):
            lines.append(f"\nCategory note: {entry['notes']}")
        return "\n".join(lines)

    def build(self, planned: PlannedInstance, existing_ids: list[str]) -> str:
        card_path = self.categories_dir / f"{planned.category}.md"
        category_card = card_path.read_text(encoding="utf-8").strip()
        target = planned.target

        existing = (
            "\n".join(f"- {iid}" for iid in existing_ids) if existing_ids else "- (none yet)"
        )
        tokens = {
            "{{WORKDIR}}": self.config.workdir,
            "{{REPO_KEY}}": self.config.repo_key,
            "{{QA_DIR}}": self.config.container_qa_dir,
            "{{QA_DIR_NAME}}": self.config.qa_dir_name,
            "{{INSTANCE_ID}}": planned.instance_id,
            "{{CATEGORY}}": planned.category,
            "{{CATEGORY_CARD}}": category_card,
            "{{TARGET_QUALNAME}}": target["qualname"],
            "{{TARGET_FILE}}": target["file"],
            "{{TARGET_MODULE}}": target["module"],
            "{{TARGET_LINES}}": f"{target['lineno']}-{target['end_lineno']}",
            "{{TARGET_METRICS}}": json.dumps(target["metrics"], sort_keys=True),
            "{{TARGET_CALLERS}}": self._render_callers(target),
            "{{EXISTING_INSTANCES}}": existing,
            "{{SCREENING_RULES}}": screening_contract(planned.category),
            "{{CANONICAL_TEMPLATES}}": self._render_canonical_templates(planned.category),
        }
        prompt = self.base_template
        for token, value in tokens.items():
            prompt = prompt.replace(token, value)
        return prompt
