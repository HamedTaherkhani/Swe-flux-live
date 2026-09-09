import random
import unittest
from unittest.mock import patch

import networkx

from haystack.core.pipeline.draw import _to_mermaid_image


class TestMermaidParameterValidation(unittest.TestCase):
    def test_generated_render_parameter_matrix(self):
        rng = random.Random(84631)
        formats = ["img", "svg", "pdf"]
        themes = ["default", "neutral", "dark", "forest"]
        image_types = ["jpeg", "png", "webp"]
        parameter_sets = []

        for index in range(18):
            output_format = formats[index % len(formats)]
            params = {
                "format": output_format,
                "theme": themes[(index + rng.randrange(len(themes))) % len(themes)],
                "bgColor": f"!shade{rng.randrange(1000, 9999)}",
                "width": 240 + rng.randrange(320),
                "scale": 1 + (index % 3),
            }
            if output_format == "img":
                params["type"] = image_types[(index + rng.randrange(len(image_types))) % len(image_types)]
            if output_format == "pdf":
                params["fit"] = index % 4 == 0
                params["paper"] = f"a{3 + (index % 3)}"
                params["landscape"] = index % 2 == 0
            parameter_sets.append(params)

        class Response:
            status_code = 200
            content = bytes((index * 29 + 7) % 256 for index in range(31))

        graph = networkx.MultiDiGraph()
        rendered = []
        with patch("haystack.core.pipeline.draw.requests.get", return_value=Response()) as request:
            for params in parameter_sets:
                rendered.append(_to_mermaid_image(graph, params=dict(params)))

            malformed = dict(parameter_sets[-1])
            malformed["landscape"] = sum(
                len(key) * (position + 1) for position, key in enumerate(sorted(malformed))
            )
            caught = None
            try:
                _to_mermaid_image(graph, params=malformed)
            except BaseException as exc:
                caught = exc

        self.assertEqual(len(rendered), len(parameter_sets))
        self.assertTrue(all(item == Response.content for item in rendered))
        self.assertEqual(request.call_count, len(parameter_sets))
        self.assertIsNotNone(caught)
        self.assertTrue(str(caught).endswith("."))
