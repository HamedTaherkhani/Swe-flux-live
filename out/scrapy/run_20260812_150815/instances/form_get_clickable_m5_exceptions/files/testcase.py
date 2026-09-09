from __future__ import annotations

import unittest
import warnings

from scrapy.http import FormRequest, HtmlResponse


class VisibleCriteria(dict[str, str | int]):
    """Let an index choose a candidate without adding it to the later XPath."""

    def items(self):  # type: ignore[override]
        return ((key, value) for key, value in super().items() if key != "nr")


class TestGetClickableExceptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        warnings.filterwarnings("ignore", category=DeprecationWarning)

    def make_response(self, seed: int, size: int, groups: int) -> HtmlResponse:
        state = seed * 41 + size
        controls: list[str] = []
        for index in range(size):
            state = (state * 73 + index * 19 + seed) % 1009
            controls.append(
                f'<input type="text" name="field_{seed}_{index}" value="{state}">'
            )
            if (state + index) % 3:
                controls.append(
                    f'<button type="submit" name="batch_{seed % groups}" '
                    f'value="{(state + seed) % 211}">send</button>'
                )
            else:
                controls.append(
                    f'<input type="image" name="image_{seed}_{index}" '
                    f'value="{(state * 3 + index) % 223}">'
                )
        controls.append(
            f'<input type="submit" name="solo_{seed}" value="{state % 227}">'
        )
        body = (
            f'<form action="/submit/{(seed * size) % 97}" method="post">'
            + "".join(controls)
            + "</form>"
        )
        return HtmlResponse(
            url=f"https://example.invalid/forms/{seed}/",
            body=body,
            encoding="utf-8",
        )

    def build(
        self,
        seed: int,
        size: int,
        groups: int,
        clickdata: dict[str, str | int] | None,
    ) -> FormRequest:
        return FormRequest.from_response(
            self.make_response(seed, size, groups),
            clickdata=clickdata,
        )

    def test_default_click_uses_first_control(self) -> None:
        request = self.build(7, 19, 4, None)
        self.assertTrue(request.url.startswith("https://"))
        self.assertIsInstance(request.body, bytes)

    def test_existing_positive_number(self) -> None:
        seed, size = 13, 22
        request = self.build(seed, size, 5, {"nr": (seed + size) % 7})
        self.assertGreater(len(request.body), 0)

    def test_unique_generated_name(self) -> None:
        seed = 17
        request = self.build(seed, 25, 6, {"name": f"solo_{seed}"})
        self.assertEqual(request.method, "POST")

    def test_absent_generated_name(self) -> None:
        seed, size = 23, 21
        missing = f"missing_{(seed * size + 1) % 997}"
        with self.assertRaises(Exception):
            self.build(seed, size, 4, {"name": missing})

    def test_repeated_generated_name(self) -> None:
        seed = 29
        repeated = f"batch_{seed % 3}"
        with self.assertRaises(Exception):
            self.build(seed, 27, 3, {"name": repeated})

    def test_empty_criteria_matches_many_nodes(self) -> None:
        with self.assertRaises(Exception):
            self.build(31, 18, 5, {})

    def test_large_positive_number_kept_in_xpath(self) -> None:
        seed, size = 37, 24
        response = self.make_response(seed, size, 4)
        outside = len(response.text) * (seed + size)
        with self.assertRaises(Exception):
            FormRequest.from_response(response, clickdata={"nr": outside})

    def test_large_negative_number_kept_in_xpath(self) -> None:
        seed, size = 41, 26
        response = self.make_response(seed, size, 5)
        outside = -(len(response.text) + seed * size)
        with self.assertRaises(Exception):
            FormRequest.from_response(response, clickdata={"nr": outside})

    def test_hidden_number_then_repeated_name(self) -> None:
        seed, size = 43, 23
        response = self.make_response(seed, size, 3)
        outside = len(response.text) + size * seed
        criteria = VisibleCriteria(nr=outside, name=f"batch_{seed % 3}")
        with self.assertRaises(Exception):
            FormRequest.from_response(response, clickdata=criteria)

    def test_hidden_negative_number_then_absent_name(self) -> None:
        seed, size = 47, 28
        response = self.make_response(seed, size, 6)
        outside = -(len(response.text) * size + seed)
        criteria = VisibleCriteria(
            nr=outside,
            name=f"absent_{(seed + size) * 17}",
        )
        with self.assertRaises(Exception):
            FormRequest.from_response(response, clickdata=criteria)

    def test_hidden_number_then_unique_name_recovers(self) -> None:
        seed, size = 53, 20
        response = self.make_response(seed, size, 7)
        outside = len(response.text) * size - seed
        criteria = VisibleCriteria(nr=outside, name=f"solo_{seed}")
        request = FormRequest.from_response(response, clickdata=criteria)
        self.assertIn("submit", request.url)

    def test_non_numeric_number_selector(self) -> None:
        seed = 59
        token = f"slot_{(seed * seed) % 101}"
        with self.assertRaises(Exception):
            self.build(seed, 29, 4, {"nr": token})  # type: ignore[dict-item]

    def test_malformed_generated_attribute(self) -> None:
        seed = 61
        malformed = chr((seed * 2 + 68) % 128)
        with self.assertRaises(Exception):
            self.build(seed, 30, 5, {malformed: f"value_{seed}"})

    def test_malformed_generated_value(self) -> None:
        seed = 67
        malformed = chr((seed + 95) % 128)
        with self.assertRaises(Exception):
            self.build(seed, 32, 6, {"name": malformed})

    def test_hidden_number_then_malformed_attribute(self) -> None:
        seed, size = 71, 31
        response = self.make_response(seed, size, 8)
        outside = len(response.text) * (seed - size)
        malformed = chr((seed + size + 21) % 128)
        criteria = VisibleCriteria(
            nr=outside,
            **{malformed: f"probe_{(seed * size) % 251}"},
        )
        with self.assertRaises(Exception):
            FormRequest.from_response(response, clickdata=criteria)
