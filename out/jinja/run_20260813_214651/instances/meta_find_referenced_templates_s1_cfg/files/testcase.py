import random
import unittest

from jinja2 import Environment
from jinja2 import meta


def _build_template_sources(
    seed: int, template_count: int, list_width: int
) -> list[str]:
    rng = random.Random(seed)
    sources: list[str] = []
    for index in range(template_count):
        variant = rng.randint(0, 8)
        if variant == 0:
            sources.append(f'{{% extends "base_{index}.html" %}}')
        elif variant == 1:
            sources.append(f'{{% include "partial_{index}.html" %}}')
        elif variant == 2:
            sources.append(f'{{% from "macros_{index}.html" import fn %}}')
        elif variant == 3:
            sources.append(f'{{% import "lib_{index}.html" as lib %}}')
        elif variant == 4:
            sources.append("{% include dynamic_tpl %}")
        elif variant == 5:
            parts = ", ".join(
                f'"item_{index}_{part}.html"' for part in range(list_width)
            )
            sources.append(f"{{% include [{parts}, helper] %}}")
        elif variant == 6:
            sources.append(
                f'{{% include ["x_{index}.html", 42, "y_{index}.html"] %}}'
            )
        elif variant == 7:
            sources.append(f'{{% include ("only_{index}.html",) %}}')
        else:
            parts = ", ".join(
                f'"t_{index}_{part}.html"' for part in range(list_width)
            )
            sources.append(f"{{% include ({parts}, helper) %}}")
    return sources


class TestFindReferencedTemplatesBatch(unittest.TestCase):
    def test_batch_reference_scan(self) -> None:
        env = Environment()
        sources = _build_template_sources(
            seed=20240814,
            template_count=25,
            list_width=6,
        )
        checksum = 0
        for index, source in enumerate(sources):
            ast = env.parse(source)
            refs = list(meta.find_referenced_templates(ast))
            checksum ^= len(refs) * (index + 7)
        self.assertEqual(checksum, 1)
        self.assertEqual(len(sources), 25)
