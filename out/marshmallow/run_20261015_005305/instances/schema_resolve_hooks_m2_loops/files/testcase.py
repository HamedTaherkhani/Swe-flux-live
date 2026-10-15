"""Scenarios driving SchemaMeta.resolve_hooks over generated schema hierarchies."""

import random
import unittest

from marshmallow import Schema, fields
from marshmallow.decorators import (
    post_dump,
    post_load,
    pre_dump,
    pre_load,
    validates,
    validates_schema,
)
from marshmallow.schema import SchemaMeta

DECORATORS = [pre_load, post_load, pre_dump, post_dump, validates_schema]


def _make_hook(name, rng):
    def hook(self, data, **kwargs):
        return data

    hook.__name__ = name
    for _ in range(rng.randint(1, 3)):
        hook = rng.choice(DECORATORS)(hook)
    return hook


def _plain_method(name):
    def method(self):
        return name

    method.__name__ = name
    return method


def _attrs(rng, prefix, n_fields, n_hooks, n_plain):
    attrs = {}
    for i in range(n_fields):
        attrs[f"{prefix}_f{i}"] = rng.choice([fields.Str, fields.Int, fields.Bool])()
    for i in range(n_hooks):
        attrs[f"{prefix}_h{i}"] = _make_hook(f"{prefix}_h{i}", rng)
    for i in range(n_plain):
        attrs[f"{prefix}_m{i}"] = _plain_method(f"{prefix}_m{i}")
    return attrs


def _total_entries(hooks):
    return sum(len(v) for v in hooks.values())


