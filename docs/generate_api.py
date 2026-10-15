"""Extract existing Sphinx API contracts into pages rendered by Starlight."""

from __future__ import annotations

import html
import json
import posixpath
import re
import subprocess
import sys
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BASE = "/r2x-core/"


def rewrite_link(match: re.Match[str], *, docname: str) -> str:
    """Resolve Sphinx's file-relative links into the public Astro route space."""
    quote, value = match.group(1), match.group(2)
    url = urlsplit(value)
    if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
        return match.group(0)
    parent = posixpath.dirname(docname) if docname.endswith("/index") or url.path.endswith(".md") else docname
    target = posixpath.normpath(posixpath.join(parent, url.path))
    target = target.removesuffix(".html").removesuffix(".md")
    if target.endswith("/index"):
        target = target[:-6]
    destination = BASE + target.strip("/") + "/"
    if url.fragment:
        destination += "#" + url.fragment
    return f"href={quote}{destination}{quote}"


def main() -> None:
    """Build API data and materialize generated pages before Astro's content load."""
    source = ROOT / "docs/source"
    output = ROOT / "docs/build/api-json"
    subprocess.run(
        [sys.executable, "-m", "sphinx", "-E", "-b", "json", "-W", "-q", str(source), str(output)],
        cwd=ROOT,
        check=True,
    )
    destination = ROOT / "docs/src/content/docs"
    generated = destination / "references"
    generated.mkdir(parents=True, exist_ok=True)
    inputs = sorted((source / "references").glob("*.md"))
    for original in inputs:
        docname = "references/" + original.stem
        data = json.loads((output / f"{docname}.fjson").read_text())
        title = re.sub(r"<[^>]+>", "", data["title"])
        body = re.sub(r"<h1\b[^>]*>.*?</h1>", "", data["body"], count=1, flags=re.S)
        body = re.sub(r"""href=(["'])(.*?)\1""", partial(rewrite_link, docname=docname), body)
        body = "<details><summary>API contents</summary>" + data["toc"] + "</details>\n" + body
        page = (
            "---\ntitle: "
            + json.dumps(title)
            + "\neditUrl: "
            + json.dumps("https://github.com/NatLabRockies/r2x-core/edit/main/docs/source/" + docname + ".md")
            + '\n---\n\n<div class="api-contracts">\n'
            + body
            + "\n</div>\n"
        )
        (generated / original.name).write_text(page)
    changelog = (ROOT / "CHANGELOG.md").read_text()
    (destination / "release-notes.md").write_text(
        '---\ntitle: Release notes\neditUrl: "https://github.com/NatLabRockies/r2x-core/edit/main/CHANGELOG.md"\n---\n\n'
        + re.sub(r"^# .+\n", "", changelog, count=1)
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
        target = html.escape(BASE + new + "/", quote=True)
        output = destination / (old + ".html")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0;url={target}">'
            f'<link rel="canonical" href="{target}"><title>Page moved</title></head>'
            f'<body><a href="{target}">Continue to documentation</a></body></html>\n'
        )
    print(f"Preserved {len(redirects)} legacy HTML paths.")


if __name__ == "__main__":
    if "--redirects" in sys.argv:
        write_redirects()
    else:
        main()
