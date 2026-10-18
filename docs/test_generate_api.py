"""Regression checks for the Sphinx-to-Starlight link boundary."""

import re
import unittest
from functools import partial

from generate_api import SphinxContents, link_code_names, rewrite_link


class ApiLinksTest(unittest.TestCase):
    def test_contents_preserve_section_class_and_member_anchors(self) -> None:
        parser = SphinxContents()
        parser.feed(
            '<ul><li><a href="#">API</a><ul><li><a href="#system">System</a><ul>'
            '<li><a href="#r2x_core.System"><code>System</code></a><ul><li>'
            '<a href="#r2x_core.System.to_json">System.to_json()</a>'
            "</li></ul></li></ul></li></ul></li></ul>"
        )
        section = parser.navigation()[0]
        self.assertEqual(section["slug"], "system")
        component = section["children"][0]
        self.assertEqual(component["slug"], "r2x_core.System")
        self.assertEqual(component["children"][0]["slug"], "r2x_core.System.to_json")
        self.assertEqual(component["children"][0]["text"], "System.to_json()")

    def test_sphinx_and_explicit_file_routes(self) -> None:
        for source in ("../api/#r2x_core.System", "api.html#r2x_core.System", "api.md#r2x_core.System"):
            with self.subTest(source=source):
                result = re.sub(
                    r"href=([\"\'])(.*?)\1",
                    partial(rewrite_link, docname="references/system"),
                    f'href="{source}"',
                )
                self.assertEqual(result, 'href="/r2x-core/references/api/#r2x_core.System"')

    def test_index_route(self) -> None:
        self.assertEqual(
            re.sub(
                r'href=(["\'])(.*?)\1',
                partial(rewrite_link, docname="references/index"),
                'href="api/#r2x_core.System"',
            ),
            'href="/r2x-core/references/api/#r2x_core.System"',
        )

    def test_external_and_fragment_links_unchanged(self) -> None:
        for source in ("#method", "https://example.org/api.html#method", "/r2x-core/install/"):
            markup = f'href="{source}"'
            self.assertEqual(
                re.sub(r"href=([\"\'])(.*?)\1", partial(rewrite_link, docname="references/api"), markup),
                markup,
            )

    def test_code_links_keep_tokens_and_qualified_names(self) -> None:
        markup = '<div class="highlight"><pre><span class="n">System</span><span class="o">.</span><span class="n">to_json</span></pre>'
        target = "/r2x-core/references/api/#r2x_core.System.to_json"
        linked = re.sub(r".+", partial(link_code_names, targets={"System.to_json": target}), markup)
        self.assertIn(f'<a href="{target}"><span class="n">System</span>', linked)
        self.assertEqual(re.sub(r"<[^>]+>", "", linked), "System.to_json")
        self.assertEqual(re.sub(r".+", partial(link_code_names, targets={}), markup), markup)


if __name__ == "__main__":
    unittest.main()
