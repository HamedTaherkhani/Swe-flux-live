from __future__ import annotations

import random
import unittest
from typing import Any

from fastapi.utils import deep_dict_update


class ProbeDict(dict[str, Any]):
    def items(self):
        return super().items()

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key)

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)


def build_pair(rng: random.Random, depth: int, width: int) -> tuple[ProbeDict, ProbeDict]:
    main = ProbeDict()
    update = ProbeDict()

    for index in range(width):
        key = f"level_{depth}_slot_{(index * 11 + depth * 5) % width:02d}"
        selector = (rng.randrange(97) + index * 7 + depth * 13) % 6
        token = rng.randrange(1_000, 100_000)

        if selector == 0 and depth < 3:
            child_main, child_update = build_pair(rng, depth + 1, width - 4)
            main[key] = child_main
            update[key] = child_update
        elif selector == 1:
            main[key] = [token ^ shift for shift in range((index % 4) + 1)]
            update[key] = [token + shift * (depth + 1) for shift in range((index % 3) + 2)]
        elif selector == 2:
            main[key] = token
            update[key] = token ^ (index * 31 + depth)
        elif selector == 3:
            update[key] = (token + index) % 997
        elif selector == 4:
            main[key] = [token, depth]
            update[key] = ProbeDict(
                generated=(token * (index + 1)) % 1009,
                parity=(token + depth) % 2,
            )
        else:
            main[key] = ProbeDict(previous=token - index)
            update[key] = [token // (depth + 1), index]

    return main, update


class DeepDictUpdateCallGraphTest(unittest.TestCase):
    def test_generated_recursive_mapping_merge(self) -> None:
        rng = random.Random(0xD33F)
        main, update = build_pair(rng, depth=0, width=18)
        keys_before = set(main)
        update_keys = set(update)

        deep_dict_update(main, update)

        self.assertEqual(set(main), keys_before | update_keys)
        self.assertTrue(all(key in main for key in update))
        self.assertTrue(any(isinstance(value, list) for value in main.values()))
        self.assertTrue(any(isinstance(value, ProbeDict) for value in main.values()))

