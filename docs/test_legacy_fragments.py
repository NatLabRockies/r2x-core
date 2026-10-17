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
            "references/plugins": ("function-based-transform-plugins", "entry-point-discovery"),
            "references/upgrader": ("define-an-upgrade-step", "system-upgrade", "apply-upgrades"),
            "explanations/versioning": ("version-comparison-strategies",),
            "tutorials/getting-started": ("working-with-systems",),
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
