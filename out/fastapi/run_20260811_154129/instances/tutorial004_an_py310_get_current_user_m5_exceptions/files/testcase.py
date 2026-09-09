from __future__ import annotations

import random
import unittest

from docs_src.security import tutorial004_an_py310 as tutorial


class TestGeneratedTokenMatrix(unittest.IsolatedAsyncioTestCase):
    async def test_generated_token_matrix(self) -> None:
        generator = random.Random(sum((index + 3) ** 4 for index in range(19)))
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        known_name = "".join(
            alphabet[position] for position in (9, 14, 7, 13, 3, 14, 4)
        )
        future_expiry = sum(2**power for power in range(20, 33))
        alternate_key = "".join(
            alphabet[generator.randrange(len(alphabet))] for _ in range(47)
        )
        case_count = len(alphabet) + len(tuple(range(23)))
        tokens: list[str] = []

        for index in range(case_count):
            mode = (index * 11 + index // 3 + 5) % 9
            suffix = "".join(
                alphabet[(generator.randrange(26) + index + offset) % 26]
                for offset in range(13)
            )
            payload: dict[str, object] = {"exp": future_expiry}
            key = tutorial.SECRET_KEY
            algorithm = tutorial.ALGORITHM

            if mode == 0:
                payload["sub"] = known_name
            elif mode == 1:
                payload["sub"] = f"{suffix}{index * index}"
            elif mode == 2:
                pass
            elif mode == 3:
                payload.update({"sub": known_name, "exp": index - case_count - 1})
            elif mode == 4:
                payload["sub"] = known_name
                key = alternate_key
            elif mode == 5:
                payload["sub"] = known_name
                algorithm = "HS" + str(128 * 3)
            elif mode == 6:
                payload["sub"] = index * 17
            elif mode == 7:
                payload.update(
                    {"sub": known_name, "aud": [suffix, suffix[::-1]]}
                )
            else:
                malformed = "".join(
                    alphabet[(generator.randrange(26) + position) % 26]
                    for position in range(37)
                )
                tokens.append(malformed)
                continue

            tokens.append(tutorial.jwt.encode(payload, key, algorithm=algorithm))

        completed = 0
        rejected = 0
        returned_names: list[str] = []
        for token in tokens:
            try:
                user = await tutorial.get_current_user(token)
            except Exception:
                rejected += 1
            else:
                completed += 1
                returned_names.append(user.username)

        self.assertEqual(completed + rejected, len(tokens))
        self.assertGreater(completed * rejected, 0)
        self.assertTrue(returned_names)
        self.assertTrue(all(name == known_name for name in returned_names))
