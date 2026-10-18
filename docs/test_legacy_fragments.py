"""Verify historical bookmarks reach an anchor in the built replacement page."""

import re
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
    def test_property_members_have_anchors_and_source_links(self) -> None:
        page = Path(__file__).parent / "dist/references/api/index.html"
        markup = page.read_text(encoding="utf-8")
        for member in ("Plugin.config", "Plugin.system"):
            with self.subTest(member=member):
                signature = re.search(r'id="r2x_core\.' + re.escape(member) + r'".*?</dt>', markup, re.S)
                self.assertIsNotNone(signature)
                self.assertRegex(
                    signature[0],
                    r'href="https://github.com/NatLabRockies/r2x-core/blob/[0-9a-f]{40}/src/r2x_core/plugin_base\.py#L\d+-L\d+"',
                )
                self.assertIn(f'href="#r2x_core.{member}"', markup)

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
                "installation",
            ),
            "how-tos/build-parsers": ("working-with-systems", "see-also", "parser-basics"),
            "how-tos/build-exporters": ("exporting-systems", "see-also", "exporter-basics"),
            "tutorials/getting-started": (
                "prerequisites",
                "working-with-systems",
                "working-with-data-files",
                "plugin-configuration",
                "creating-a-plugin",
                "working-with-rules",
                "version-management",
                "next-steps",
                "getting-started-with-r2x-core",
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
                "plugin-system",
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
                "upgrade-system",
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
                "versioning-and-upgrades-design-philosophy",
            ),
            "contributing": ("contributing",),
            "explanations/data-management": ("data-management-design-philosophy",),
            "explanations/h5-readers": ("hdf5-reader-system",),
            "explanations": ("explanations",),
            "explanations/plugin-system": ("plugin-system-architecture", "plugin-configuration"),
            "explanations/rules-system": ("rule-system-architecture",),
            "explanations/unit-system": ("unit-system-design-and-architecture",),
            "how-tos/apply-rules": ("apply-translation-rules",),
            "how-tos/attach-timeseries": ("attaching-time-series",),
            "how-tos/configure-data-files": ("working-with-datafiles",),
            "how-tos/configure-data-settings": ("configuring-data-settings",),
            "how-tos/convert-units": ("work-with-units",),
            "how-tos/create-function-plugins": ("create-function-based-transform-plugins",),
            "how-tos/create-rule-filters": ("rule-filters",),
            "how-tos/create-rules": ("create-translation-rules",),
            "how-tos/define-rule-mappings": ("working-with-rules",),
            "how-tos": ("how-to-guides",),
            "how-tos/manage-datastores": ("managing-datastores",),
            "how-tos/manage-systems": ("managing-systems",),
            "how-tos/manage-versions": ("managing-versions",),
            "how-tos/process-file-data": ("processing-file-data",),
            "how-tos/read-hdf5-files": ("reading-hdf5-data-files",),
            "how-tos/register-plugins": ("create-and-register-plugins",),
            "how-tos/run-plugins": ("using-plugins",),
            "how-tos/structure-plugin-directories": ("plugin-directory-structure",),
            "how-tos/upgrade-data-files": ("upgrade-data-between-versions",),
            "how-tos/upgrade-systems": ("upgrade-systems-between-versions",),
            "": (
                "r2x-core-documentation",
                "about-r2x-core",
                "key-features",
                "quick-start",
                "plugin-discovery",
                "indices-and-tables",
            ),
            "references/processors": ("multi-row-csvtsv-headers",),
            "tutorials": ("tutorials",),
            "tutorials/plugin-context": ("plugin-context",),
            "tutorials/plugin-discovery": (
                "plugin-discovery",
                "4-generic-configuration-types",
                "integration-with-cli",
            ),
            "tutorials/plugin-system": ("plugin-system",),
            "tutorials/plugin-utilities": (
                "plugin-developer-utilities",
                "components_to_records",
                "export_components_to_csv",
                "getter",
            ),
            "tutorials/working-with-units": ("create-power-system-components-with-units",),
        }
        for route, fragments in bookmarks.items():
            with self.subTest(route=route):
                legacy = root / f"{route}.html"
                if route not in ("", "explanations", "how-tos", "tutorials"):
                    redirect = Page()
                    redirect.feed(legacy.read_text(encoding="utf-8"))
                    self.assertEqual(redirect.redirect, f"/r2x-core/{route}/")
                destination = Page()
                destination.feed((root / route / "index.html").read_text(encoding="utf-8"))
                for fragment in fragments:
                    self.assertIn(fragment, destination.ids)


if __name__ == "__main__":
    unittest.main()
