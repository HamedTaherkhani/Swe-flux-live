import random
import unittest

from lark.parsers.earley_forest import ForestToParseTree
from lark.visitors import Discard


class Parent:
    def __init__(self, is_intermediate):
        self.is_intermediate = is_intermediate


class Child:
    def __init__(self, is_intermediate):
        self.is_intermediate = is_intermediate


class SyntheticPackedNode:
    def __init__(self, parent, left, right, rule):
        self.parent = parent
        self.left = left
        self.right = right
        self.rule = rule


class TestPackedNodeControlFlow(unittest.TestCase):
    def test_seeded_direct_transformations(self):
        rng = random.Random(1)
        callback_count = [0]

        def combine(children):
            callback_count[0] += 1
            return tuple(children)

        transformer = ForestToParseTree(
            callbacks={},
            prioritizer=None,
            resolve_ambiguity=False,
            use_cache=True,
        )
        nodes = []
        calls = []
        rolling = rng.randrange(1000)

        for position in range(400):
            rolling = (rolling * (17 + rng.randrange(13)) + rng.randrange(997)) % 16381
            width = 1 + rng.randrange(30)
            payload = [
                (rolling + offset * rng.randrange(2, 97)) % 8191
                for offset in range(width)
            ]
            parent = Parent(bool(rng.getrandbits(1)))
            left = Child(bool(rng.getrandbits(1))) if rng.randrange(2) else None
            right = Child(bool(rng.getrandbits(1))) if rng.randrange(3) else None
            rule = (position, rolling, tuple(payload[-2:]))
            transformer.callbacks[rule] = combine

            shape = rng.randrange(4)
            if shape == 0:
                data = []
            elif shape == 1:
                data = [payload[0]]
            else:
                data = [payload[:-1], payload[-1]]
            mode = rng.randrange(8)

            node = SyntheticPackedNode(parent, left, right, rule)
            nodes.append(node)
            calls.append((node, data, mode, tuple(payload)))

        results = []
        for node, data, mode, payload in calls:
            transformer._on_cycle_retreat = False
            transformer._cycle_node = None
            transformer._successful_visits.clear()
            transformer.resolve_ambiguity = mode == 1

            if mode == 0:
                transformer._on_cycle_retreat = True
                transformer._cycle_node = nodes[(rolling + len(payload)) % len(nodes)]
                if transformer._cycle_node is node:
                    transformer._cycle_node = object()
            elif mode == 1:
                transformer._successful_visits.add(id(node.parent))
            elif mode == 2:
                transformer._cache[id(node)] = ("cached", sum(payload) % 101)
            elif mode == 4:
                transformer._on_cycle_retreat = True
                transformer._cycle_node = node
            elif mode == 5:
                transformer._on_cycle_retreat = True
                transformer._cycle_node = object()
                transformer._successful_visits.add(id(node))

            results.append(transformer.transform_packed_node(node, data))

        self.assertEqual(len(results), len(nodes))
        self.assertTrue(any(result is Discard for result in results))
        self.assertTrue(any(isinstance(result, list) for result in results))
        self.assertTrue(any(isinstance(result, tuple) for result in results))
        self.assertGreater(callback_count[0], 0)