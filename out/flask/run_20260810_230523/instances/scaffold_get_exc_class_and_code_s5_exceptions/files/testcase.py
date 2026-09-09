import random
import unittest

from flask import Flask
from werkzeug.exceptions import default_exceptions


class TestErrorHandlerRegistration(unittest.TestCase):
    def test_seeded_registration_matrix_then_instance(self):
        app = Flask(__name__)
        rng = random.Random(20260811517)
        codes = sorted(default_exceptions)
        generated_classes = [
            type(
                "".join(chr(65 + rng.randrange(26)) for _ in range(9)),
                (Exception,),
                {},
            )
            for _ in range(13)
        ]

        def handler(error):
            return str(error)

        chosen_codes = []
        for index in range(39):
            code = codes[(rng.randrange(len(codes)) + index * 7) % len(codes)]
            chosen_codes.append(code)
            mode = index % 3
            if mode == 0:
                registration_key = code
            elif mode == 1:
                registration_key = default_exceptions[code]
            else:
                registration_key = generated_classes[
                    (rng.randrange(len(generated_classes)) + index) % len(generated_classes)
                ]
            app.register_error_handler(registration_key, handler)

        signature = sum(
            (index + 3) * code for index, code in enumerate(chosen_codes)
        )
        class_name = "".join(
            chr(65 + ((signature >> shift) + rng.randrange(26)) % 26)
            for shift in range(0, 45, 5)
        )
        payload = "".join(
            chr(97 + (signature * (index + 5) + rng.randrange(26)) % 26)
            for index in range(17)
        )
        exception_instance = type(class_name, (Exception,), {})(payload)

        self.assertTrue(app.error_handler_spec[None])
        with self.assertRaises(BaseException) as caught:
            app.register_error_handler(exception_instance, handler)
        self.assertEqual(len(caught.exception.args), 1)
