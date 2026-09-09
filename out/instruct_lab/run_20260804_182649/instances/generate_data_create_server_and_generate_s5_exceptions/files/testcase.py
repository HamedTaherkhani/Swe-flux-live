import builtins
import importlib
import random
import unittest
from unittest import mock

import openai

from instructlab import client_utils
from instructlab.data import generate_data as data_entry
from instructlab.defaults import ILAB_PROCESS_MODES
from instructlab.model.backends import backends
from instructlab.process import process as process_support
from instructlab.sdg import utils as sdg_utils


sdg_generation = importlib.import_module("instructlab.sdg.generate_data")


def _usable_exception_classes():
    pending = list(BaseException.__subclasses__())
    seen = set()
    candidates = []
    while pending:
        candidate = pending.pop()
        if candidate in seen:
            continue
        seen.add(candidate)
        pending.extend(candidate.__subclasses__())
        if candidate.__module__ != builtins.__name__:
            continue
        if not issubclass(candidate, Exception) or candidate is Exception:
            continue
        try:
            instance = candidate("probe")
        except BaseException:
            continue
        if type(instance) is candidate:
            candidates.append(candidate)
    candidates.sort(key=lambda item: item.__qualname__)
    random.Random(73129).shuffle(candidates)
    return candidates


class TestGeneratedDataFailureMatrix(unittest.TestCase):
    def test_public_entry_point_handles_runtime_failure_matrix(self):
        exception_classes = _usable_exception_classes()
        scenario_count = min(len(exception_classes), 17) + 4
        self.assertGreater(scenario_count, 15)

        state = {
            "backend_calls": 0,
            "failure_calls": 0,
            "generation_calls": 0,
            "completion_calls": 0,
        }

        class _Backend:
            def __init__(self, ordinal):
                self.ordinal = ordinal

            def get_backend_type(self):
                return mock.sentinel.synthetic_backend

            def run_detached(self, **_kwargs):
                if self.ordinal % 5 != 4:
                    selected = exception_classes[state["failure_calls"]]
                    state["failure_calls"] += 1
                    token = "".join(
                        chr(97 + ((self.ordinal * 7 + offset * 11) % 26))
                        for offset in range(13)
                    )
                    raise selected(token)
                return f"http://127.0.0.1:{8100 + self.ordinal}"

            def shutdown(self):
                return None

        def select_backend(**_kwargs):
            ordinal = state["backend_calls"]
            state["backend_calls"] += 1
            return _Backend(ordinal)

        def invoke_in_foreground(
            process_mode, process_type, target, extra_imports, **kwargs
        ):
            del process_type, extra_imports
            return target(
                **kwargs,
                log_file=None,
                local_uuid=f"job-{state['backend_calls']:03d}",
                process_mode=process_mode,
            )

        def fail_generation(**kwargs):
            state["generation_calls"] += 1
            material = "|".join(
                str(kwargs[key])
                for key in sorted(kwargs)
                if key in {"model_name", "num_instructions_to_generate", "pipeline"}
            )
            exception_name = "".join(chr(value) for value in (71, 101, 110, 101, 114, 97, 116, 101, 69, 120, 99, 101, 112, 116, 105, 111, 110))
            exception_class = getattr(sdg_utils, exception_name)
            raise exception_class(
                "".join(reversed(material))
                + ":"
                + str(sum(ord(character) for character in material))
            )

        def record_completion(**_kwargs):
            state["completion_calls"] += 1

        escaped = []
        with (
            mock.patch.object(process_support, "add_process", invoke_in_foreground),
            mock.patch.object(backends, "select_backend", select_backend),
            mock.patch.object(client_utils, "http_client", return_value=mock.sentinel.http),
            mock.patch.object(openai, "OpenAI", return_value=mock.sentinel.client),
            mock.patch.object(sdg_generation, "generate_data", fail_generation),
            mock.patch.object(process_support, "complete_process", record_completion),
        ):
            for index in range(scenario_count):
                try:
                    data_entry.gen_data(
                        serve_cfg=mock.sentinel.serve_config,
                        model_path=f"generated-model-{index * index + 3 * index + 19}",
                        num_cpus=(index % 4) + 1,
                        sdg_scale_factor=(index + 2) * 3,
                        taxonomy_path=f"/virtual/taxonomy/{index:02d}",
                        taxonomy_base="origin/main",
                        output_dir=f"/virtual/output/{index:02d}",
                        quiet=bool(index % 2),
                        endpoint_url=None,
                        api_key=f"key-{index * 13 + 5}",
                        yaml_rules=None,
                        chunk_word_count=120 + index,
                        server_ctx_size=4096 + index * 8,
                        http_client_params={
                            "tls_client_cert": "",
                            "tls_client_key": "",
                            "tls_client_passwd": "",
                            "tls_insecure": "",
                        },
                        model_family="granite",
                        pipeline=f"pipeline-{(index * 7) % 11}",
                        enable_serving_output=bool(index % 3),
                        batch_size=(index % 5) + 1,
                        gpus=None,
                        checkpoint_dir=None,
                        max_num_tokens=512 + index,
                        system_prompt=None,
                        use_legacy_pretraining_format=False,
                        process_mode=ILAB_PROCESS_MODES.DETACHED,
                        log_level=20,
                    )
                except BaseException as exc:
                    escaped.append(exc)

        self.assertEqual(len(escaped), scenario_count)
        self.assertTrue(all(item.__cause__ is not None for item in escaped))
        self.assertGreater(state["generation_calls"], 0)
        self.assertGreater(state["completion_calls"], state["generation_calls"])
