from __future__ import annotations

import random
import unittest

from pydantic import Field, create_model

from fastapi._compat import v2


class TestGetDefinitionsProgramState(unittest.TestCase):
    def test_generated_model_description_cleanup(self) -> None:
        rng = random.Random(8675309)
        alphabet = "abcdefghjkmnpqrstuvwxyz"
        model_count = 37
        fields: list[v2.ModelField] = []

        for index in range(model_count):
            token = "".join(rng.choice(alphabet) for _ in range(13))
            weight = sum((position + 3) * ord(char) for position, char in enumerate(token))
            omit_description = (weight + rng.randrange(97) + index * index) % 6 == 0
            description = None
            if not omit_description:
                prefix_words = [
                    token[(offset * 5 + index) % len(token)]
                    for offset in range(11)
                ]
                prefix = "".join(prefix_words)
                checksum = (weight * (index + 7) + rng.randrange(10_000)) % 104_729
                discarded = "".join(
                    rng.choice(alphabet) for _ in range(19 + index % 7)
                )
                description = (
                    f"{prefix.title()} schema phase {checksum} for generated payload"
                    f"\fdiscarded-{discarded}"
                )

            model = create_model(
                f"RuntimeModel{index}_{token[:6].title()}",
                __doc__=description,
                payload=(str, Field(min_length=1 + index % 5)),
                score=(int, Field(ge=-(weight % 23), le=weight % 211 + 50)),
            )
            fields.append(
                v2.ModelField(
                    field_info=v2.FieldInfo(annotation=model),
                    name=f"generated_{token}_{index}",
                    mode="serialization" if (weight + index) % 3 == 0 else "validation",
                )
            )

        field_mapping, definitions = v2.get_definitions(
            fields=fields,
            model_name_map={},
            separate_input_output_schemas=False,
        )

        self.assertEqual(len(field_mapping), model_count)
        self.assertEqual(len(definitions), model_count)
        described = [
            schema["description"]
            for schema in definitions.values()
            if "description" in schema
        ]
        self.assertGreater(len(described), model_count // 2)
        self.assertTrue(all("\f" not in value for value in described))
        self.assertTrue(all(value.endswith("generated payload") for value in described))
