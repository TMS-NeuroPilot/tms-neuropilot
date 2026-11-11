"""Contract tests for the documentation site.

These make documentation rot a test failure instead of a slow surprise:

* the site builds and every internal link and anchor resolves,
* every page is in the nav and every nav entry exists,
* the search index covers every page,
* every environment/lab key the code reads is documented,
* every relay topic string is in the protocol page,
* every fit function is in the analysis page,
* no personal absolute paths or example binaries leak into the output.

The builder is dependency-free (standard library only), so this file needs no
display and no optional packages.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "docs" / "site"
SRC = REPO / "src" / "neuropilot"


def _load_builder():
    spec = importlib.util.spec_from_file_location("np_docs_build", SITE / "build.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("np_docs_build", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def builder():
    return _load_builder()


@pytest.fixture(scope="module")
def built(builder, tmp_path_factory):
    out = tmp_path_factory.mktemp("docs") / "public"
    problems = builder.build(out, strict=False)
    return out, problems


def test_build_has_no_broken_links(built):
    _, problems = built
    assert not problems, "\n".join(problems)


def test_every_page_is_built_and_in_the_nav(built, builder):
    out, _ = built
    sections = builder.read_nav()
    pages = [page for section in sections for page in section["pages"]]
    for page in pages:
        assert (out / (page["path"][:-3] + ".html")).is_file(), page["path"]
    on_disk = {p.relative_to(SITE / "pages").as_posix()
               for p in (SITE / "pages").rglob("*.md")}
    assert on_disk == {page["path"] for page in pages}


def test_search_index_covers_every_page(built, builder):
    out, _ = built
    index = json.loads((out / "search-index.json").read_text())
    pages = [page for section in builder.read_nav()
             for page in section["pages"]]
    assert len(index) == len(pages)
    urls = {item["url"] for item in index}
    for page in pages:
        assert page["path"][:-3] + ".html" in urls
    for item in index:
        assert (out / item["url"]).is_file()
        assert item["title"] and item["section"]


def test_support_files_exist(built):
    out, _ = built
    for name in ("search.html", "404.html", "robots.txt", "sitemap.xml",
                 "assets/css/site.css", "assets/js/site.js",
                 "assets/img/favicon.svg"):
        assert (out / name).is_file(), name


def test_every_environment_key_is_documented(builder):
    text = "\n".join(p.read_text() for p in (SITE / "pages").rglob("*.md"))
    keys = set()
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8", errors="replace")
        keys |= set(re.findall(r'(?:os\.getenv|os\.environ\.get|_env)\(\s*["\']([A-Z][A-Z0-9_]+)', source))
    # System variables used by Qt/tests, not project settings.
    keys -= {"DISPLAY", "WAYLAND_DISPLAY", "PYTHONPATH"}
    missing = sorted(key for key in keys if key not in text)
    assert not missing, f"undocumented environment keys: {missing}"


def test_every_lab_profile_key_is_documented(builder):
    from neuropilot.lab_profile import LAB_KEYS
    lab_page = (SITE / "pages" / "config" / "lab.md").read_text()
    missing = [key for key in LAB_KEYS if key not in lab_page]
    assert not missing, f"lab profile keys missing from config/lab.md: {missing}"


def test_every_relay_topic_is_documented(builder):
    relay_page = (SITE / "pages" / "reference" / "relay.md").read_text()
    topics = set()
    # Declared topic constants in the simulators …
    for name in ("sim_robot/config.py", "sim_nav/config.py"):
        source = (SRC / name).read_text(encoding="utf-8")
        topics |= set(re.findall(r'TOPIC_\w+\s*=\s*["\']([^"\']+)["\']', source))
    # … and the literal topics the controller sends or handles.
    prefix = re.compile(r'^(External Controller|From Neuronavigation|Neuronavigation to Robot|'
                        r'Robot to|Pipeline to|GUI to|SIM - )[^"\']*: [^"\']+$')
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8", errors="replace")
        for candidate in re.findall(r'["\']([^"\'\n]{4,90})["\']', source):
            if prefix.match(candidate):
                topics.add(candidate)
        topics |= set(re.findall(r'["\'](STOP|Press robot button)["\']', source))
    assert topics, "no topics found in the source"
    missing = sorted(topic for topic in topics if topic not in relay_page)
    assert not missing, f"relay topics missing from reference/relay.md: {missing}"


def test_every_fit_function_is_documented(builder):
    from neuropilot.controller.fit_functions import fit_names
    page = (SITE / "pages" / "results" / "analysis.md").read_text()
    missing = [name for name in fit_names() if name not in page]
    assert not missing, f"fit functions missing from results/analysis.md: {missing}"


def test_every_gui_tab_is_documented(builder):
    nav = builder.read_nav()
    titles = {page["title"] for section in nav for page in section["pages"]}
    for tab in ("Project", "Connections", "Control", "MEP results",
                "Cortical results", "Config"):
        assert any(tab.lower() in title.lower() for title in titles), tab


def test_no_personal_paths_or_binaries_leak_into_the_site(built):
    out, _ = built
    for path in out.rglob("*.html"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "/home/" not in text, path
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in (".nii", ".msh", ".hdf5"):
            pytest.fail(f"binary example data in the site: {path}")
