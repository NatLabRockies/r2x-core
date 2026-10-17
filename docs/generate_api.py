"""Extract existing Sphinx API contracts into pages rendered by Starlight."""

from __future__ import annotations

import html
import json
import posixpath
import re
import subprocess
import sys
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BASE = "/r2x-core/"


def rewrite_link(match: re.Match[str], *, docname: str) -> str:
    """Resolve Sphinx's file-relative links into the public Astro route space."""
    quote, value = match.group(1), match.group(2)
    url = urlsplit(value)
    if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
        return match.group(0)
    # JSONHTMLBuilder emits directory-relative routes; explicit source/HTML
    # filenames instead resolve relative to the document's containing directory.
    parent = (
        posixpath.dirname(docname)
        if docname.endswith("/index") or url.path.endswith((".html", ".md"))
        else docname
    )
    target = posixpath.normpath(posixpath.join(parent, url.path))
    target = target.removesuffix(".html").removesuffix(".md")
    if target.endswith("/index"):
        target = target[:-6]
    destination = BASE + target.strip("/") + "/"
    if url.fragment:
        destination += "#" + url.fragment
    return f"href={quote}{destination}{quote}"


def api_targets(output: Path) -> dict[str, str]:
    """Index unambiguous public names using the API anchors Sphinx actually emitted."""
    candidates: dict[str, set[str]] = {}
    for page in sorted((output / "references").glob("*.fjson")):
        body = json.loads(page.read_text(encoding="utf-8"))["body"]
        for identifier in re.findall(r'<dt class="sig[^>]* id="([^"]+)"', body):
            if not identifier.startswith("r2x_core."):
                continue
            parts = identifier.split(".")
            target = BASE + "references/" + page.stem + "/#" + identifier
            for length in range(1, len(parts) + 1):
                candidates.setdefault(".".join(parts[-length:]), set()).add(target)
    return {name: next(iter(urls)) for name, urls in candidates.items() if len(urls) == 1}


def link_code_names(match: re.Match[str], *, targets: dict[str, str]) -> str:
    """Retain Pygments tokens while linking names with a unique documented target."""

    def link_name(name_match: re.Match[str]) -> str:
        markup = name_match.group(0)
        name = re.sub(r"<[^>]+>", "", markup)
        target = targets.get(name) if "." in name or name[:1].isupper() else None
        return f'<a href="{html.escape(target, quote=True)}">{markup}</a>' if target else markup

    token = r'<span class="n">[^<]+</span>'
    qualified = token + r'(?:<span class="o">[.]</span>' + token + r")*"
    return re.sub(qualified, link_name, match.group(0))


class TocItem(TypedDict):
    """One native Starlight navigation entry sourced from Sphinx's contents tree."""

    text: str
    slug: str
    depth: int
    children: list[TocItem]


