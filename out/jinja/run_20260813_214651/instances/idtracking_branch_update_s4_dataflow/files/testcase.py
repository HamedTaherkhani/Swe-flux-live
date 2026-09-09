import hashlib
import unittest

from jinja2.idtracking import Symbols, VAR_LOAD_ALIAS, VAR_LOAD_RESOLVE


def _token(seed: str, tag: str) -> str:
    return hashlib.blake2b(f"{seed}:{tag}".encode(), digest_size=12).hexdigest()


def _branch_symbol(
    seed: str,
    branch_idx: int,
    parent: Symbols | None,
    parent_names: list[str],
) -> Symbols:
    sym = Symbols(parent=parent)
    token = _token(seed, f"branch:{branch_idx}")
    store_count = 2 + int(token[0:2], 16) % 5
    for inner in range(store_count):
        inner_token = _token(seed, f"store:{branch_idx}:{inner}")
        if parent_names and int(inner_token[0:2], 16) % 3 == 0:
            pick = int(inner_token[2:4], 16) % len(parent_names)
            name = parent_names[pick]
        else:
            slot = int(inner_token[4:7], 16) % 41
            name = f"s{slot}_{branch_idx}_{inner}"
        sym.store(name)
    return sym


def _prepare_parent(seed: str) -> Symbols:
    parent = Symbols()
    for idx in range(18):
        token = _token(seed, f"parent:{idx}")
        if int(token[0:2], 16) % 3 == 0:
            continue
        slot = int(token[2:5], 16) % 33
        parent.store(f"p{slot}")
    return parent


def _self_symbol(seed: str, parent: Symbols, inv_idx: int) -> Symbols:
    sym = Symbols(parent=parent)
    token = _token(seed, f"self:{inv_idx}")
    pre_count = int(token[0:2], 16) % 7
    for pre in range(pre_count):
        inner = _token(seed, f"pre:{inv_idx}:{pre}")
        slot = int(inner[0:3], 16) % 29
        sym.store(f"pre{slot}")
    return sym


class IdtrackingBranchUpdateS4DataflowTest(unittest.TestCase):
    def test_direct_branch_update_merges_symbol_tables(self) -> None:
        seed = "idtracking_branch_update_s4"
        parent = _prepare_parent(seed)
        parent_names = sorted(parent.stores)
        checksum = 0

        for inv_idx in range(28):
            inv_token = _token(seed, f"inv:{inv_idx}")
            branch_count = 3 + int(inv_token[0:2], 16) % 4
            use_parent = int(inv_token[2:4], 16) % 2 == 0
            branches: list[Symbols] = []
            for branch_idx in range(branch_count):
                branch_parent = parent if use_parent and branch_idx % 2 == 0 else None
                branches.append(
                    _branch_symbol(
                        seed,
                        inv_idx * 11 + branch_idx,
                        branch_parent,
                        parent_names,
                    )
                )

            frame = _self_symbol(seed, parent, inv_idx)
            frame.branch_update(branches)

            checksum += len(frame.stores)
            checksum += len(frame.refs)
            alias_hits = sum(
                1
                for load in frame.loads.values()
                if isinstance(load, tuple) and load[0] == VAR_LOAD_ALIAS
            )
            resolve_hits = sum(
                1
                for load in frame.loads.values()
                if isinstance(load, tuple) and load[0] == VAR_LOAD_RESOLVE
            )
            checksum += alias_hits * 3 + resolve_hits

        self.assertGreater(checksum, 0)
        self.assertGreater(len(parent.refs), 0)
