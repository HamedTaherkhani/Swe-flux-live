import builtins
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from llamafactory.model import adapter as adapter_module


class _GeneratedModel:
    def __init__(self, rng, failure_class, failure_message):
        self.config = SimpleNamespace(num_hidden_layers=rng.randrange(24, 40))
        self._rng = rng
        self._failure_class = failure_class
        self._failure_message = failure_message
        self.yielded = 0
        self.parameter_total = rng.randrange(21, 29)

    def named_parameters(self):
        stems = ("encoder", "decoder", "bridge", "output")
        for index in range(self.parameter_total):
            branch = (self._rng.randrange(0, 97) + index * index) % 3
            stem = stems[(self._rng.randrange(len(stems)) + index) % len(stems)]
            if branch == 0:
                name = f"{stem}.chunk_{index}.0.projection.weight"
            elif branch == 1:
                name = f"{stem}.chunk_{index}.1.projection.bias"
            else:
                name = f"{stem}_bank_{index}.projection.weight"
            self.yielded += 1
            yield name, object()

        raise self._failure_class(self._failure_message)


class TestFreezeTuningExceptionPropagation(unittest.TestCase):
    def test_seeded_parameter_scan_failure(self):
        rng = random.Random(sum((index + 11) * ord(char) for index, char in enumerate(self.id())))
        exception_name = "".join(chr(code) for code in (82, 117, 110, 116, 105, 109, 101, 69, 114, 114, 111, 114))
        failure_class = getattr(builtins, exception_name)

        rolling = rng.randrange(10000, 99999)
        fragments = []
        for width in range(6, 14):
            samples = [rng.randrange(31, 4093) for _ in range(width)]
            rolling = (rolling * 257 + sum((offset + 3) * value for offset, value in enumerate(samples))) % 1000003
            fragments.append(format(rolling ^ rng.randrange(4096, 65536), "x"))
        failure_message = ":".join(fragments)

        model = _GeneratedModel(rng, failure_class, failure_message)
        model_args = SimpleNamespace(quantization_bit=None)
        finetuning_args = SimpleNamespace(
            finetuning_type="freeze",
            pure_bf16=False,
            use_badam=False,
            use_llama_pro=False,
            freeze_trainable_layers=5,
            freeze_trainable_modules=["projection"],
            freeze_extra_modules=None,
        )

        caught = []
        with (
            patch.object(adapter_module, "is_deepspeed_zero3_enabled", return_value=False),
            patch.object(adapter_module.logger, "info_rank0", return_value=None),
        ):
            try:
                adapter_module.init_adapter(
                    model.config,
                    model,
                    model_args,
                    finetuning_args,
                    is_trainable=True,
                )
            except BaseException as exc:
                caught.append(exc)

        self.assertTrue(caught)
        self.assertEqual(len(caught), int(bool(model.yielded)))
        self.assertGreater(model.yielded, len(fragments) * 2)
        self.assertGreater(len(str(caught[0]).split(":")), len(stems := ("a", "b", "c")))
