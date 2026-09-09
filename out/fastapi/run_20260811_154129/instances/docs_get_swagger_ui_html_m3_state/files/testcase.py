import random
import unittest

from fastapi.openapi.docs import get_swagger_ui_html


class TestGeneratedSwaggerUI(unittest.TestCase):
    def test_generated_parameter_states(self) -> None:
        generator = random.Random(731_947)
        parameters = {}
        rolling = generator.randrange(1, 10_000)

        for slot in range(24):
            rolling = (rolling * 73 + generator.randrange(10_000) + slot**3) % 104_729
            key = f"option_{slot:02d}_{rolling:05x}"
            selector = (rolling + slot) % 4
            if selector == 0:
                value = bool((rolling // 7) % 2)
            elif selector == 1:
                value = {
                    "threshold": (rolling * (slot + 5)) % 9_973,
                    "tokens": [
                        chr(97 + ((rolling + offset * slot + offset**2) % 26))
                        for offset in range(5)
                    ],
                }
            elif selector == 2:
                value = [
                    (rolling ^ (offset * 257 + slot)) % 4_099
                    for offset in range(1 + slot % 5)
                ]
            else:
                value = "".join(
                    chr(65 + ((rolling // (offset + 1) + slot * offset) % 26))
                    for offset in range(7)
                )
            parameters[key] = value

        parameter_sets = [
            parameters,
            {
                key: (
                    {"mirror": value, "rank": index}
                    if index % 3 == 0
                    else value
                )
                for index, (key, value) in enumerate(reversed(parameters.items()))
            },
        ]

        responses = []
        for invocation, swagger_parameters in enumerate(parameter_sets):
            suffix = sum(ord(character) for character in tuple(swagger_parameters)[invocation])
            responses.append(
                get_swagger_ui_html(
                    openapi_url=f"/schema/{suffix:x}.json",
                    title=f"Generated API {invocation}-{suffix % 97}",
                    swagger_js_url=f"/assets/ui-{(suffix * 17) % 1009}.js",
                    swagger_css_url=f"/assets/ui-{(suffix * 19) % 1013}.css",
                    swagger_favicon_url=f"/assets/icon-{(suffix * 23) % 1021}.png",
                    oauth2_redirect_url=(
                        f"/oauth/{(suffix * 29) % 1031}" if invocation == 0 else None
                    ),
                    init_oauth=(
                        {
                            "clientId": f"client-{(suffix * 31) % 1033:x}",
                            "scopes": {
                                f"scope-{index}": bool((suffix + index) % 2)
                                for index in range(6)
                            },
                        }
                        if invocation == 0
                        else None
                    ),
                    swagger_ui_parameters=swagger_parameters,
                )
            )

        self.assertEqual(len(responses), len(parameter_sets))
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertTrue(all(response.media_type == "text/html" for response in responses))
        self.assertNotEqual(responses[0].body, responses[1].body)
