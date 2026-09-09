import asyncio
import unittest
from unittest import mock

import jwt
from fastapi.security import SecurityScopes

import docs_src.security.tutorial005_py310 as tutorial


class TestCurrentUserExceptionMatrix(unittest.TestCase):
    def test_generated_tokens_and_scope_walks(self) -> None:
        username = "".join(chr(value) for value in (106, 111, 104, 110, 100, 111, 101))
        scope_names = [
            f"perm_{(index * 17 + 11) % 101:03d}_{index * index + 7}"
            for index in range(37)
        ]
        base_payload = {"sub": username, "scope": " ".join(scope_names)}

        valid_token = jwt.encode(
            base_payload, tutorial.SECRET_KEY, algorithm=tutorial.ALGORITHM
        )
        user = asyncio.run(
            tutorial.get_current_user(
                SecurityScopes(scopes=list(reversed(scope_names))), valid_token
            )
        )
        self.assertEqual(len(user.username), len(username))

        extended_scopes = scope_names[:23] + [
            f"absent_{sum((position + 3) ** 2 for position in range(19))}"
        ]
        scope_failure = None
        try:
            asyncio.run(
                tutorial.get_current_user(
                    SecurityScopes(scopes=extended_scopes), valid_token
                )
            )
        except BaseException as error:
            scope_failure = error
        self.assertIsNotNone(scope_failure)

        malformed = "".join(chr(33 + (index * 17) % 80) for index in range(37))
        token_cases = [
            malformed,
            jwt.encode(
                base_payload,
                tutorial.SECRET_KEY[::-1],
                algorithm=tutorial.ALGORITHM,
            ),
            jwt.encode(
                {**base_payload, "exp": 1},
                tutorial.SECRET_KEY,
                algorithm=tutorial.ALGORITHM,
            ),
            jwt.encode(
                {**base_payload, "nbf": 4_102_444_800},
                tutorial.SECRET_KEY,
                algorithm=tutorial.ALGORITHM,
            ),
            jwt.encode(
                {**base_payload, "aud": f"aud-{sum(index**3 for index in range(17))}"},
                tutorial.SECRET_KEY,
                algorithm=tutorial.ALGORITHM,
            ),
            jwt.encode(base_payload, tutorial.SECRET_KEY, algorithm="HS384"),
            jwt.encode(
                {**base_payload, "sub": sum(index * 7 for index in range(9))},
                tutorial.SECRET_KEY,
                algorithm=tutorial.ALGORITHM,
            ),
            jwt.encode(
                {**base_payload, "jti": sum(index**2 for index in range(13))},
                tutorial.SECRET_KEY,
                algorithm=tutorial.ALGORITHM,
            ),
        ]

        propagated = []
        for token in token_cases:
            try:
                asyncio.run(
                    tutorial.get_current_user(SecurityScopes(scopes=[]), token)
                )
            except BaseException as error:
                propagated.append(error)

        with mock.patch.object(
            tutorial.jwt,
            "decode",
            return_value={
                "sub": sum(index * 5 for index in range(11)),
                "scope": " ".join(scope_names[::5]),
            },
        ):
            try:
                asyncio.run(
                    tutorial.get_current_user(
                        SecurityScopes(scopes=scope_names[::7]), valid_token
                    )
                )
            except BaseException as error:
                propagated.append(error)

        self.assertEqual(len(propagated), len(token_cases) + 1)
        self.assertTrue(
            all(getattr(error, "status_code", 0) // 100 == 4 for error in propagated)
        )


if __name__ == "__main__":
    unittest.main()
