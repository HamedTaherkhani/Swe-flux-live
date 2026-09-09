import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from haystack import Pipeline, component


@component
class VariablePorts:
    def __init__(self, input_names=(), output_names=()):
        component.set_input_types(self, **{name: int for name in input_names})
        component.set_output_types(self, **{name: int for name in output_names})

    def run(self, **kwargs):
        value = sum(item for item in kwargs.values() if isinstance(item, int))
        return {name: value for name in self.__haystack_output__._sockets_dict}


@component
class PipelineWrapper:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        component.set_input_types(self, feed=int)
        component.set_output_types(self, result=int)

    def run(self, **kwargs):
        return {"result": sum(kwargs.values())}


class TestMergeSuperComponentLoops(unittest.TestCase):
    def _exercise(self, scenario):
        digest = hashlib.sha256(("expanded-diagram:" + scenario).encode()).digest()
        outer = Pipeline()
        wrapper_count = 2 + digest[0] % 4

        for wrapper_index in range(wrapper_count):
            inner = Pipeline()
            node_count = 2 + digest[1 + wrapper_index] % 6

            for node_index in range(node_count):
                digest_index = 7 + wrapper_index * 7 + node_index
                socket_count = 1 + digest[digest_index % len(digest)] % 6
                inputs = tuple(f"in_{index}" for index in range(socket_count))
                outputs = (f"out_{wrapper_index}_{node_index}",)
                inner.add_component(
                    f"inner_{wrapper_index}_{node_index}",
                    VariablePorts(input_names=inputs, output_names=outputs),
                )

            source_name = f"source_{wrapper_index}"
            wrapper_name = f"wrapper_{wrapper_index}"
            sink_name = f"sink_{wrapper_index}"
            outer.add_component(source_name, VariablePorts(output_names=("out",)))
            outer.add_component(wrapper_name, PipelineWrapper(inner))
            outer.add_component(sink_name, VariablePorts(input_names=("value",)))
            outer.connect(f"{source_name}.out", f"{wrapper_name}.feed")
            outer.connect(f"{wrapper_name}.result", f"{sink_name}.value")

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / (scenario + ".bin")
            payload = scenario.encode()
            with patch("haystack.core.pipeline.base._to_mermaid_image", return_value=payload):
                outer.draw(path=image_path, super_component_expansion=True)
            self.assertEqual(image_path.read_bytes(), payload)
            self.assertGreater(len(outer.graph), wrapper_count)

    def test_amber_archipelago(self):
        self._exercise("amber-archipelago")

    def test_boreal_compass(self):
        self._exercise("boreal-compass")

    def test_cinder_delta(self):
        self._exercise("cinder-delta")

    def test_dappled_estuary(self):
        self._exercise("dappled-estuary")

    def test_ember_fjord(self):
        self._exercise("ember-fjord")

    def test_fallow_glacier(self):
        self._exercise("fallow-glacier")

    def test_gilded_harbor(self):
        self._exercise("gilded-harbor")

    def test_hushed_isthmus(self):
        self._exercise("hushed-isthmus")

    def test_indigo_junction(self):
        self._exercise("indigo-junction")

    def test_jasper_karst(self):
        self._exercise("jasper-karst")

    def test_kinetic_lagoon(self):
        self._exercise("kinetic-lagoon")

    def test_luminous_moraine(self):
        self._exercise("luminous-moraine")
