import random
import unittest

from flask import Flask
from werkzeug.exceptions import default_exceptions


class TestErrorHandlerRegistration(unittest.TestCase):
    def test_seeded_registration_matrix_then_instance(self):
        app = Flask(__name__)
        rng = random.Random(91736452801)
        codes = sorted(default_exceptions)
        generated_classes = [
            type(
                "".join(chr(65 + rng.randrange(26)) for _ in range(17)),
                (
                    default_exceptions[
                        codes[
                            (rng.randrange(len(codes)) + rng.randrange(len(codes)))
                            % len(codes)
                        ]
                    ],
                )
                if rng.randrange(2)
                else (Exception,),
                {},
            )
            for _ in range(53)
        ]

        def handler(error):
            return str(error)

        chosen_codes = []
        for index in range(211):
            code = codes[(rng.randrange(len(codes)) + index * 13) % len(codes)]
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
            (index + 11) * code for index, code in enumerate(chosen_codes)
        )
        class_name = "".join(
            chr(65 + ((signature >> shift) + rng.randrange(26)) % 26)
            for shift in range(0, 96, 3)
        )
        payload = "".join(
            chr(97 + (signature * (index + 17) + rng.randrange(26)) % 26)
            for index in range(41)
        )
        exception_instance = type(class_name, (Exception,), {})(payload)

        self.assertTrue(app.error_handler_spec[None])
        with self.assertRaises(BaseException) as caught:
            app.register_error_handler(exception_instance, handler)
        self.assertEqual(len(caught.exception.args), 1)