class ResolveHooksLoopTest(unittest.TestCase):
    def test_flat_schema(self):
        rng = random.Random(11)
        klass = SchemaMeta("FlatSchema", (Schema,), _attrs(rng, "flat", 6, 4, 3))
        hooks = klass.resolve_hooks()
        self.assertEqual(_total_entries(hooks), _total_entries(klass._hooks))
        self.assertTrue(all(name.startswith("flat_h") for v in hooks.values() for name, _, _ in v))

    def test_linear_chain(self):
        rng = random.Random(23)
        base = Schema
        for depth in range(rng.randint(4, 6)):
            base = SchemaMeta(
                f"Chain{depth}",
                (base,),
                _attrs(rng, f"c{depth}", rng.randint(0, 3), rng.randint(0, 2), 1),
            )
        hooks = base.resolve_hooks()
        self.assertGreater(len(hooks), 0)

    def test_diamond_mixins(self):
        rng = random.Random(37)
        mixins = [
            type(f"Mixin{i}", (), _attrs(rng, f"mx{i}", 0, rng.randint(1, 2), rng.randint(0, 2)))
            for i in range(4)
        ]
        left = SchemaMeta("Left", (mixins[0], mixins[1], Schema), {})
        right = SchemaMeta("Right", (mixins[2], Schema), _attrs(rng, "r", 2, 1, 0))
        bottom = SchemaMeta("Bottom", (left, right, mixins[3]), _attrs(rng, "b", 1, 1, 1))
        hooks = bottom.resolve_hooks()
        self.assertEqual(set(hooks), set(bottom._hooks))

    def test_phantom_dir_names(self):
        rng = random.Random(41)
        phantoms = [f"ghost_{rng.randint(100, 999)}_{i}" for i in range(rng.randint(5, 9))]

        class PhantomMeta(SchemaMeta):
            def __dir__(cls):
                return sorted(set(type.__dir__(cls)) | set(phantoms))

        mid = PhantomMeta("PhantomMid", (Schema,), _attrs(rng, "pm", 2, 2, 0))
        leaf = PhantomMeta("PhantomLeaf", (mid,), _attrs(rng, "pl", 1, 1, 2))
        hooks = leaf.resolve_hooks()
        names = {name for v in hooks.values() for name, _, _ in v}
        self.assertFalse(names & set(phantoms))

    def test_shadowed_hooks(self):
        rng = random.Random(53)
        parent = SchemaMeta("ShadowParent", (Schema,), _attrs(rng, "sh", 0, 6, 0))
        overrides = {f"sh_h{i}": _plain_method(f"sh_h{i}") for i in range(6) if i % 2 == 0}
        child = SchemaMeta("ShadowChild", (parent,), overrides)
        grandchild = SchemaMeta("ShadowGrand", (child,), {"sh_h1": None})
        self.assertLess(_total_entries(grandchild.resolve_hooks()), _total_entries(parent._hooks))

    def test_stacked_decorators(self):
        def make(i):
            def fn(self, data, **kwargs):
                return data

            for j in range(i % 4 + 1):
                fn = DECORATORS[(i + j) % len(DECORATORS)](fn)
            return fn

        klass = SchemaMeta("Stacked", (Schema,), {f"st{i}": make(i) for i in range(7)})
        hooks = klass.resolve_hooks()
        self.assertGreaterEqual(_total_entries(hooks), 7)

    def test_from_dict(self):
        rng = random.Random(67)
        generated = Schema.from_dict(
            {f"g{i}": fields.Str() for i in range(rng.randint(5, 12))}, name="Gen"
        )
        sub = SchemaMeta("GenSub", (generated,), _attrs(rng, "gs", 1, 2, 1))
        self.assertEqual(set(sub.resolve_hooks()), set(sub._hooks))

    def test_repeated_resolution(self):
        rng = random.Random(79)
        klass = SchemaMeta("Repeat", (Schema,), _attrs(rng, "rp", 3, 3, 0))
        results = [klass.resolve_hooks() for _ in range(rng.randint(2, 4))]
        self.assertTrue(all(r == results[0] for r in results))

    def test_field_validators(self):
        names = [f"v{i}" for i in range(8)]
        attrs = {n: fields.Int() for n in names}
        for i in range(0, 8, 3):
            def check(self, value, **kwargs):
                return None

            attrs[f"validate_{names[i]}"] = validates(*names[i : i + 2])(check)
        klass = SchemaMeta("Validated", (Schema,), attrs)
        hooks = klass.resolve_hooks()
        self.assertIn("validates", hooks)

    def test_custom_hook_object(self):
        class Marker:
            def __init__(self, tags):
                self.__marshmallow_hook__ = {t: [(i % 2 == 0, {"i": i})] for i, t in enumerate(tags)}

        rng = random.Random(83)
        attrs = {
            f"mk{i}": Marker(rng.sample(["pre_load", "post_load", "pre_dump", "post_dump"], rng.randint(1, 4)))
            for i in range(5)
        }
        klass = SchemaMeta("Markers", (Schema,), attrs)
        hooks = klass.resolve_hooks()
        self.assertEqual(_total_entries(hooks), sum(len(a.__marshmallow_hook__) for a in attrs.values()))

    def test_setattr_after_creation(self):
        rng = random.Random(97)
        klass = SchemaMeta("Mutable", (Schema,), _attrs(rng, "mu", 2, 1, 1))
        before = _total_entries(klass.resolve_hooks())
        for i in range(rng.randint(3, 6)):
            setattr(klass, f"late{i}", _make_hook(f"late{i}", rng))
        after = _total_entries(klass.resolve_hooks())
        self.assertGreater(after, before)

    def test_wide_multiple_inheritance(self):
        rng = random.Random(101)
        bases = [
            SchemaMeta(f"Wide{i}", (Schema,), _attrs(rng, f"w{i}", 1, rng.randint(0, 2), rng.randint(0, 1)))
            for i in range(5)
        ]
        combo = SchemaMeta("WideCombo", tuple(reversed(bases)), {})
        hooks = combo.resolve_hooks()
        self.assertEqual(hooks, combo._hooks)


if __name__ == "__main__":
    unittest.main()