class SphinxContents(HTMLParser):
    """Retain Sphinx's section/class/member hierarchy without interpreting signatures."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[TocItem] = []
        self.stack: list[list[TocItem]] = []
        self.active: TocItem | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "ul":
            children: list[TocItem] = []
            if self.stack and self.stack[-1]:
                self.stack[-1][-1]["children"] = children
            else:
                self.items = children
            self.stack.append(children)
        elif tag == "a" and self.stack:
            href = dict(attrs).get("href") or ""
            self.active = TocItem(
                text="", slug=href.removeprefix("#"), depth=min(len(self.stack), 6), children=[]
            )
            self.stack[-1].append(self.active)

    def handle_data(self, data: str) -> None:
        if self.active is not None:
            self.active["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.active is not None:
            self.active["text"] = " ".join(self.active["text"].split())
            self.active = None
        elif tag == "ul" and self.stack:
            self.stack.pop()

    def navigation(self) -> list[TocItem]:
        """Omit the duplicated page-title entry, preserving every anchored descendant."""
        return [child for item in self.items for child in ([item] if item["slug"] else item["children"])]


def main() -> None:
    """Build API data and materialize generated pages before Astro's content load."""
    source = ROOT / "docs/source"
    output = ROOT / "docs/build/api-json"
    subprocess.run(
        [sys.executable, "-m", "sphinx", "-E", "-b", "json", "-W", "-q", str(source), str(output)],
        cwd=ROOT,
        check=True,
    )
    targets = api_targets(output)
    destination = ROOT / "docs/src/content/docs"
    generated = destination / "references"
    generated.mkdir(parents=True, exist_ok=True)
    inputs = sorted((source / "references").glob("*.md"))
    navigation: dict[str, list[TocItem]] = {}
    for original in inputs:
        docname = "references/" + original.stem
        data = json.loads((output / f"{docname}.fjson").read_text(encoding="utf-8"))
        title = re.sub(r"<[^>]+>", "", data["title"])
        body = re.sub(r"<h1\b[^>]*>.*?</h1>", "", data["body"], count=1, flags=re.S)
        body = body.replace(
            'class="doctest highlight-default notranslate"',
            'class="doctest highlight-pycon notranslate" data-language="pycon"',
        )
        body = re.sub(r"""href=(["'])(.*?)\1""", partial(rewrite_link, docname=docname), body)
        body = re.sub(
            r'<div class="highlight[^>]*>.*?</pre>',
            partial(link_code_names, targets=targets),
            body,
            flags=re.S,
        )
        contents = SphinxContents()
        contents.feed(data["toc"])
        navigation[docname] = contents.navigation()
        page = (
            "---\ntitle: "
            + json.dumps(title)
            + ("\nsidebar:\n  hidden: true" if original.stem == "index" else "")
            + "\neditUrl: "
            + json.dumps("https://github.com/NatLabRockies/r2x-core/edit/main/docs/source/" + docname + ".md")
            + '\n---\n\n<div class="api-contracts">\n'
            + body
            + "\n</div>\n"
        )
        (generated / original.name).write_text(page, encoding="utf-8")
    navigation_file = ROOT / "docs/src/generated/api-toc.json"
    navigation_file.parent.mkdir(parents=True, exist_ok=True)
    navigation_file.write_text(json.dumps(navigation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    (destination / "release-notes.md").write_text(
        '---\ntitle: Changelog\neditUrl: "https://github.com/NatLabRockies/r2x-core/edit/main/CHANGELOG.md"\n---\n\n'
        + "This page is generated from the canonical repository changelog. "
        + "See [GitHub releases](https://github.com/NatLabRockies/r2x-core/releases) and "
        + "[PyPI](https://pypi.org/project/r2x-core/) for published distributions.\n\n"
        + "These guides describe main. For an installed release, select its tag in the "
        + "[source version browser](https://github.com/NatLabRockies/r2x-core/tags) "
        + "and open its documentation directory. Tagged source is available through GitHub; "
        + "this site does not advertise historical hosted builds.\n\n"
        + re.sub(r"^# .+\n", "", changelog, count=1),
        encoding="utf-8",
    )
    print(f"Generated {len(inputs)} API reference pages and canonical release notes.")


def write_redirects() -> None:
    """Preserve legacy .html paths without conflicting with Astro index files."""
    destination = ROOT / "docs/dist"
    content = ROOT / "docs/src/content/docs"
    redirects = {"CHANGELOG": "release-notes"}
    for page in content.rglob("*.md"):
        name = page.relative_to(content).with_suffix("").as_posix()
        if name == "index" or name.endswith("/index"):
            continue
        redirects[name] = name
    for old, new in redirects.items():
        redirect_url = BASE + new + "/"
        target = html.escape(redirect_url, quote=True)
        output = destination / (old + ".html")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<script>location.replace({json.dumps(redirect_url)} + location.search + location.hash);</script>"
            f'<meta http-equiv="refresh" content="0;url={target}">'
            f'<link rel="canonical" href="{target}"><title>Page moved</title></head>'
            f'<body><a href="{target}">Continue to documentation</a></body></html>\n',
            encoding="utf-8",
        )
    print(f"Preserved {len(redirects)} legacy HTML paths.")


if __name__ == "__main__":
    if "--redirects" in sys.argv:
        write_redirects()
    else:
        main()
