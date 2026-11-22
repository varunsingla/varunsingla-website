#!/usr/bin/env python3
"""
check_seo.py — verify what search engines are told about every page.

Run it after `python3 generate_geo.py` (or after editing a hand-written page):

    python3 check_seo.py            # exit 1 when something is wrong
    python3 check_seo.py --verbose  # also list warnings and per-page details

It reads the files on disk, exactly as GitHub Pages will serve them, and fails on:

  * a page without a <title>, meta description, canonical link, <h1> or social image
  * two indexable pages sharing a title, or a canonical link pointing at the wrong address
  * structured data (JSON-LD) that does not parse, misses a field Google needs for an
    article, or refers to an @id nothing on the page defines
  * a sitemap entry that does not exist, is marked noindex, or is canonicalised elsewhere,
    and an indexable page that the sitemap leaves out
  * an internal link or an icon/manifest reference that leads nowhere
  * the author being described differently on different pages

Warnings (not failures): a title over 70 characters (entry headlines excepted), a description
outside 70–160 characters.

Redirect stubs (pages whose only job is a meta refresh) are checked for a working target
and otherwise ignored.
"""
from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = "https://varunsingla.com"
PERSON_ID = f"{SITE}/#varun"
AUTHOR = "Varun Singla"
SKIP_DIRS = {'.git', '__pycache__', 'node_modules'}


def pages() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob('*.html')):
        if not any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            out.append(p)
    return out


