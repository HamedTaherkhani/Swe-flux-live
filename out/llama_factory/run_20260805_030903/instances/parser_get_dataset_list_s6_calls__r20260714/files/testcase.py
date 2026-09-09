import json
import os
import tempfile
import unittest

from src.llamafactory.data.parser import get_dataset_list


class TestParserGetDatasetListS6Calls(unittest.TestCase):
    def setUp(self) -> None:
        self._old_ms = os.environ.get("USE_MODELSCOPE_HUB")
        self._old_om = os.environ.get("USE_OPENMIND_HUB")

    def tearDown(self) -> None:
        if self._old_ms is None:
            os.environ.pop("USE_MODELSCOPE_HUB", None)
        else:
            os.environ["USE_MODELSCOPE_HUB"] = self._old_ms

        if self._old_om is None:
            os.environ.pop("USE_OPENMIND_HUB", None)
        else:
            os.environ["USE_OPENMIND_HUB"] = self._old_om

    def _invoke_online(self, name: str, use_ms: bool, use_om: bool):
        os.environ["USE_MODELSCOPE_HUB"] = "1" if use_ms else "0"
        os.environ["USE_OPENMIND_HUB"] = "1" if use_om else "0"
        return get_dataset_list([name], "ONLINE")

    def _invoke_local(self, dataset_dir: str):
        os.environ["USE_MODELSCOPE_HUB"] = "0"
        os.environ["USE_OPENMIND_HUB"] = "0"
        return get_dataset_list(["alpha", "beta", "gamma"], dataset_dir)

    def test_dynamic_callee_sequence_third_invocation(self):
        first = self._invoke_online("online_ms", use_ms=True, use_om=False)
        self.assertEqual(first[0].load_from, "ms_hub")
        self.assertEqual(first[0].dataset_name, "online_ms")

        second = self._invoke_online("online_hf", use_ms=False, use_om=False)
        self.assertEqual(second[0].load_from, "hf_hub")
        self.assertEqual(second[0].dataset_name, "online_hf")

        with tempfile.TemporaryDirectory() as tmp_dir:
            info_path = os.path.join(tmp_dir, "dataset_info.json")
            dataset_info = {
                "alpha": {
                    "hf_hub_url": "hf://alpha",
                    "ms_hub_url": "ms://alpha",
                    "om_hub_url": "om://alpha",
                    "columns": {"prompt": "instruction_alpha"},
                },
                "beta": {
                    "om_hub_url": "om://beta",
                    "columns": {"response": "answer_beta"},
                },
                "gamma": {
                    "ms_hub_url": "ms://gamma",
                    "columns": {"query": "question_gamma"},
                },
            }
            with open(info_path, "w", encoding="utf-8") as fout:
                json.dump(dataset_info, fout, sort_keys=True)

            third = self._invoke_local(tmp_dir)

        self.assertEqual([item.load_from for item in third], ["hf_hub", "om_hub", "ms_hub"])
        self.assertEqual([item.dataset_name for item in third], ["hf://alpha", "om://beta", "ms://gamma"])
        self.assertEqual(third[0].prompt, "instruction_alpha")
        self.assertEqual(third[1].response, "answer_beta")
        self.assertEqual(third[2].query, "question_gamma")

