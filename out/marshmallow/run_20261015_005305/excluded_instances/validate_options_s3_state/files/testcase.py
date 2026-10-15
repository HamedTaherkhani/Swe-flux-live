import random
import unittest

from marshmallow.validate import OneOf


SYLLABLES = ["ka", "ro", "mi", "tsu", "ne", "zo", "lu", "pe"]


def make_word(rng, parts):
    return "".join(rng.choice(SYLLABLES) for _ in range(parts))


class OneOfOptionsTest(unittest.TestCase):
    def test_options_label_padding(self):
        rng = random.Random(4127)
        validators = []
        for i in range(9):
            n_choices = rng.randint(1, 5)
            n_labels = rng.randint(0, 6)
            choices = [rng.randint(0, 99) * (i + 1) % 97 for _ in range(n_choices)]
            labels = [make_word(rng, 1 + (j + i) % 3).upper() for j in range(n_labels)]
            if i % 4 == 2:
                # labels given lazily
                labels = (lab.lower() for lab in labels)
            elif i % 4 == 3:
                labels = labels[::-1]
            validators.append(OneOf(choices, labels))

        total = 0
        empties = 0
        for idx, validator in enumerate(validators):
            getter = str if idx % 2 == 0 else (lambda c: c * 3 % 11)
            pairs = list(validator.options(getter))
            self.assertEqual(len(pairs), len(tuple(validator.choices)))
            total += len(pairs)
            empties += sum(1 for _, label in pairs if label == "")
        self.assertGreater(total, 10)
        self.assertGreater(empties, 0)
