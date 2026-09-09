import base64
import builtins
import random
import unittest
from unittest.mock import patch

from haystack.components.routers import FileTypeRouter
from haystack.dataclasses import ByteStream


class TestFileTypeRouterRunExceptions(unittest.TestCase):
    def test_catches_generated_conversion_failures(self):
        encoded_names = (
            "QXJpdGhtZXRpY0Vycm9y",
            "QXNzZXJ0aW9uRXJyb3I=",
            "QXR0cmlidXRlRXJyb3I=",
            "QmxvY2tpbmdJT0Vycm9y",
            "QnJva2VuUGlwZUVycm9y",
            "QnVmZmVyRXJyb3I=",
            "Qnl0ZXNXYXJuaW5n",
            "Q2hpbGRQcm9jZXNzRXJyb3I=",
            "Q29ubmVjdGlvbkFib3J0ZWRFcnJvcg==",
            "Q29ubmVjdGlvbkVycm9y",
            "Q29ubmVjdGlvblJlZnVzZWRFcnJvcg==",
            "Q29ubmVjdGlvblJlc2V0RXJyb3I=",
            "RGVwcmVjYXRpb25XYXJuaW5n",
            "RU9GRXJyb3I=",
            "RmlsZUV4aXN0c0Vycm9y",
            "RmlsZU5vdEZvdW5kRXJyb3I=",
            "RmxvYXRpbmdQb2ludEVycm9y",
            "RnV0dXJlV2FybmluZw==",
            "SW1wb3J0RXJyb3I=",
            "SW1wb3J0V2FybmluZw==",
            "SW5kZXhFcnJvcg==",
            "SW50ZXJydXB0ZWRFcnJvcg==",
            "SXNBRGlyZWN0b3J5RXJyb3I=",
            "S2V5RXJyb3I=",
            "TG9va3VwRXJyb3I=",
            "TWVtb3J5RXJyb3I=",
            "TW9kdWxlTm90Rm91bmRFcnJvcg==",
            "TmFtZUVycm9y",
            "Tm90QURpcmVjdG9yeUVycm9y",
            "Tm90SW1wbGVtZW50ZWRFcnJvcg==",
            "T1NFcnJvcg==",
            "T3ZlcmZsb3dFcnJvcg==",
            "UGVuZGluZ0RlcHJlY2F0aW9uV2FybmluZw==",
            "UGVybWlzc2lvbkVycm9y",
            "UHJvY2Vzc0xvb2t1cEVycm9y",
            "UmVmZXJlbmNlRXJyb3I=",
            "UmVzb3VyY2VXYXJuaW5n",
            "UnVudGltZUVycm9y",
            "UnVudGltZVdhcm5pbmc=",
            "U3RvcEFzeW5jSXRlcmF0aW9u",
            "U3RvcEl0ZXJhdGlvbg==",
            "U3ludGF4RXJyb3I=",
            "U3ludGF4V2FybmluZw==",
            "U3lzdGVtRXJyb3I=",
            "VGltZW91dEVycm9y",
            "VHlwZUVycm9y",
            "VW5ib3VuZExvY2FsRXJyb3I=",
            "VW5pY29kZUVycm9y",
            "VW5pY29kZVdhcm5pbmc=",
            "VXNlcldhcm5pbmc=",
            "VmFsdWVFcnJvcg==",
            "V2FybmluZw==",
            "WmVyb0RpdmlzaW9uRXJyb3I=",
        )
        exception_types = [
            getattr(builtins, base64.b64decode(token).decode("ascii")) for token in encoded_names
        ]

        rng = random.Random(sum(token.count("R") for token in encoded_names))
        schedule = [rng.randrange(len(exception_types)) for _ in range(96)]
        sources = [
            ByteStream(
                data=bytes((position * 29 + offset * 17) % 251 for offset in range(23)),
                mime_type=f"application/x-generated-{position % 11}",
            )
            for position in range(len(schedule))
        ]
        metadata = [
            {"batch": position // 7, "token": (position * position + 31) % 97}
            for position in range(len(sources))
        ]

        call_index = 0

        def fail_conversion(source):
            nonlocal call_index
            selected = exception_types[schedule[call_index]]
            message_seed = sum(source.data) + metadata[call_index]["token"]
            call_index += 1
            raise selected(f"conversion-{message_seed:x}-{call_index * 13:x}")

        router = FileTypeRouter(mime_types=[r"application/x-generated-\d+"])
        with patch(
            "haystack.components.routers.file_type_router.get_bytestream_from_source",
            side_effect=fail_conversion,
        ):
            result = router.run(sources=sources, meta=metadata)

        self.assertEqual(call_index, len(sources))
        self.assertEqual(set(result), {"failed"})
        self.assertEqual(sum(map(len, result.values())), len(schedule))
