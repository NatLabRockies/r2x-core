"""Verify historical bookmarks reach an anchor in the built replacement page."""

import unittest
from html.parser import HTMLParser
from pathlib import Path


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.redirect: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if anchor := values.get("id"):
            self.ids.add(anchor)
        if tag == "meta" and values.get("http-equiv") == "refresh":
            self.redirect = (values.get("content") or "").split("url=", 1)[-1]


class LegacyFragmentsTest(unittest.TestCase):
    def test_bookmarks_reach_final_anchors(self) -> None:
        root = Path(__file__).parent / "dist"
        bookmarks = {
            "install": (
                "python-version-support",
                "installation-options",
                "installation-with-pip",
                "installation-with-uv",
                "upgrading-options",
                "upgrading-with-uv",
                "upgrading-with-pip",
                "verify-installation",
                "next-steps",
            ),
            "how-tos/build-parsers": ("working-with-systems", "see-also"),
            "how-tos/build-exporters": ("exporting-systems", "see-also"),
            "tutorials/getting-started": (
                "prerequisites",
                "working-with-systems",
                "working-with-data-files",
                "plugin-configuration",
                "creating-a-plugin",
                "working-with-rules",
                "version-management",
                "next-steps",
            ),
            "references/plugins": (
                "overview",
                "quick-reference",
                "usage-examples",
                "creating-a-pluginconfig",
                "entry-point-discovery",
                "manifest-export-utility",
                "configuration-directory-structure",
                "pluginconfig-features",
                "function-based-transform-plugins",
                "see-also",
            ),
            "references/upgrader": (
                "quick-reference",
                "overview",
                "upgrade-types",
                "usage-examples",
                "define-an-upgrade-step",
                "system-upgrade",
                "apply-upgrades",
                "see-also",
            ),
            "explanations/versioning": (
                "the-problem-we-solve",
                "staged-upgrades-vs-monolithic-upgrades",
                "monolithic-approach-fragile",
                "staged-approach-maintainable",
                "version-comparison-strategies",
                "semantic-versioning-most-common",
                "git-based-versioning",
                "custom-strategies",
                "version-ranges-and-upgrade-applicability",
                "file-vs-system-upgrades",
                "file-upgrades-most-common",
                "system-upgrades-less-common",
                "priority-and-execution-order",
                "design-trade-offs",
                "why-not-just-update-all-data-upfront",
                "why-priority-instead-of-dependency-graphs",
                "real-world-example",
                "see-also",
            ),
        }
        for route, fragments in bookmarks.items():
            with self.subTest(route=route):
                redirect = Page()
                redirect.feed((root / f"{route}.html").read_text(encoding="utf-8"))
                self.assertEqual(redirect.redirect, f"/r2x-core/{route}/")
                destination = Page()
                destination.feed((root / route / "index.html").read_text(encoding="utf-8"))
                for fragment in fragments:
                    self.assertIn(fragment, destination.ids)


if __name__ == "__main__":
    unittest.main()