def url_of(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    if rel == 'index.html':
        return f"{SITE}/"
    if rel.endswith('/index.html'):
        return f"{SITE}/{rel[:-len('index.html')]}"
    return f"{SITE}/{rel}"


def file_for(url_path: str) -> Path | None:
    """The file GitHub Pages serves for a site-relative path, or None."""
    clean = url_path.split('#')[0].split('?')[0]
    if not clean.startswith('/'):
        return None
    target = ROOT / clean.lstrip('/')
    if clean.endswith('/'):
        target = target / 'index.html'
    elif target.is_dir():
        target = target / 'index.html'
    return target if target.is_file() else None


def attr(tag: str, name: str) -> str:
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', tag) or re.search(rf"\b{name}\s*=\s*'([^']*)'", tag)
    return html.unescape(m.group(1)) if m else ''


def meta(text: str, key: str, value: str) -> str:
    """content of <meta key="value" content="…">, whichever order the attributes come in."""
    for tag in re.findall(r'<meta\b[^>]*>', text, re.I):
        if attr(tag, key).lower() == value.lower():
            return attr(tag, 'content')
    return ''


def link(text: str, rel: str) -> str:
    for tag in re.findall(r'<link\b[^>]*>', text, re.I):
        if attr(tag, 'rel').lower() == rel.lower():
            return attr(tag, 'href')
    return ''


def walk(node, found: list):
    if isinstance(node, dict):
        found.append(node)
        for v in node.values():
            walk(v, found)
    elif isinstance(node, list):
        for v in node:
            walk(v, found)


def main(argv: list[str]) -> int:
    verbose = '--verbose' in argv
    errors: list[str] = []
    warnings: list[str] = []
    titles: dict[str, list[str]] = defaultdict(list)
    indexable: dict[str, Path] = {}          # url -> file, for the sitemap comparison
    noindex: set[str] = set()
    canonical_elsewhere: set[str] = set()
    person_names: dict[str, set[str]] = defaultdict(set)
    n_pages = n_ld = n_links = 0

    for path in pages():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding='utf-8')
        url = url_of(path)

        refresh = re.search(r'<meta\s+http-equiv="refresh"\s+content="\d+;\s*url=([^"]+)"', text, re.I)
        if refresh:                                    # a redirect stub
            if not file_for(refresh.group(1)):
                errors.append(f"{rel}: redirects to {refresh.group(1)}, which does not exist")
            if 'noindex' not in meta(text, 'name', 'robots'):
                errors.append(f"{rel}: redirect stub should be noindex")
            continue

        n_pages += 1
        is_404 = rel == '404.html'
        head = text[:text.find('</head>')] if '</head>' in text else text
        body_static = re.sub(r'<script\b.*?</script>', '', text, flags=re.S | re.I)

        # ── basics ──
        if not re.search(r'<html[^>]*\blang="en', text):
            errors.append(f"{rel}: <html> has no lang attribute")
        t = re.findall(r'<title>(.*?)</title>', head, re.S)
        title = html.unescape(t[0]).strip() if t else ''
        if len(t) != 1 or not title:
            errors.append(f"{rel}: expected exactly one non-empty <title>, found {len(t)}")
        desc = meta(head, 'name', 'description')
        if not desc:
            errors.append(f"{rel}: no meta description")
        robots = meta(head, 'name', 'robots')
        canonical = link(head, 'canonical')
        h1 = re.findall(r'<h1\b', body_static)
        if len(h1) != 1:
            errors.append(f"{rel}: expected exactly one <h1> in the static HTML, found {len(h1)}")
        if 'viewport' not in head:
            errors.append(f"{rel}: no viewport meta tag")

        if 'noindex' in robots:
            noindex.add(url)
        elif not is_404:
            if not canonical:
                errors.append(f"{rel}: no canonical link")
            elif canonical != url:
                if file_for(canonical[len(SITE):]) if canonical.startswith(SITE) else None:
                    canonical_elsewhere.add(url)       # a declared duplicate of another page
                else:
                    errors.append(f"{rel}: canonical {canonical} is not this page ({url}) and not another page")
            if canonical == url:
                indexable[url] = path
                titles[title].append(rel)
                if len(title) > 70 and not rel.startswith('entries/2'):   # entry titles are the day's headline
                    warnings.append(f"{rel}: title is {len(title)} characters (search results show about 60)")
                if desc and not 70 <= len(desc) <= 160:
                    warnings.append(f"{rel}: description is {len(desc)} characters (aim for 70–160)")

        # ── link previews ──
        if not is_404:
            for prop in ('og:title', 'og:description', 'og:image', 'og:url', 'og:site_name'):
                if not meta(head, 'property', prop):
                    errors.append(f"{rel}: missing {prop}")
            if meta(head, 'property', 'og:url') and meta(head, 'property', 'og:url') != canonical and 'noindex' not in robots:
                errors.append(f"{rel}: og:url differs from the canonical link")
            if not meta(head, 'name', 'twitter:card'):
                errors.append(f"{rel}: missing twitter:card")
        img = meta(head, 'property', 'og:image')
        if img.startswith(SITE) and not file_for(img[len(SITE):]):
            errors.append(f"{rel}: og:image {img} does not exist")

        # ── icons and manifest ──
        for tag in re.findall(r'<link\b[^>]*>', head, re.I):
            if attr(tag, 'rel').lower() in ('icon', 'apple-touch-icon', 'manifest'):
                href = attr(tag, 'href')
                if href.startswith('data:'):
                    errors.append(f"{rel}: favicon is a data: URI; search engines need a file they can fetch")
                elif href.startswith('/') and not file_for(href):
                    errors.append(f"{rel}: {attr(tag, 'rel')} {href} does not exist")
        if not re.search(r'<link\b[^>]*rel="icon"', head):
            errors.append(f"{rel}: no favicon link")

        # ── structured data ──
        blocks = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', text, re.S)
        nodes: list[dict] = []
        for raw in blocks:
            if not raw.strip() or raw.strip() == '[]':
                continue                                # filled in by the page's script at run time
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"{rel}: JSON-LD does not parse ({exc})")
                continue
            n_ld += 1
            walk(data, nodes)
        if not is_404 and not nodes:
            errors.append(f"{rel}: no structured data")
        defined = {n['@id'] for n in nodes if '@id' in n and len(n) > 1}
        for n in nodes:
            if list(n.keys()) == ['@id'] and n['@id'] not in defined:
                errors.append(f"{rel}: JSON-LD refers to {n['@id']} but nothing on the page defines it")
            if n.get('@type') == 'Person' and n.get('@id') == PERSON_ID:
                person_names[n.get('name', '')].add(rel)
            if n.get('@type') == 'BlogPosting':
                for field in ('headline', 'datePublished', 'dateModified', 'author', 'image', 'mainEntityOfPage'):
                    if not n.get(field):
                        errors.append(f"{rel}: BlogPosting has no {field}")
            if n.get('@type') == 'BreadcrumbList':
                for item in n.get('itemListElement', []):
                    target = item.get('item', '')
                    if target.startswith(SITE) and not file_for(target[len(SITE):] or '/'):
                        errors.append(f"{rel}: breadcrumb points at {target}, which does not exist")
        if rel.startswith('entries/2') and not any(n.get('@type') == 'BlogPosting' for n in nodes):
            errors.append(f"{rel}: entry page has no BlogPosting")
        if rel in ('index.html', 'about/index.html'):
            full = [n for n in nodes if n.get('@type') == 'Person' and n.get('jobTitle')]
            if not full:
                errors.append(f"{rel}: the full Person record is missing")
            if rel == 'index.html' and not any(n.get('@type') == 'WebSite' and n.get('name') for n in nodes):
                errors.append(f"{rel}: no WebSite record (Google reads the site name from it)")
            if rel == 'about/index.html' and not any(n.get('@type') == 'ProfilePage' for n in nodes):
                errors.append(f"{rel}: no ProfilePage record")

        # ── internal links ──
        for href in set(re.findall(r'<a\b[^>]*\bhref="([^"]+)"', body_static)):
            href = html.unescape(href)
            if '${' in href:                            # a template inside page script
                continue
            if href.startswith(SITE):
                href = href[len(SITE):] or '/'
            if href.startswith('/'):
                n_links += 1
                if not file_for(href):
                    errors.append(f"{rel}: link to {href} leads nowhere")
            elif not re.match(r'(https?:|mailto:|#|tel:)', href) and href:
                n_links += 1
                target = (path.parent / href.split('#')[0].split('?')[0])
                if not (target.is_file() or (target.is_dir() and (target / 'index.html').is_file())):
                    errors.append(f"{rel}: link to {href} leads nowhere")

    # ── across pages ──
    for title, rels in titles.items():
        if len(rels) > 1:
            errors.append(f"title used by {len(rels)} indexable pages ({', '.join(rels[:4])}): {title[:70]}")
    names = {n for n in person_names if n}
    if names != {AUTHOR}:
        errors.append(f"the author is named inconsistently in structured data: {sorted(names)}")

    # ── sitemap ──
    sm = ROOT / 'sitemap.xml'
    try:
        locs = [el.text.strip() for el in ET.parse(sm).getroot().iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    except (ET.ParseError, FileNotFoundError) as exc:
        locs = []
        errors.append(f"sitemap.xml could not be read ({exc})")
    for loc in locs:
        if not loc.startswith(SITE) or not file_for(loc[len(SITE):] or '/'):
            errors.append(f"sitemap.xml lists {loc}, which does not exist")
        elif loc in noindex:
            errors.append(f"sitemap.xml lists {loc}, which is noindex")
        elif loc in canonical_elsewhere:
            errors.append(f"sitemap.xml lists {loc}, which is canonicalised to another page")
    if len(locs) != len(set(locs)):
        errors.append("sitemap.xml lists a URL more than once")
    for url in sorted(set(indexable) - set(locs)):
        errors.append(f"sitemap.xml leaves out {url}")

    # ── robots.txt ──
    robots_txt = (ROOT / 'robots.txt').read_text(encoding='utf-8') if (ROOT / 'robots.txt').exists() else ''
    if f"Sitemap: {SITE}/sitemap.xml" not in robots_txt:
        errors.append("robots.txt does not name the sitemap")
    if re.search(r'^Disallow:\s*/\s*$', robots_txt, re.M):
        errors.append("robots.txt blocks the whole site for some crawler")
    for needed in ('/index.json',):
        if re.search(rf'^Disallow:\s*{re.escape(needed)}', robots_txt, re.M):
            errors.append(f"robots.txt blocks {needed}, which the home page needs to render")

    print(f"check_seo: {n_pages} pages, {n_ld} structured-data blocks, {n_links} internal links, "
          f"{len(locs)} sitemap URLs, {len(noindex)} noindex, {len(canonical_elsewhere)} canonicalised elsewhere")
    if verbose or errors:
        for w in warnings:
            print(f"  warn  {w}")
    elif warnings:
        print(f"  {len(warnings)} warning(s) — run with --verbose to list them")
    for e in errors:
        print(f"  FAIL  {e}")
    print("PASS" if not errors else f"FAILED: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
