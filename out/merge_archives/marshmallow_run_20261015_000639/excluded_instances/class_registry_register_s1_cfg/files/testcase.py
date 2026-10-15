import random
import unittest

from marshmallow import class_registry
from marshmallow.class_registry import register


def _build_plan(seed, count):
    rng = random.Random(seed)
    stems = ["".join(chr(ord("K") + (i * 7 + j) % 13) for j in range(4)).title() for i in range(3)]
    modules = [f"qa_reg.pkg{k}.sub{(k * 5) % 3}" for k in range(3)]
    plan = []
    for _ in range(count):
        module = rng.choice(modules)
        stem = rng.choice(stems)
        roll = rng.random()
        if roll < 0.2:
            # dotted class names may collide with full-path registry keys
            classname = f"{rng.choice(modules)}.{stem}"
        else:
            classname = stem
        plan.append((classname, module))
    return plan


class RegisterControlFlowTest(unittest.TestCase):
    def test_register_sequence(self):
        saved = dict(class_registry._registry)
        class_registry._registry.clear()
        try:
            plan = _build_plan(seed=20241, count=26)
            created = []
            for idx, (classname, module) in enumerate(plan):
                cls = type(f"Gen{idx}", (), {"__module__": module})
                created.append(cls)
                register(classname, cls)

            registry = class_registry._registry
            for classname, module in plan:
                self.assertIn(classname, registry)
                self.assertIn(f"{module}.{classname}", registry)
            self.assertIn(created[-1], registry[f"{plan[-1][1]}.{plan[-1][0]}"])
            total = sum(len(v) for v in registry.values())
            self.assertGreater(total, len(set(c for c, _ in plan)))
        finally:
            class_registry._registry.clear()
            class_registry._registry.update(saved)
