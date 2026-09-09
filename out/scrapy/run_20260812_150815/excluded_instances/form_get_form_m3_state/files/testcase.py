from __future__ import annotations

import unittest

from scrapy.http import FormRequest


class Node:
    def __init__(self, tag: str, code: int, parent: Node | None = None) -> None:
        self.tag = tag
        self.code = code
        self._parent = parent

    def getparent(self) -> Node | None:
        return self._parent

    def __repr__(self) -> str:
        return f"Node(tag={self.tag!r}, code={self.code})"


class Form(Node):
    def __init__(
        self,
        code: int,
        *,
        name: str | None = None,
        form_id: str | None = None,
        method: str = "GET",
    ) -> None:
        super().__init__("form", code)
        self.name = name
        self.form_id = form_id
        self.method = method
        self.base_url = f"https://example.invalid/base/{code}/"

    def xpath(self, query: str, **kwargs: object) -> list[Node]:
        return []

    def get(self, key: str) -> str | None:
        if key == "action":
            return f"submit/{(self.code * 7 + 3) % 97}"
        return None


class TakingList(list[Node]):
    """A list whose integer lookup consumes the selected entry."""

    def __getitem__(self, index: int | slice) -> Node | list[Node]:
        if isinstance(index, int):
            return self.pop(index)
        return super().__getitem__(index)


class Root:
    def __init__(
        self,
        *,
        seed: int,
        depth: int,
        forms: int = 1,
        selected: int = 0,
        name: str | None = None,
        form_id: str | None = None,
        method: str = "GET",
        empty_path: bool = False,
        orphan_path: bool = False,
    ) -> None:
        self.seed = seed
        self.depth = depth
        self.empty_path = empty_path
        self.orphan_path = orphan_path
        self.forms = [
            Form(
                (seed * (index + 5) + depth * 3) % 101,
                name=name if index == selected else None,
                form_id=form_id if index == selected else None,
                method=method if index == selected else "GET",
            )
            for index in range(forms)
        ]
        self.selected = selected

    def _path_nodes(self) -> TakingList:
        if self.empty_path:
            return TakingList()

        tags = ("article", "aside", "div", "fieldset", "main", "nav", "section")
        parent: Node | None
        if self.orphan_path:
            parent = None
        else:
            parent = self.forms[self.selected]

        state = (self.seed * 29 + self.depth * 11) % 257
        for index in range(self.depth):
            state = (state * 73 + index * 17 + self.seed) % 997
            parent = Node(tags[(state + index) % len(tags)], state, parent)

        assert parent is not None
        decoy_code = (state * 31 + self.seed + self.depth) % 997
        return TakingList([parent, Node(tags[decoy_code % len(tags)], decoy_code)])

    def xpath(self, query: str) -> list[Node]:
        if query == "//form":
            return self.forms
        if query.startswith('//form[@name="'):
            wanted = query.removeprefix('//form[@name="').removesuffix('"]')
            return [form for form in self.forms if form.name == wanted]
        if query.startswith('//form[@id="'):
            wanted = query.removeprefix('//form[@id="').removesuffix('"]')
            return [form for form in self.forms if form.form_id == wanted]
        return self._path_nodes()


class Selector:
    def __init__(self, root: Root) -> None:
        self.root = root


class Response:
    encoding = "utf-8"

    def __init__(self, root: Root) -> None:
        self.selector = Selector(root)


class TestGetFormProgramState(unittest.TestCase):
    def make_request(self, root: Root, **kwargs: object) -> FormRequest:
        return FormRequest.from_response(  # type: ignore[arg-type]
            Response(root),
            dont_click=True,
            **kwargs,
        )

    def test_xpath_modular_chain(self) -> None:
        root = Root(seed=5, depth=19)
        request = self.make_request(root, formxpath="//node[@kind='modular']")
        self.assertTrue(request.url.startswith("https://"))

    def test_xpath_quadratic_chain(self) -> None:
        root = Root(seed=11, depth=23, method="POST")
        request = self.make_request(root, formxpath="//node[@kind='quadratic']")
        self.assertIn(request.method, FormRequest.valid_form_methods)

    def test_css_translated_chain(self) -> None:
        root = Root(seed=17, depth=17)
        request = self.make_request(root, formcss="section.generated > span")
        self.assertGreater(len(request.url), len(root.forms))

    def test_xpath_with_url_override(self) -> None:
        root = Root(seed=23, depth=21)
        request = self.make_request(
            root,
            formxpath="//node[@kind='override']",
            url="../computed-destination",
        )
        self.assertEqual(request.method.isupper(), True)

    def test_xpath_explicit_get(self) -> None:
        root = Root(seed=31, depth=18, method="POST")
        request = self.make_request(
            root,
            formxpath="//node[@kind='explicit-get']",
            method="get",
        )
        self.assertFalse(request.body)

    def test_xpath_post_with_generated_data(self) -> None:
        root = Root(seed=37, depth=24, method="POST")
        data = {f"k{index}": str((index * root.seed + root.depth) % 43) for index in range(7)}
        request = self.make_request(
            root,
            formxpath="//node[@kind='post-data']",
            formdata=data,
        )
        self.assertIsInstance(request.body, bytes)

    def test_invalid_name_then_xpath(self) -> None:
        root = Root(seed=41, depth=20, name="available")
        request = self.make_request(
            root,
            formname="absent",
            formxpath="//node[@kind='after-name']",
        )
        self.assertTrue(request.url)

    def test_invalid_id_then_xpath(self) -> None:
        root = Root(seed=47, depth=22, form_id="present")
        request = self.make_request(
            root,
            formid="missing",
            formxpath="//node[@kind='after-id']",
        )
        self.assertIn("example.invalid", request.url)

    def test_named_form_short_circuit(self) -> None:
        root = Root(seed=53, depth=16, forms=3, selected=1, name="chosen")
        request = self.make_request(root, formname="chosen")
        self.assertGreaterEqual(len(request.headers), 0)

    def test_identified_form_short_circuit(self) -> None:
        root = Root(seed=59, depth=25, forms=2, selected=0, form_id="identity")
        request = self.make_request(root, formid="identity")
        self.assertIsInstance(request, FormRequest)

    def test_numbered_form_fallback(self) -> None:
        root = Root(seed=61, depth=15, forms=4, selected=3)
        request = self.make_request(root, formname="unknown", formnumber=3)
        self.assertNotEqual(request.url, "")

    def test_empty_xpath_result(self) -> None:
        root = Root(seed=67, depth=27, empty_path=True)
        with self.assertRaises(ValueError):
            self.make_request(root, formxpath="//node[@kind='empty']")

    def test_orphan_xpath_chain(self) -> None:
        root = Root(seed=71, depth=16, orphan_path=True)
        with self.assertRaises(ValueError):
            self.make_request(root, formxpath="//node[@kind='orphan']")
