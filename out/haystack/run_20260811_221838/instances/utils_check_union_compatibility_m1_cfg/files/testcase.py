import unittest
from typing import Any, Optional, Union

from haystack.core.super_component.utils import _is_compatible


def _make_types(prefix, size):
    return tuple(type(f"{prefix}_{index}", (), {}) for index in range(size))


def _union(types):
    return Union[types]


class TestUnionCompatibilityCFG(unittest.TestCase):
    def test_left_union_with_late_match(self):
        types = _make_types("left_late", len("abcdefghijklmnopqr"))
        compatible, common = _is_compatible(_union(types), types[-2])
        self.assertTrue(compatible)
        self.assertIs(common, types[-2])

    def test_left_union_without_match(self):
        types = _make_types("left_miss", len("abcdefghijklmnop"))
        outsider = _make_types("left_outsider", len("x"))[0]
        compatible, common = _is_compatible(_union(types), outsider)
        self.assertFalse(compatible)
        self.assertIsNone(common)

    def test_right_union_with_early_match(self):
        types = _make_types("right_early", len("abcdefghijklmnopq"))
        compatible, common = _is_compatible(types[1], _union(types))
        self.assertTrue(compatible)
        self.assertIs(common, types[1])

    def test_right_union_without_match(self):
        types = _make_types("right_miss", len("abcdefghijklmnopqrst"))
        outsider = _make_types("right_outsider", len("z"))[0]
        compatible, common = _is_compatible(outsider, _union(types))
        self.assertFalse(compatible)
        self.assertIsNone(common)

    def test_two_unions_with_shared_middle(self):
        shared = _make_types("shared_middle", len("abcdef"))
        left = _make_types("shared_left", len("abcdefgh")) + shared
        right = _make_types("shared_right", len("abcdefg")) + tuple(reversed(shared))
        compatible, common = _is_compatible(_union(left), _union(right))
        self.assertTrue(compatible)
        self.assertIsNotNone(common)

    def test_two_disjoint_unions(self):
        left = _make_types("disjoint_left", len("abcdefghijk"))
        right = _make_types("disjoint_right", len("abcdefghijklm"))
        compatible, common = _is_compatible(_union(left), _union(right))
        self.assertFalse(compatible)
        self.assertIsNone(common)

    def test_any_in_left_union(self):
        left = (Any,) + _make_types("any_left", len("abcdefghijklm"))
        right = _make_types("any_left_targets", len("abcdefghij"))
        compatible, common = _is_compatible(_union(left), _union(right))
        self.assertTrue(compatible)
        self.assertIsNotNone(common)

    def test_any_in_right_union(self):
        left = _make_types("any_right_sources", len("abcdefghijkl"))
        right = _make_types("any_right", len("abcdefghi")) + (Any,)
        compatible, common = _is_compatible(_union(left), _union(right))
        self.assertTrue(compatible)
        self.assertIsNotNone(common)

    def test_nested_list_unions(self):
        shared = _make_types("list_shared", len("abcde"))
        left = _make_types("list_left", len("abcdefg")) + shared
        right = shared + _make_types("list_right", len("abcdefgh"))
        compatible, common = _is_compatible(list[_union(left)], list[_union(right)])
        self.assertTrue(compatible)
        self.assertIsNotNone(common)

    def test_nested_mapping_unions_disjoint(self):
        left = _make_types("map_left", len("abcdefghij"))
        right = _make_types("map_right", len("abcdefghijkl"))
        compatible, common = _is_compatible(dict[str, _union(left)], dict[str, _union(right)])
        self.assertFalse(compatible)
        self.assertIsNone(common)

    def test_union_containing_generic(self):
        atoms = _make_types("generic_atoms", len("abcdefghijklmnop"))
        alternatives = tuple(list[atom] for atom in atoms)
        compatible, common = _is_compatible(_union(alternatives), list[atoms[-1]])
        self.assertTrue(compatible)
        self.assertIsNotNone(common)

    def test_optional_union_without_recursive_unwrap(self):
        atoms = _make_types("optional_atoms", len("abcdefghijklmnopq"))
        optional_union = Optional[_union(atoms)]
        compatible, common = _is_compatible(optional_union, atoms[2], unwrap_nested=False)
        self.assertTrue(compatible)
        self.assertIs(common, atoms[2])

    def test_tuple_with_several_union_slots(self):
        groups = tuple(
            _make_types(f"tuple_group_{index}", len("abcdefghijk") + index)
            for index in range(len("abc"))
        )
        left = tuple[_union(groups[0]), _union(groups[1]), _union(groups[2])]
        right = tuple[groups[0][-1], groups[1][-2], groups[2][-3]]
        compatible, common = _is_compatible(left, right)
        self.assertTrue(compatible)
        self.assertIsNotNone(common)
