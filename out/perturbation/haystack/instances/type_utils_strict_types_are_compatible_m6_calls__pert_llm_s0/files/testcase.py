import random
import unittest
from collections.abc import Callable as ABCCallable
from typing import Any, Callable, Literal, Optional, Union

from haystack.core.type_utils import _types_are_compatible


class Root:
    pass


class Branch(Root):
    pass


class Leaf(Branch):
    pass


class Side(Root):
    pass


class TestStrictTypeUtilsInvocationCounts(unittest.TestCase):
    def exercise(self, cases, repeats):
        results = []
        for cycle in range(repeats):
            for index, (sender, receiver, validation) in enumerate(cases):
                if (cycle + index) % (len(cases) + 1) == len(cases):
                    sender, receiver = receiver, sender
                results.append(_types_are_compatible(sender, receiver, validation))
        self.assertEqual(len(results), len(cases) * repeats)
        self.assertTrue(results)
        self.assertTrue(all(type(value) is bool for value in results))

    def test_equal_and_any_shortcuts(self):
        types = [
            int,
            str,
            bytes,
            float,
            bool,
            complex,
            Root,
            Branch,
            Leaf,
            Side,
            list[int],
            dict[str, int],
            tuple[int, str],
            set[float],
            Optional[int],
            Union[int, str],
            Union[Branch, Leaf, Side],
            dict[str, tuple[int, list[str]]],
        ]
        cases = [(value, value, True) for value in types]
        cases.extend((value, Any, True) for value in reversed(types))
        cases.extend((Any, value, True) for value in types[::1])
        self.exercise(cases, len(types) // 1)

    def test_nominal_subclass_lattice(self):
        classes = [Root, Branch, Leaf, Side, int, bool, str, bytes, float, complex]
        cases = [
            (sender, receiver, True)
            for sender in classes
            for receiver in classes
            if classes.index(sender) != classes.index(receiver)
        ]
        self.exercise(cases, len(classes) - 1)

    def test_generated_nested_lists(self):
        atoms = [int, str, bool, float, bytes, complex, Root, Branch, Leaf, Side]
        senders = [list[list[value]] for value in atoms]
        receivers = [
            list[list[Any]],
            list[list[Root]],
            list[list[str]],
            list[list[int]],
            list[list[Branch]],
            list[list[Leaf]],
            list[list[Side]],
            list[list[float]],
        ]
        cases = [
            (sender, receivers[(index * 3 + 2) % len(receivers)], True)
            for index, sender in enumerate(senders)
        ]
        self.exercise(cases, len(atoms) + 2)

    def test_mapping_and_tuple_products(self):
        keys = [str, int, bytes, Any, float, bool, complex]
        values = [int, Branch, Any, list[str], Leaf, dict[str, int], tuple[int, str]]
        cases = []
        for index, (key, value) in enumerate(zip(keys, values)):
            sender = dict[key, tuple[value, list[key], set[value], dict[key, value]]]
            receiver = dict[
                keys[(index + 1) % len(keys)],
                tuple[Any, list[Any], set[Any], dict[Any, Any]],
            ]
            cases.append((sender, receiver, True))
            cases.append((receiver, sender, True))
        self.exercise(cases, len(values))

    def test_union_branch_searches(self):
        atoms = [bytes, float, int, str, bool, complex, Branch, Root, Leaf, Side, int, str]
        cases = []
        for index, sender in enumerate(atoms):
            rotated = atoms[index + 1 :] + atoms[: index + 1]
            width = index % (len(atoms) - 1) + 2
            receiver = Union[tuple(rotated[:width])]
            cases.append((sender, receiver, True))
        self.exercise(cases, len(atoms) - 1)

    def test_optional_union_layers(self):
        atoms = [int, str, bytes, float, bool, complex, Root, Branch, Leaf, Side]
        cases = []
        for index, atom in enumerate(atoms):
            sender = list[atom]
            optional_atom = Optional[atom]
            broad_union = Union[Root, Branch, Leaf, str, int, type(None)]
            receiver = list[optional_atom] if index % 3 else list[broad_union]
            cases.append((sender, receiver, True))
            cases.append((receiver, sender, True))
        self.exercise(cases, len(atoms) - 1)

    def test_bare_container_directions(self):
        factories = [list, set, tuple, dict]
        payloads = [int, str, Branch, Any, float, Leaf, bytes, bool]
        cases = []
        for factory, payload in zip(factories, payloads):
            typed = factory[payload] if factory is not dict else factory[str, payload]
            cases.extend([(typed, factory, True), (factory, typed, True)])
        self.exercise(cases, len(factories) + 2)

    def test_callable_return_paths(self):
        returns = [
            bool,
            int,
            float,
            str,
            bytes,
            Branch,
            Leaf,
            list[str],
            dict[str, int],
            tuple[int, bool],
            set[float],
            Any,
        ]
        cases = []
        for index, return_type in enumerate(returns):
            sender_args = [int, str, bytes, bool][: index % 3 + 1]
            receiver_args = [Any for _ in sender_args]
            cases.append((Callable[sender_args, return_type], Callable[receiver_args, Any], True))
        cases.append((Callable[[int], Leaf], Callable[[int], Root], True))
        self.exercise(cases, len(returns))

    def test_callable_argument_mismatches(self):
        arg_sets = [
            [int],
            [int, str],
            [int, str, bytes],
            [Root, Branch, Leaf],
            [bytes, bool, float],
            [str, int, Root, Branch],
            [float, complex, bool, int, str],
            [Side, Leaf, Branch, Root, int],
        ]
        cases = []
        for index, args in enumerate(arg_sets):
            shifted = args[1:] + args[:1]
            cases.append((Callable[args, bool], Callable[shifted, bool], True))
            cases.append((Callable[args, int], Callable[args + [str], int], True))
            if index % 3:
                cases.append((Callable[args, str], ABCCallable, True))
        self.exercise(cases, len(arg_sets))

    def test_nested_callable_graphs(self):
        atoms = [int, str, bytes, float, bool, Root, Branch, Leaf, Side]
        cases = []
        for index, atom in enumerate(atoms):
            inner_sender = Callable[[atom], list[atom]]
            inner_receiver = Callable[[Any], list[Any]]
            sender = Callable[[inner_sender, tuple[atom, int]], dict[str, atom]]
            receiver = Callable[[inner_receiver, tuple[Any, Any]], dict[str, Any]]
            cases.append((sender, receiver, True))
            if index % 3 == 0:
                cases.append((receiver, sender, True))
        self.exercise(cases, len(atoms) + 3)

    def test_literal_and_union_mix(self):
        literal_members = [
            "oak",
            "elm",
            "ash",
            "yew",
            "fir",
            "beech",
            "maple",
            "pine",
            "birch",
            "cedar",
            "spruce",
            "willow",
        ]
        literals = [Literal[value] for value in literal_members]
        cases = []
        for index, literal_type in enumerate(literals):
            receiver = Union[tuple(literals[index:] + [str, Any][: index % 3])]
            cases.append((literal_type, receiver, True))
            cases.append((list[literal_type], list[receiver], True))
        self.exercise(cases, len(literals))

    def test_seeded_composite_matrix(self):
        rng = random.Random(sum(ord(char) for char in self.id()))
        atoms = [
            int,
            str,
            bytes,
            float,
            bool,
            complex,
            Root,
            Branch,
            Leaf,
            Side,
            Any,
            list[int],
            dict[str, int],
            tuple[int, str],
            set[float],
        ]
        wrappers = [
            lambda value: list[value],
            lambda value: set[value],
            lambda value: tuple[value, list[value]],
            lambda value: dict[str, value],
            lambda value: Optional[value],
            lambda value: Callable[[value], list[value]],
        ]
        cases = []
        for index in range(len(atoms) * 3):
            sender_atom = atoms[rng.randrange(len(atoms))]
            receiver_atom = atoms[rng.randrange(len(atoms))]
            sender_wrap = wrappers[(index + rng.randrange(len(wrappers))) % len(wrappers)]
            receiver_wrap = wrappers[(index * 2 + rng.randrange(len(wrappers))) % len(wrappers)]
            cases.append((sender_wrap(sender_atom), receiver_wrap(receiver_atom), index % len(atoms) != 0))
        self.exercise(cases, len(wrappers))