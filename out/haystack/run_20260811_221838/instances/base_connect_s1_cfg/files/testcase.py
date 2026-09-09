import json
import random
import unittest

from haystack import Pipeline, component


@component
class DenseSource:
    def __init__(self):
        component.set_output_types(self, bridge=int, north=int, east=int, west=int)

    def run(self):
        return {"bridge": 1, "north": 2, "east": 3, "west": 4}


@component
class DenseSink:
    def __init__(self):
        component.set_input_types(self, bridge=int, south=int, upper=int, lower=int)

    def run(self, **kwargs):
        return {}


class TestIndirectDenseConnections(unittest.TestCase):
    def test_loads_generated_pipeline(self):
        rng = random.Random(73129)
        pair_count = 19
        labels = rng.sample(range(pair_count * 11, pair_count * 97), pair_count)
        order = list(range(pair_count))
        rng.shuffle(order)

        source_type = f"{DenseSource.__module__}.{DenseSource.__qualname__}"
        sink_type = f"{DenseSink.__module__}.{DenseSink.__qualname__}"
        components = {}
        pairs = []
        for index, label in enumerate(labels):
            source_name = f"source_{index}_{label:x}"
            sink_name = f"sink_{index}_{(label * label + index):x}"
            components[source_name] = {"type": source_type, "init_parameters": {}}
            components[sink_name] = {"type": sink_type, "init_parameters": {}}
            pairs.append((source_name, sink_name))

        connections = []
        midpoint = len(order) // 2
        for position, pair_index in enumerate(order):
            source_name, sink_name = pairs[pair_index]
            if position == midpoint:
                connections.append({"sender": source_name, "receiver": sink_name})
            else:
                connections.append(
                    {"sender": f"{source_name}.bridge", "receiver": f"{sink_name}.bridge"}
                )

        payload = {
            "metadata": {"seed_tag": hex(sum(labels) ^ len(connections))},
            "components": components,
            "connections": connections,
        }
        pipe = Pipeline.loads(json.dumps(payload, sort_keys=True))

        self.assertEqual(pipe.graph.number_of_nodes(), pair_count * 2)
        self.assertEqual(pipe.graph.number_of_edges(), len(connections))
