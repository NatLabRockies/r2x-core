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
    for original in inputs:
        docname = "references/" + original.stem
        data = json.loads((output / f"{docname}.fjson").read_text(encoding="utf-8"))
        title = re.sub(r"<[^>]+>", "", data["title"])
        body = re.sub(r"<h1\b[^>]*>.*?</h1>", "", data["body"], count=1, flags=re.S)
        body = re.sub(r"""href=(["'])(.*?)\1""", partial(rewrite_link, docname=docname), body)
        body = re.sub(
            r'<div class="highlight[^>]*>.*?</pre>',
            partial(link_code_names, targets=targets),
            body,
            flags=re.S,
        )
        body = "<details><summary>API contents</summary>" + data["toc"] + "</details>\n" + body
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
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    (destination / "release-notes.md").write_text(
        '---\ntitle: Release notes\neditUrl: "https://github.com/NatLabRockies/r2x-core/edit/main/CHANGELOG.md"\n---\n\n'
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
        target = html.escape(BASE + new + "/", quote=True)
        output = destination / (old + ".html")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
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
