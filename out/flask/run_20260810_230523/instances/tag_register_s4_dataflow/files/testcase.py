import unittest

from flask.json.tag import JSONTag
from flask.json.tag import TaggedJSONSerializer


class TestTaggedJSONSerializerRegister(unittest.TestCase):
    def test_generated_registration_paths(self):
        serializer = TaggedJSONSerializer()
        failures = 0
        successful = 0

        for position in range(36):
            residue = (position * position + 3 * position + 7) % 13
            generated_key = "" if residue % 6 == 0 else f" q{residue}"
            tag_class = type(
                f"GeneratedTag{position}",
                (JSONTag,),
                {"key": generated_key},
            )
            force = ((position * 11 + residue) % 7) not in {0, 3}
            index = None if (position ^ residue) % 4 else (position * 5) % (
                len(serializer.order) + 1
            )

            try:
                serializer.register(
                    tag_class,
                    force=force,
                    index=index,
                )
            except KeyError:
                failures += 1
            else:
                successful += 1

        self.assertGreater(failures, 0)
        self.assertGreater(successful, failures)
        self.assertGreater(len(serializer.order), len(serializer.default_tags))
        self.assertTrue(all(tag.serializer is serializer for tag in serializer.order))
