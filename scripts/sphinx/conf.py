"""Internal API extraction only. The public site is Astro/Starlight."""

project = "r2x-core"
extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.linkcode",
    "sphinxcontrib.autodoc_pydantic",
]
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "infrasys": ("https://natlabrockies.github.io/infrasys/", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
myst_all_links_external = True
autosummary_generate = True
highlight_language = "python"
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_typehints_format = "short"
autoclass_content = "both"
exclude_patterns = ["_static"]


# Pin source links to the checkout used for this documentation build.
def linkcode_resolve(domain, info):
    import inspect
    import subprocess
    from importlib import import_module
    from pathlib import Path

    if domain != "py" or not info.get("module"):
        return None
    try:
        obj = import_module(info["module"])
        for part in info["fullname"].split("."):
            obj = getattr(obj, part)
        obj = inspect.unwrap(obj)
        source = Path(inspect.getsourcefile(obj)).resolve()
        root = Path(__file__).resolve().parents[2]
        source.relative_to(root / "src" / "r2x_core")
        relative = source.relative_to(root).as_posix()
        lines, start = inspect.getsourcelines(obj)
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except (AttributeError, ImportError, OSError, TypeError, ValueError, subprocess.CalledProcessError):
        return None
    return f"https://github.com/NatLabRockies/r2x-core/blob/{revision}/{relative}#L{start}-L{start + len(lines) - 1}"


def normalize_package_label(_app, _what, name, _obj, _options, lines):
    """Use the package name in System prose without changing runtime source or examples."""
    if name not in {"r2x_core.System", "r2x_core.system.System"}:
        return
    for index, line in enumerate(lines):
        if line in {"R2X Core System class extending infrasys.System.", "Initialize R2X Core System."}:
            lines[index] = line.replace("R2X Core", "r2x-core")


def setup(app):
    app.connect("autodoc-process-docstring", normalize_package_label)
