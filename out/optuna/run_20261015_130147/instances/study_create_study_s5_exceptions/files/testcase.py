import random
import unittest

import optuna
from optuna.study import StudyDirection
from optuna.study.study import create_study


DIRECTION_POOL = [
    "minimize",
    "maximize",
    StudyDirection.MAXIMIZE,
    StudyDirection.MINIMIZE,
    "Maximize",
    "minimise",
]


class CreateStudyEscapeTest(unittest.TestCase):
    def test_first_escaping_error(self):
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        rng = random.Random(19)
        storage = optuna.storages.InMemoryStorage()
        stems = ["".join(rng.choice("bcdfghkmnpqrstvz") for _ in range(4)) for _ in range(9)]

        completed = 0
        escaped = None
        for _ in range(60):
            name = f"{rng.choice(stems)}-{rng.randrange(3)}"
            load = rng.random() < 0.8
            kind = rng.random()
            kwargs = {}
            if kind < 0.35:
                kwargs["direction"] = rng.choice(DIRECTION_POOL[:4])
            elif kind < 0.9:
                n = rng.randint(1, 4)
                kwargs["directions"] = [
                    rng.choice(DIRECTION_POOL[: 4 if rng.random() < 0.9 else 6])
                    for _ in range(n)
                ]
            try:
                study = create_study(
                    storage=storage, study_name=name, load_if_exists=load, **kwargs
                )
            except Exception as e:  # noqa: BLE001
                escaped = e
                break
            self.assertEqual(study.study_name, name)
            completed += 1

        self.assertIsNotNone(escaped)
        self.assertGreater(completed, 15)
        self.assertGreater(len(storage.get_all_studies()), 5)


if __name__ == "__main__":
    unittest.main()
