#!/usr/bin/env python3
"""Build the NeuroPilot documentation site (GitLab Pages).

Deliberately dependency-free: the CI runner only needs the Python that runs the
tests, and the site must build on a machine with no network.  Markdown is a
small, well-defined subset (see ``docs/site/README.md``) rendered by this file;
the result is a static site in ``public/``.

    python docs/site/build.py                 # build into public/
    python docs/site/build.py --out /tmp/x    # somewhere else
    python docs/site/build.py --serve 8000    # build, then preview locally
    python docs/site/build.py --check         # only verify links (CI)

Structure:
    docs/site/nav.toml          sections and pages (order, titles, blurbs)
    docs/site/pages/*.md        the content
    docs/site/assets/           css, js, diagrams, screenshots
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = ROOT / "pages"
ASSETS = ROOT / "assets"
SITE_NAME = "NeuroPilot"
SITE_TAGLINE = "Guided online TMS mapping with online field optimisation"
REPO_URL = "https://gitlab.gwdg.de/tms-localization/papers/neuropilot"
EDIT_URL = REPO_URL + "/-/edit/main/docs/site/pages/"
SITE_URL = "https://neuropilot-94ad2d.pages.gwdg.de/"

_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")


def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", text).strip("-") or "section"


def _resolve_link(href: str, ctx: dict) -> tuple[str, bool]:
    """Rewrite repository-relative links; return ``(href, is_external)``."""
    if re.match(r"^(https?:|mailto:|#|data:)", href):
        return href, href.startswith("http")
    if href.startswith("assets/"):
        suffix = f'?v={ctx["version"]}' if ctx.get("version") else ""
        return ctx["root"] + href + suffix, False
    if href.startswith("/"):
        return href, False
    target = (PAGES / href).resolve()
    if target.is_file() and href.endswith(".md"):
        # Navigate relative to the page that contains the link, not to the
        # site root: pages live at different depths.
        rel = os.path.relpath(target, ctx["page"].parent).replace(os.sep, "/")
        return rel[:-3] + ".html", False
    if (ctx["page"].parent / href).resolve().is_file():
        rel = os.path.relpath((ctx["page"].parent / href).resolve(), ROOT)
        return f"{REPO_URL}/-/blob/main/{rel}".replace(os.sep, "/"), True
    return href, False


def inline(text: str, ctx: dict, with_links: bool = True) -> str:
    """Inline markdown -> HTML.

    Code spans, images and links are rendered first and stashed, so the
    remaining text can be escaped without touching the generated markup.
    """
    stash: list[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    text = _INLINE_CODE.sub(
        lambda m: keep(f"<code>{html.escape(m.group(1))}</code>"), text)

    if with_links:
        def image(match: re.Match) -> str:
            alt, src, title = match.group(1), match.group(2), match.group(3)
            src, _ = _resolve_link(src, ctx)
            title_attr = f' title="{html.escape(title)}"' if title else ""
            return keep(
                f'<img src="{html.escape(src, quote=True)}"'
                f' alt="{html.escape(alt, quote=True)}"{title_attr} loading="lazy">')

        text = _IMAGE.sub(image, text)

        def link(match: re.Match) -> str:
            label, href, title = match.group(1), match.group(2), match.group(3)
            href, external = _resolve_link(href, ctx)
            title_attr = f' title="{html.escape(title, quote=True)}"' if title else ""
            extra = (' class="external" target="_blank" rel="noopener"'
                     if external else "")
            label_html = html.escape(label)
            label_html = _BOLD.sub(r"<strong>\1</strong>", label_html)
            return keep(f'<a href="{html.escape(href, quote=True)}"{title_attr}'
                        f"{extra}>{label_html}</a>")

        text = _LINK.sub(link, text)

    text = html.escape(text, quote=False)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
    return text


def _table(lines: list[str], ctx: dict) -> str:
    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    header = cells(lines[0])
    out = ['<div class="table-wrap"><table>', "<thead><tr>"]
    out += [f"<th>{inline(cell, ctx)}</th>" for cell in header]
    out += ["</tr></thead><tbody>"]
    for line in lines[2:]:
        out.append("<tr>" + "".join(f"<td>{inline(cell, ctx)}</td>"
                                    for cell in cells(line)) + "</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def _admonition(kind: str, title: str | None, body: list[str], ctx: dict) -> str:
    icon = {"note": "ℹ", "tip": "💡", "warning": "⚠", "danger": "⛔",
            "example": "▸", "quote": "❝"}.get(kind, "ℹ")
    label = title or kind.capitalize()
    return (f'<div class="admonition {kind}">'
            f'<p class="admonition-title"><span class="icon">{icon}</span>'
            f'{inline(label, ctx)}</p>{render_blocks(body, ctx)}</div>')


def _tabs(groups: list[tuple[str, list[str]]], ctx: dict) -> str:
    buttons, panes = [], []
    for index, (title, body) in enumerate(groups):
        active = " active" if index == 0 else ""
        buttons.append(
            f'<button type="button" class="tab{active}" role="tab" '
            f'data-tab="{index}" aria-selected="{"true" if index == 0 else "false"}">'
            f"{inline(title, ctx)}</button>")
        panes.append(
            f'<div class="pane{active}" role="tabpanel" data-pane="{index}">'
            f"{render_blocks(body, ctx)}</div>")
    return ('<div class="tabs"><div class="tablist" role="tablist">'
            + "".join(buttons) + '</div><div class="panes">' + "".join(panes)
            + "</div></div>")


def _code_block(lang: str, code: str, ctx: dict) -> str:
    label = lang or "text"
    return (f'<div class="code"><div class="code-head"><span>{html.escape(label)}</span>'
            "<button class=\"copy\" type=\"button\" aria-label=\"Copy code\">Copy</button>"
            f"</div><pre><code class=\"language-{html.escape(lang or 'text')}\">"
            f"{html.escape(code)}</code></pre></div>")


def _list(lines: list[str], ctx: dict) -> str:
    ordered = bool(re.match(r"^\s*\d+\.\s", lines[0]))
    pattern = re.compile(r"^(\s*)(\d+\.|[-*])\s+(.*)$")
    items: list[list[str]] = []
    for line in lines:
        match = pattern.match(line)
        if match and not match.group(1):
            items.append([match.group(3)])
        elif items:
            items[-1].append(line)
    out = ["<ol>" if ordered else "<ul>"]
    for item in items:
        first, rest = item[0], item[1:]
        task = re.match(r"\[([ xX])\]\s*(.*)", first)
        if task:
            checked = " checked" if task.group(1).lower() == "x" else ""
            out.append(f'<li class="task"><input type="checkbox" disabled{checked}> '
                       f"{inline(task.group(2), ctx)}</li>")
            continue
        body = inline(first, ctx)
        continuation = [line.strip() for line in rest if line.strip()]
        if continuation:
            if all(re.match(r"^[-*]\s+|^\d+\.\s+", line) for line in continuation):
                out.append(f"<li>{body}{_list(continuation, ctx)}</li>")
            else:
                out.append(f"<li>{body} {inline(' '.join(continuation), ctx)}</li>")
        else:
            out.append(f"<li>{body}</li>")
    out.append("</ol>" if ordered else "</ul>")
    return "\n".join(out)


_BLOCK_START = re.compile(r"^(#{1,4}\s|```|!!!|\||>|\s*[-*]\s|\s*\d+\.\s|---$)")


def render_blocks(lines: list[str], ctx: dict) -> str:
    """Render a list of block-level markdown lines."""
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            index += 1
            out.append(_code_block(lang, "\n".join(code), ctx))
            continue

        if re.match(r'^===\s+"', stripped):
            groups = []
            index += 1
            while index < len(lines):
                header = re.match(r'^===\s+"([^"]*)"\s*$', lines[index].strip())
                if not header:
                    break
                title = header.group(1)
                index += 1
                body = []
                while index < len(lines):
                    current = lines[index]
                    if current.strip() and not current.startswith("    "):
                        break
                    body.append(current[4:] if current.startswith("    ") else "")
                    index += 1
                groups.append((title, body))
            out.append(_tabs(groups, ctx))
            continue

        if stripped.startswith("!!!"):
            match = re.match(r'!!!\s*(\w+)(?:\s+"([^"]*)")?\s*$', stripped)
            kind = match.group(1) if match else "note"
            title = match.group(2) if match else None
            body = []
            index += 1
            while index < len(lines):
                current = lines[index]
                if current.strip() and not current.startswith("    "):
                    break
                body.append(current[4:] if current.startswith("    ") else "")
                index += 1
            out.append(_admonition(kind, title, body, ctx))
            continue

        if stripped.startswith("|") and index + 1 < len(lines) \
                and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[index + 1]):
            table = [line]
            index += 1
            while index < len(lines) and lines[index].strip().startswith("|"):
                table.append(lines[index])
                index += 1
            out.append(_table(table, ctx))
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2)
            anchor = slug(text)
            ctx["headings"].append((level, text, anchor))
            out.append(f'<h{level} id="{anchor}">{inline(text, ctx)}'
                       f'<a class="anchor" href="#{anchor}" aria-hidden="true">#</a>'
                       f"</h{level}>")
            index += 1
            continue

        if re.match(r"^\s*[-*]\s+\S", line) or re.match(r"^\s*\d+\.\s+\S", line):
            items = []
            while index < len(lines) and (
                    re.match(r"^\s*[-*]\s+\S", lines[index])
                    or re.match(r"^\s*\d+\.\s+\S", lines[index])
                    or (lines[index].startswith("  ") and lines[index].strip())):
                items.append(lines[index])
                index += 1
            out.append(_list(items, ctx))
            continue

        if stripped.startswith(">"):
            quote = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip()[1:].lstrip())
                index += 1
            out.append(f"<blockquote>{render_blocks(quote, ctx)}</blockquote>")
            continue

        if stripped in ("---", "***", "___"):
            out.append("<hr>")
            index += 1
            continue

        if stripped.startswith("<") and stripped.endswith(">"):
            block = [line]
            index += 1
            while index < len(lines) and lines[index].strip():
                block.append(lines[index])
                index += 1
            # Raw HTML is not markdown-processed, so assets referenced inside
            # a <figure> need the page's root prefix explicitly.
            markup = "\n".join(block)
            markup = markup.replace('src="assets/', f'src="{ctx["root"]}assets/')
            markup = markup.replace('href="assets/', f'href="{ctx["root"]}assets/')
            if ctx.get("version"):
                prefix = re.escape(ctx["root"] + "assets/")
                markup = re.sub(
                    r'((?:src|href)="' + prefix + r'[^"?]+)"',
                    rf'\1?v={ctx["version"]}"', markup)
            out.append(markup)
            continue

        paragraph = [stripped]
        index += 1
        while index < len(lines) and lines[index].strip() \
                and not _BLOCK_START.match(lines[index].strip()):
            paragraph.append(lines[index].strip())
            index += 1
        out.append(f"<p>{inline(' '.join(paragraph), ctx)}</p>")

    return "\n".join(out)


# ── page assembly ──────────────────────────────────────────────────────

def read_nav() -> list[dict]:
    data = tomllib.loads((ROOT / "nav.toml").read_text(encoding="utf-8"))
    sections = []
    seen = set()
    for section in data["sections"]:
        pages = []
        for entry in section["pages"]:
            title, path = entry[0], entry[1]
            blurb = entry[2] if len(entry) > 2 else ""
            if path in seen:
                raise SystemExit(f"nav: {path} is listed twice")
            seen.add(path)
            pages.append({"title": title, "path": path, "blurb": blurb})
        sections.append({"title": section["title"], "pages": pages})
    return sections


def _template(body: str, page: dict, nav_html: str, toc_html: str,
              pager: str, ctx: dict) -> str:
    title = html.escape(page["title"])
    description = html.escape(page["blurb"] or SITE_TAGLINE, quote=True)
    return f"""<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {SITE_NAME}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title} · {SITE_NAME}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="article">
