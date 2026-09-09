import hashlib
import unittest

from jinja2 import Environment
from jinja2.filters import do_xmlattr
from jinja2.nodes import EvalContext
from jinja2.runtime import Undefined


def _digest(seed: int, tag: str, index: int = 0) -> str:
    return hashlib.blake2b(
        f"filters_do_xmlattr_s2_loops:{seed}:{tag}:{index}".encode(),
        digest_size=32,
    ).hexdigest()


def _build_attr_mapping(seed: int) -> dict[str, object]:
    """Construct a deterministic attribute mapping with mixed value kinds."""
    mapping: dict[str, object] = {}
    base = _digest(seed, "base")
    slot_total = 100 + (int(base[0:2], 16) % 60)

    for idx in range(slot_total):
        chunk = _digest(seed, "slot", idx)
        gate = int(chunk[0:2], 16) % 18
        if gate == 0:
            continue

        key_token = int(chunk[2:4], 16) % 5
        if key_token == 0:
            key = f"attr_{idx}"
        elif key_token == 1:
            key = f"data_{idx}"
        elif key_token == 2:
            key = f"field_{idx}"
        elif key_token == 3:
            key = f"k{idx}"
        else:
            key = f"n{idx}_{chunk[4:8]}"

        if key in mapping:
            continue

        value_gate = int(chunk[4:6], 16) % 16
        if value_gate == 0:
            mapping[key] = None
        elif value_gate == 1:
            mapping[key] = Undefined()
        elif value_gate == 2:
            mapping[key] = int(chunk[6:8], 16)
        elif value_gate == 3:
            mapping[key] = f"payload_{chunk[8:12]}"
        elif value_gate == 4:
            mapping[key] = chunk[12:18]
        else:
            mapping[key] = f"v{idx}_{int(chunk[18:20], 16)}"

    return mapping


class FiltersDoXmlattrS2LoopsTest(unittest.TestCase):
    def test_direct_xmlattr_drives_items_loop(self) -> None:
        seed = 88
        mapping = _build_attr_mapping(seed)
        env = Environment(autoescape=True)
        eval_ctx = EvalContext(env)

        result = do_xmlattr(eval_ctx, mapping, autospace=True)

        self.assertIsInstance(result, str)
        self.assertGreater(len(mapping), 15)
        self.assertTrue(result.startswith(" "))
        kept = sum(
            1
            for value in mapping.values()
            if value is not None and not isinstance(value, Undefined)
        )
        self.assertGreater(kept, 8)
        self.assertEqual(result.count('="'), kept)
