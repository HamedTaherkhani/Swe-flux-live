import random
import unittest

import jwt

from docs_src.security import tutorial004_py310 as tutorial


class TestGetCurrentUserExceptionKinds(unittest.IsolatedAsyncioTestCase):
    async def test_seeded_token_matrix(self):
        variant_count = 11
        selectors = list(range(variant_count)) * 5
        seed_text = tutorial.SECRET_KEY[::7]
        random.Random(sum(map(ord, seed_text))).shuffle(selectors)

        known_username = next(iter(tutorial.fake_users_db))
        outcomes = []

        for index, selector in enumerate(selectors):
            claims = {"sub": known_username}
            signing_key = tutorial.SECRET_KEY
            algorithm = tutorial.ALGORITHM

            if selector == 0:
                token = format(index * variant_count + selector, "x") * (index % 5 + 1)
            else:
                if selector == 1:
                    claims["exp"] = -(index + 1)
                elif selector == 2:
                    claims["nbf"] = 2 ** (variant_count * 4)
                elif selector == 3:
                    claims["aud"] = f"service-{index % variant_count}"
                elif selector == 4:
                    signing_key = tutorial.SECRET_KEY[::-1]
                elif selector == 5:
                    algorithm = "HS384"
                elif selector == 6:
                    claims["sub"] = index
                elif selector == 7:
                    claims["jti"] = index
                elif selector == 8:
                    claims.pop("sub")
                elif selector == 9:
                    claims["sub"] = f"user-{index * variant_count:x}"

                token = jwt.encode(claims, signing_key, algorithm=algorithm)

            try:
                user = await tutorial.get_current_user(token)
            except BaseException:
                outcomes.append(False)
            else:
                outcomes.append(user.username == known_username)

        self.assertEqual(len(outcomes), len(selectors))
        self.assertEqual(sum(outcomes), selectors.count(max(selectors)))
        self.assertTrue(any(not outcome for outcome in outcomes))