<link rel="stylesheet" href="{ctx['root']}assets/css/site.css?v={ctx['version']}">
<link rel="icon" href="{ctx['root']}assets/img/favicon.svg" type="image/svg+xml">
<noscript><style>.nav-pages[hidden]{{display:block}}.nav-toggle{{pointer-events:none}}.chevron{{display:none}}</style></noscript>
</head>
<body>
<a class="skip" href="#content">Skip to content</a>
<header class="topbar">
  <button class="menu" type="button" aria-label="Toggle navigation">☰</button>
  <a class="brand" href="{ctx['root']}index.html">
    <span class="brand-mark">NP</span>
    <span class="brand-name">{SITE_NAME}</span>
  </a>
  <span class="tagline">{SITE_TAGLINE}</span>
  <div class="search">
    <input type="search" id="search" placeholder="Search docs…  (press /)"
           autocomplete="off" aria-label="Search documentation">
    <div class="results" id="results" hidden></div>
  </div>
  <button class="theme" type="button" title="Toggle light / dark">Dark</button>
  <a class="repo" href="{REPO_URL}" target="_blank" rel="noopener" title="Source repository">GitLab ↗</a>
</header>
<div class="shell">
  <nav class="sidebar" id="sidebar" aria-label="Documentation">
{nav_html}
  </nav>
  <main id="content">
    <article>
{body}
    </article>
    <nav class="pager" aria-label="Previous and next page">
{pager}
    </nav>
    <footer class="page-foot">
      <a href="{EDIT_URL}{page['path']}" target="_blank" rel="noopener">Edit this page</a>
      <span>·</span>
      <a href="{REPO_URL}/-/issues" target="_blank" rel="noopener">Report a problem</a>
      <span>·</span>
      <a href="{ctx['root']}search.html">Search all pages</a>
    </footer>
  </main>
  <aside class="toc" aria-label="On this page">
{toc_html}
  </aside>
