import dataclasses
import datetime
import decimal
import random
import unittest
import uuid

from flask import Flask
from flask.json.provider import DefaultJSONProvider


@dataclasses.dataclass
class Packet:
    label: str
    amount: decimal.Decimal
    marker: uuid.UUID


class HtmlToken:
    def __init__(self, value):
        self.value = value

    def __html__(self):
        return f"<token-{self.value:x}>"


def build_payload(rng, round_index):
    payload = []
    rolling = rng.getrandbits(31) ^ ((round_index + 17) * 65_537)

    for position in range(27 + rolling % 9):
        rolling = (
            (rolling * 1_103_515_245 + 12_345)
            ^ rng.getrandbits(29)
            ^ (position * 8_191)
        ) & 0x7FFF_FFFF
        selector = (rolling ^ (rolling >> 7) ^ round_index ^ position) % 6

        if selector == 0:
            payload.append(
                datetime.date(
                    1996 + rolling % 27,
                    1 + (rolling // 31) % 12,
                    1 + (rolling // 997) % 27,
                )
            )
        elif selector == 1:
            payload.append(
                decimal.Decimal((rolling % 900_001) - 450_000).scaleb(
                    -((position % 4) + 1)
                )
            )
        elif selector == 2:
            payload.append(
                uuid.UUID(
                    int=((rolling << 97) ^ (position << 61) ^ rng.getrandbits(96))
                    & ((1 << 128) - 1)
                )
            )
        elif selector == 3:
            payload.append(
                Packet(
                    label=f"packet-{round_index:x}-{rolling % 4_093:x}",
                    amount=decimal.Decimal(rolling % 70_001).scaleb(-3),
                    marker=uuid.UUID(
                        int=((rolling << 83) ^ rng.getrandbits(104))
                        & ((1 << 128) - 1)
                    ),
                )
            )
        elif selector == 4:
            payload.append(HtmlToken(rolling ^ (round_index << 12) ^ position))
        else:
            payload.append(
                {
                    "bits": [bool(rolling & (1 << shift)) for shift in range(7)],
                    "value": (rolling ^ (position * 257)) % 100_003,
                }
            )

    return payload


class TestProviderResponseCalls(unittest.TestCase):
    def test_seeded_response_matrix(self):
        app = Flask(__name__)
        provider = DefaultJSONProvider(app)
        rng = random.Random(8_642_197)
        seen_lengths = set()

        for round_index in range(19):
            payload = build_payload(rng, round_index)
            seen_lengths.add(len(payload))

            mode_seed = rng.getrandbits(17) ^ (round_index * 313)
            provider.compact = (None, False, True)[mode_seed % 3]
            app.debug = bool((mode_seed >> 5) & 1)

            call_style = (mode_seed ^ len(payload) ^ round_index) % 3
            if call_style == 0:
                response = provider.response(payload)
            elif call_style == 1:
                response = provider.response(*payload)
            else:
                response = provider.response(
                    **{
                        f"item_{position:02x}_{mode_seed % 29:02x}": value
                        for position, value in enumerate(payload)
                    }
                )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.is_json)
            self.assertTrue(response.get_data().endswith(b"\n"))

        self.assertGreater(len(seen_lengths), 3)
