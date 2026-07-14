"""Prompt assembly (Template Method over markdown parts).

A prompt = base contract + category card + target dossier, joined by literal
`{{TOKEN}}` substitution so markdown braces stay untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import PROMPTS_DIR, RunConfig
from .planner import PlannedInstance


class PromptBuilder:
    def __init__(self, config: RunConfig, prompts_dir: Path = PROMPTS_DIR):
        self.config = config
        self.base_template = (prompts_dir / "base_contract.md").read_text(encoding="utf-8")
        self.categories_dir = prompts_dir / "categories"

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
            "{{EXISTING_INSTANCES}}": existing,
        }
        prompt = self.base_template
        for token, value in tokens.items():
            prompt = prompt.replace(token, value)
        return prompt