</div>
<script>window.SITE_ROOT = "{ctx['root']}";</script>
<script src="{ctx['root']}assets/js/site.js?v={ctx['version']}"></script>
</body>
</html>
"""


def build_nav(sections: list[dict], current: str, root: str) -> str:
    """Collapsible sections: the current one is open, the rest start closed.

    Without JavaScript the page still works: a <noscript> rule in the head
    makes every group visible again.
    """
    out = []
    for index, section in enumerate(sections):
        active = any(page["path"] == current for page in section["pages"])
        ident = f"nav-{slug(section['title'])}-{index}"
        expanded = "true" if active else "false"
        hidden = "" if active else " hidden"
        out.append(
            f'<div class="nav-section{" active" if active else ""}" '
            f'data-section="{html.escape(section["title"], quote=True)}">')
        out.append(
            f'<button class="nav-toggle" type="button" aria-expanded="{expanded}" '
            f'aria-controls="{ident}">'
            f'<span class="nav-title">{html.escape(section["title"])}</span>'
            '<span class="chevron" aria-hidden="true"></span></button>')
        out.append(f'<ul class="nav-pages" id="{ident}"{hidden}>')
        for page in section["pages"]:
            cls = ' class="current"' if page["path"] == current else ""
            href = f"{root}{page['path'][:-3]}.html"
            out.append(f'<li{cls}><a href="{href}">{html.escape(page["title"])}</a></li>')
        out.append("</ul></div>")
    return "\n".join(out)


def build_toc(headings: list[tuple[int, str, str]]) -> str:
    items = [f'<li class="l{level}"><a href="#{anchor}">{html.escape(text)}</a></li>'
             for level, text, anchor in headings if level in (2, 3)]
    if not items:
        return '<p class="toc-title">On this page</p><p class="toc-empty">—</p>'
    return '<p class="toc-title">On this page</p><ul>' + "".join(items) + "</ul>"


def plain_text(markdown: str) -> str:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.S)
    text = re.sub(r"!!!.*", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#*`>|_~-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build(out_dir: Path, strict: bool = True) -> list[str]:
    sections = read_nav()
    order = [(section["title"], page) for section in sections
             for page in section["pages"]]
    paths = {page["path"] for _, page in order}

    for _, page in order:
        if not (PAGES / page["path"]).is_file():
            raise SystemExit(f"nav lists a missing page: {page['path']}")
    for path in sorted(p.relative_to(PAGES).as_posix()
                       for p in PAGES.rglob("*.md")):
        if path not in paths:
            raise SystemExit(f"page {path} is not in nav.toml (it would be orphaned)")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    shutil.copytree(ASSETS, out_dir / "assets")
    # Cache-busting: a redeployed site must not serve yesterday's stylesheet
    # or diagram.  Hash every asset so any change invalidates the URLs.
    digest = hashlib.sha1()
    for path in sorted(ASSETS.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(ASSETS).as_posix().encode())
            digest.update(path.read_bytes())
    version = digest.hexdigest()[:8]

    search_index = []
    problems = []
    link_targets: list[tuple[str, Path, str]] = []
    for position, (section_title, page) in enumerate(order):
        markdown = (PAGES / page["path"]).read_text(encoding="utf-8")
        depth = len(Path(page["path"]).parts) - 1
        ctx = {"page": PAGES / page["path"], "root": "../" * depth,
               "headings": [], "version": version}
        body = render_blocks(markdown.splitlines(), ctx)
        prev_page = order[position - 1] if position else None
        next_page = order[position + 1] if position + 1 < len(order) else None
        pager = []
        if prev_page:
            pager.append(f'<a class="prev" href="{ctx["root"]}{prev_page[1]["path"][:-3]}.html">'
                         f'<span>Previous</span>{html.escape(prev_page[1]["title"])}</a>')
        if next_page:
            pager.append(f'<a class="next" href="{ctx["root"]}{next_page[1]["path"][:-3]}.html">'
                         f'<span>Next</span>{html.escape(next_page[1]["title"])}</a>')
        html_page = _template(body, page,
                              build_nav(sections, page["path"], ctx["root"]),
                              build_toc(ctx["headings"]),
                              "\n".join(pager), ctx)
        target = out_dir / (page["path"][:-3] + ".html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_page, encoding="utf-8")
        search_index.append({
            "title": page["title"],
            "section": section_title,
            "url": page["path"][:-3] + ".html",
            "blurb": page["blurb"],
            "headings": [plain_text(text) for level, text, _ in ctx["headings"]
                         if level in (2, 3)],
            "text": plain_text(markdown)[:4000],
        })

        # Collected here, checked after every page (search.html, 404.html and
        # the assets are written later in this function).
        for href in re.findall(r'(?:href|src)="([^"]+)"', html_page):
            link_targets.append((page["path"], target, href))

    (out_dir / "search-index.json").write_text(
        json.dumps(search_index, ensure_ascii=False), encoding="utf-8")

    search_body = ('<h1 id="search">Search</h1><p>Type to filter every page of this '
                   'documentation. Results open the page at the top; use the '
                   'browser search (Ctrl+F) inside a page to jump to a word.</p>'
                   '<div class="search-page">'
                   '<input type="search" id="search-page" placeholder="Search…">'
                   '<div id="search-page-results" class="results static"></div></div>')
    ctx = {"page": PAGES / "index.md", "root": "", "headings": [], "version": version}
    (out_dir / "search.html").write_text(_template(
        search_body, {"title": "Search", "path": "search.md",
                      "blurb": "Search every page."},
        build_nav(sections, "", ""),
        '<p class="toc-title">On this page</p>', "", ctx), encoding="utf-8")
    (out_dir / "404.html").write_text(_template(
        '<h1 id="not-found">Page not found</h1><p>This page does not exist (any '
        'more). Try the search or start from the '
        '<a href="index.html">overview</a>.</p>',
        {"title": "Not found", "path": "404.md", "blurb": "Page not found."},
        build_nav(sections, "", ""),
        '<p class="toc-title">On this page</p>', "", ctx), encoding="utf-8")
    (out_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n", encoding="utf-8")
    urls = "".join(f"<url><loc>{SITE_URL}{page['path'][:-3]}.html</loc></url>"
                   for _, page in order)
    (out_dir / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>", encoding="utf-8")

    anchor_cache: dict[Path, set[str]] = {}

    def anchors_of(path: Path) -> set[str]:
        if path not in anchor_cache:
            anchor_cache[path] = set(
                re.findall(r'id="([^"]+)"', path.read_text(encoding="utf-8")))
        return anchor_cache[path]

    for page_path, target, href in link_targets:
        if href.startswith(("http", "mailto:", "data:")):
            continue
        clean, _, fragment = html.unescape(href).partition("#")
        clean = clean.split("?")[0]
        if clean:
            candidate = (target.parent / clean).resolve()
            if not str(candidate).startswith(str(out_dir.resolve())):
                continue
            if not candidate.exists():
                problems.append(f"{page_path}: broken link {href}")
                continue
        else:
            candidate = target
        if fragment and candidate.suffix == ".html" and candidate.is_file():
            if fragment not in anchors_of(candidate):
                problems.append(f"{page_path}: broken anchor {href}")

    if problems:
        for problem in problems:
            print(f"[LINK] {problem}", file=sys.stderr)
        if strict:
            raise SystemExit(f"{len(problems)} broken internal link(s)")
    print(f"Built {len(order)} pages into {out_dir}")
    return problems


def serve(directory: Path, port: int) -> None:
    import functools
    import http.server

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(directory))
    print(f"Serving {directory} on http://localhost:{port}/  (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT.parents[1] / "public"))
    parser.add_argument("--serve", type=int, default=0, metavar="PORT")
    parser.add_argument("--check", action="store_true",
                        help="verify the build and its links, then remove the output")
    parser.add_argument("--no-strict", action="store_true",
                        help="do not fail on broken internal links")
    args = parser.parse_args(argv)
    out = Path(args.out)
    problems = build(out, strict=not args.no_strict and not args.check)
    if args.check:
        shutil.rmtree(out, ignore_errors=True)
        return 1 if problems else 0
    if args.serve:
        serve(out, args.serve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
