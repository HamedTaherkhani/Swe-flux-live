import random
import unittest

from haystack.utils.type_serialization import deserialize_type


def _permuted(seed, values):
    values = list(values)
    random.Random(seed).shuffle(values)
    return values


class _ArithmeticGeneric:
    @classmethod
    def __class_getitem__(cls, item):
        width = len(getattr(item, "__name__", str(item)))
        return width // (width - width)


class _LookupGeneric:
    @classmethod
    def __class_getitem__(cls, item):
        key = getattr(item, "__name__", str(item))
        return {key: item}[key[::-1] + "_"]


class _DecodeGeneric:
    @classmethod
    def __class_getitem__(cls, item):
        width = len(getattr(item, "__name__", str(item)))
        return bytes([192 + width]).decode("ascii")


class _BoundsGeneric:
    @classmethod
    def __class_getitem__(cls, item):
        width = len(getattr(item, "__name__", str(item)))
        return tuple(range(width))[width + 1]


class _GeneratorGeneric:
    @classmethod
    def __class_getitem__(cls, item):
        def stream():
            yield next(iter(()))

        return next(stream())


class _AttributeGeneric:
    @classmethod
    def __class_getitem__(cls, item):
        suffix = len(getattr(item, "__name__", str(item)))
        return getattr(cls, f"_absent_{suffix}")


class _ReraisingGeneric:
    @classmethod
    def __class_getitem__(cls, item):
        key = getattr(item, "__name__", str(item))
        try:
            return {}[key]
        except Exception:
            raise


class _SwallowingGeneric:
    @classmethod
    def __class_getitem__(cls, item):
        key = getattr(item, "__name__", str(item))
        try:
            return int(key + "!")
        except Exception:
            return list[item]


class TestDeserializeTypeExceptions(unittest.TestCase):
    def test_01_generated_builtin_successes(self):
        fragments = ("str", "int", "dict", "float", "bool", "bytes", "tuple", "set")
        values = _permuted(1703, (fragments[(index * 5 + 3) % len(fragments)] for index in range(24)))
        results = [deserialize_type(value) for value in values]
        self.assertEqual(len(results), len(values))
        self.assertTrue(all(isinstance(result, type) for result in results))

    def test_02_nested_generic_successes(self):
        atoms = ("str", "int", "float", "bytes")
        values = _permuted(
            2711,
            (
                f"{('list', 'dict', 'tuple')[(index * 7) % 3]}["
                f"{atoms[index % len(atoms)]}"
                f"{', ' + atoms[(index + 1) % len(atoms)] if index % 3 == 1 else ''}]"
                for index in range(18)
            ),
        )
        results = [deserialize_type(value) for value in values]
        self.assertTrue(all(result is not None for result in results))
        self.assertEqual(len(results), len(values))

    def test_03_generated_unknown_bare_names(self):
        values = _permuted(3911, (f"unknown_{index * index + 3 * index + 1}" for index in range(7)))
        failures = 0
        for value in values:
            with self.assertRaises(Exception):
                deserialize_type(value)
            failures += 1
        self.assertEqual(failures, len(values))

    def test_04_generated_missing_modules(self):
        values = _permuted(
            4703,
            (f"absent_pkg_{index * 17 + 5}.branch_{index % 3}.Thing{index + 2}" for index in range(5)),
        )
        failures = 0
        for value in values:
            with self.assertRaises(Exception):
                deserialize_type(value)
            failures += 1
        self.assertEqual(failures, len(values))

    def test_05_existing_modules_missing_attributes(self):
        modules = ("math", "collections", "typing")
        values = _permuted(
            5501,
            (f"{modules[(index * 2) % len(modules)]}.Absent{index * index + 7}" for index in range(6)),
        )
        for value in values:
            with self.assertRaises(Exception):
                deserialize_type(value)
        self.assertGreater(len(values), 0)

    def test_06_invalid_generic_main_types(self):
        values = _permuted(
            6701,
            (f"missing_outer_{index * 13 + 4}[{('str', 'int')[index % 2]}]" for index in range(4)),
        )
        failures = sum(self._fails(value) for value in values)
        self.assertEqual(failures, len(values))

    def test_07_invalid_nested_generic_arguments(self):
        containers = ("list", "dict", "tuple")
        values = _permuted(
            7703,
            (
                f"{containers[index % len(containers)]}["
                f"{'str, ' if index % 2 else ''}missing_arg_{index * 19 + 2}]"
                for index in range(8)
            ),
        )
        failures = sum(self._fails(value) for value in values)
        self.assertEqual(failures, len(values))

    def test_08_unsubscriptable_builtin_mains(self):
        mains = ("int", "float", "bool", "complex")
        values = _permuted(
            8707,
            (f"{mains[(index * 3) % len(mains)]}[{('str', 'bytes')[index % 2]}]" for index in range(9)),
        )
        failures = sum(self._fails(value) for value in values)
        self.assertEqual(failures, len(values))

    def test_09_attribute_driven_generic_failures(self):
        module = __name__
        atoms = ("str", "int", "bytes")
        values = _permuted(
            9733,
            (f"{module}._AttributeGeneric[{atoms[(index * 2) % len(atoms)]}]" for index in range(5)),
        )
        failures = sum(self._fails(value) for value in values)
        self.assertEqual(failures, len(values))

    def test_10_arithmetic_and_reraised_lookup_failures(self):
        module = __name__
        classes = ("_ArithmeticGeneric", "_LookupGeneric", "_ReraisingGeneric")
        atoms = ("str", "int", "float", "bytes")
        values = _permuted(
            10709,
            (
                f"{module}.{classes[(index * 5 + 1) % len(classes)]}"
                f"[{atoms[(index * 3) % len(atoms)]}]"
                for index in range(11)
            ),
        )
        failures = sum(self._fails(value) for value in values)
        self.assertEqual(failures, len(values))

    def test_11_decode_bounds_and_generator_failures(self):
        module = __name__
        classes = ("_DecodeGeneric", "_BoundsGeneric", "_GeneratorGeneric")
        atoms = ("str", "int", "tuple", "bytes", "float")
        values = _permuted(
            11717,
            (
                f"{module}.{classes[(index * 7 + 2) % len(classes)]}"
                f"[{atoms[(index * 11 + 1) % len(atoms)]}]"
                for index in range(13)
            ),
        )
        failures = sum(self._fails(value) for value in values)
        self.assertEqual(failures, len(values))

    def test_12_mixed_safe_swallowed_and_failing_paths(self):
        module = __name__
        atoms = ("str", "int", "bytes", "float")
        values = []
        for index in range(17):
            selector = (index * index + 3 * index + 1) % 5
            atom = atoms[(index * 7) % len(atoms)]
            if selector == 0:
                values.append(atom)
            elif selector == 1:
                values.append(f"{module}._SwallowingGeneric[{atom}]")
            elif selector == 2:
                values.append(f"{module}._ReraisingGeneric[{atom}]")
            elif selector == 3:
                values.append(f"missing_mix_{index * 23 + 6}")
            else:
                values.append(f"int[{atom}]")

        failures = sum(self._fails(value) for value in _permuted(12721, values))
        self.assertGreater(failures, 0)
        self.assertLess(failures, len(values))

    @staticmethod
    def _fails(value):
        try:
            deserialize_type(value)
        except Exception:
            return 1
        return 0
