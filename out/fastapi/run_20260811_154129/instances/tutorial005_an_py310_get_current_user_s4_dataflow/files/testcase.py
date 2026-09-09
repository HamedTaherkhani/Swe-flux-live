import asyncio
import random
import unittest

import jwt
from fastapi import HTTPException
from fastapi.security import SecurityScopes

from docs_src.security import tutorial005_an_py310 as tutorial


class TestGetCurrentUserDataFlow(unittest.TestCase):
    def test_generated_scope_matrix(self):
        rng = random.Random(8675309)
        fragments = [
            "".join(chr(ord("a") + rng.randrange(26)) for _ in range(7))
            for _ in range(29)
        ]
        required_scopes = [
            f"{fragment}:{(index * index + rng.randrange(97)) % 101}"
            for index, fragment in enumerate(fragments)
        ]

        valid_token = jwt.encode(
            {"sub": "".join(["john", "doe"]), "scope": " ".join(required_scopes)},
            tutorial.SECRET_KEY,
            algorithm=tutorial.ALGORITHM,
        )
        denied_scopes = [
            *required_scopes[:19],
            fragments[-1][::-1] + ":denied",
            *required_scopes[19:],
        ]
        unknown_subject = "".join(chr(ord("k") + offset) for offset in range(8))
        unknown_token = jwt.encode(
            {"sub": unknown_subject, "scope": " ".join(required_scopes)},
            tutorial.SECRET_KEY,
            algorithm=tutorial.ALGORITHM,
        )
        subjectless_token = jwt.encode(
            {"scope": " ".join(required_scopes)},
            tutorial.SECRET_KEY,
            algorithm=tutorial.ALGORITHM,
        )
        malformed_token = ".".join(fragment[:5] for fragment in fragments[:3])

        async def exercise():
            user = await tutorial.get_current_user(
                SecurityScopes(scopes=required_scopes), valid_token
            )
            unrestricted = await tutorial.get_current_user(SecurityScopes(), valid_token)

            for scopes, token in (
                (denied_scopes, valid_token),
                (required_scopes, unknown_token),
                (required_scopes, subjectless_token),
                (required_scopes, malformed_token),
            ):
                with self.assertRaises(HTTPException):
                    await tutorial.get_current_user(
                        SecurityScopes(scopes=scopes), token
                    )
            return user, unrestricted

        user, unrestricted = asyncio.run(exercise())
        self.assertEqual(user, unrestricted)
        self.assertFalse(user.disabled)
        self.assertEqual(len(required_scopes), len(set(required_scopes)))
