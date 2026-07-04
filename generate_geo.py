#!/usr/bin/env python3
"""
Generative Engine Optimization (GEO) generator for varunsingla.com.

Most AI crawlers (GPTBot, ClaudeBot, PerplexityBot, …) do not execute
JavaScript, so the client-rendered journal in index.html is invisible to
them. This script renders learnings.json into static, crawler-readable
artifacts:

  entries/<date>.html   one static page per journal entry (+ JSON-LD)
  entries/index.html    crawlable archive of all entries
  llms.txt              LLM-friendly site index (llmstxt.org convention)
  llms-full.txt         full journal text as markdown, one file
  feed.xml              RSS 2.0 feed (latest entries, full content)
  sitemap.xml           complete sitemap covering every page
  index.html            refreshes the static-fallback block between
                        GEO:STATIC markers (crawler/no-JS content)

Run standalone (`python3 generate_geo.py`) or via update_site.py, which
calls generate() after each daily content update and pushes whatever
changed. Files are only rewritten when their content changes, so the
returned list is exactly what needs pushing.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

SITE = "https://varunsingla.com"
AUTHOR = "Varun Singla"
BLOG_NAME = "Varun Singla · AI Learning Journal"
ACCENT = "#CC3F2A"
TZ = timezone(timedelta(hours=8))  # Singapore
FEED_SIZE = 20

SCRIPT_DIR = Path(__file__).parent

# Theme classifier — mirrors the RULES/classify() logic in index.html so
# static pages and the SPA agree on each entry's themes.
THEMES = ['Foundations & Protocols', 'Industry Verticals', 'Enterprise & Strategy',
          'Infrastructure & Economics', 'Models & Frontier', 'Governance & Safety']
RULES = {
    'Industry Verticals': ['healthcare', 'life science', 'clinical', 'hospital', 'pharma', 'telecom', 'network', 'insurance', 'underwriting', 'financial service', 'fp&a', ' finance', 'banking', 'wall street', 'manufacturing', 'industrial', 'supply chain', 'retail', 'e-commerce', 'ecommerce', 'legal', 'contract', ' hr ', 'people operation', 'education', 'edtech', 'marketing', 'customer success', ' customer', 'sales &', 'revenue operation', ' media', 'entertainment', 'energy & climate', 'energy &', 'scientific research', 'public sector', 'govtech', 'real estate', 'proptech', 'in financial', 'vertical', 'construction'],
    'Infrastructure & Economics': ['data centre', 'data center', 'data-centre', 'power wall', 'cooling', 'water wall', 'inference econom', 'compute map', 'sovereign ai', 'hyperscaler', 'capex', 'tokenomic', 'token economic', ' gpu', 'chip', 'silicon', 'power &'],
    'Governance & Safety': ['safety', 'governance', 'eu ai act', 'ai act', 'regulat', 'compliance', 'agent identity', 'identity 3.0', 'identity 2.0', 'spiffe', 'know your agent', ' kya', 'red team', 'red-team', 'fair-housing', 'liability'],
    'Models & Frontier': ['frontier', 'model wars', 'open weight', 'open-weight', 'open-source', 'open source', 'multimodal', 'multi-modal', 'voice stack', 'gemini', 'mythos', 'vla', 'humanoid', 'robot', 'model race', 'reasoning model', 'quantiz', 'google i/o', 'i/o 2026', 'physical ai'],
    'Enterprise & Strategy': ['enterprise', 'coe', 'center of excellence', 'centre of excellence', ' roi', 'procurement', 'operating model', 'buyer', 'org chart', 'finops', 'valuation', 'moat', 'go-to-market', 'take rate', 'control plane', 'future of work', 'career', 'roles', 'cfo', 'cio', 'business case', 'adoption', 'scorecard', 'app store', 'skills economy', 'marketplace', 'agent economy', 'competitive'],
    'Foundations & Protocols': ['mcp', 'model context protocol', 'a2a', 'agent-to-agent', 'protocol', 'memory', 'orchestrat', 'agentic rag', ' rag', 'observability', 'reliability', 'eval', 'testing', 'multi-agent', 'multi agent', 'communication', 'agent pattern', 'first agent', 'first ai agent', 'first production', 'tool optim', 'tool use', 'tool-use', 'interop', 'skill.md', 'building your', 'microservices', 'agent skill', 'data infrastructure', 'browser', 'debugging', 'routing'],
}


def classify(e: dict) -> list[str]:
    t = (e.get('title') or '').lower()
    heads = ' '.join(s.get('title') or '' for s in e.get('sections') or []).lower()
    score = {k: 0 for k in THEMES}
    for th, kws in RULES.items():
        for k in kws:
            if k in t:
                score[th] += 3
            if k in heads:
                score[th] += 1
    ranked = sorted(THEMES, key=lambda k: (-score[k], THEMES.index(k)))
    chosen = [k for k in ranked if score[k] > 0][:2]
    if not chosen:
        chosen = ['Foundations & Protocols']
    if score['Industry Verticals'] >= 3:
        chosen = ['Industry Verticals'] + [c for c in chosen if c != 'Industry Verticals']
        chosen = chosen[:2]
    return chosen


def esc(s) -> str:
    return html.escape(str(s), quote=True) if s is not None else ''


def first_sentences(text: str, max_len: int = 190) -> str:
    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    stop = max(cut.rfind('. '), cut.rfind('? '), cut.rfind('! '))
    if stop > max_len * 0.5:
        return text[:stop + 1]
    sp = cut.rfind(' ')
    return text[:sp if sp > 0 else max_len].strip() + '…'


def word_count(e: dict) -> int:
    n = len((e.get('focus_intro') or '').split())
    for s in e.get('sections') or []:
        for p in s.get('paragraphs') or []:
            n += len(p.split())
        for b in s.get('bullets') or []:
            n += len(b.split())
    tk = e.get('practical_takeaway')
    if isinstance(tk, list):
        for t in tk:
            n += len(((t.get('title') or '') + ' ' + (t.get('body') or '')).split())
    elif isinstance(tk, str):
        n += len(tk.split())
    return n


def long_date(iso: str) -> str:
    d = datetime.strptime(iso[:10], '%Y-%m-%d')
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def rfc822(iso: str) -> str:
    d = datetime.strptime(iso[:10], '%Y-%m-%d').replace(hour=21, tzinfo=TZ)
    return d.strftime('%a, %d %b %Y %H:%M:%S %z')


def prepare(data: dict) -> list[dict]:
    """Filter, sort ascending, and annotate entries with derived fields."""
    entries = [e for e in data.get('learnings', []) if e.get('title') and str(e['title']).strip()]
    entries.sort(key=lambda e: str(e['date']))
    for i, e in enumerate(entries):
        e['_day'] = i + 1
        e['_tags'] = classify(e)
        e['_words'] = word_count(e)
        e['_read'] = max(3, round(e['_words'] / 210))
        intro = e.get('focus_intro') or ''
        if not intro and e.get('sections'):
            paras = e['sections'][0].get('paragraphs') or []
            intro = paras[0] if paras else ''
        e['_excerpt'] = first_sentences(intro, 190)
        e['_file'] = f"entries/{e['date']}.html"
        e['_url'] = f"{SITE}/entries/{e['date']}.html"
    return entries


# ── Entry-page HTML ───────────────────────────────────────────────────────────

PAGE_CSS = """
*{box-sizing:border-box;}
html,body{margin:0;padding:0;background:#F7F4ED;}
body{font-family:'Hanken Grotesk',sans-serif;color:#1B1A17;-webkit-font-smoothing:antialiased;}
::selection{background:#CC3F2A;color:#fff;}
a{color:inherit;}
.mast{position:sticky;top:0;z-index:50;background:rgba(247,244,237,.9);backdrop-filter:blur(12px);border-bottom:1px solid #E4DECF;}
.mast-in{max-width:1120px;margin:0 auto;padding:16px 28px;display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;}
.brand{display:flex;align-items:center;gap:11px;text-decoration:none;}
.brand-mark{width:30px;height:30px;border-radius:7px;background:#1B1A17;color:#F7F4ED;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;}
.brand-name{font-family:'JetBrains Mono',monospace;font-size:13.5px;color:#1B1A17;}
.nav-link{font-size:14.5px;font-weight:500;color:#6B6760;text-decoration:none;padding:7px 12px;border-radius:8px;}
.nav-link:hover{color:#1B1A17;background:#EEE9DC;}
.meta-row{display:flex;align-items:center;gap:13px;flex-wrap:wrap;font-family:'JetBrains Mono',monospace;font-size:13px;color:#8A857B;}
.meta-row .day{color:#CC3F2A;font-weight:500;}
.tag{font-family:'JetBrains Mono',monospace;font-size:11.5px;letter-spacing:.04em;color:#6B6760;border:1px solid #E4DECF;border-radius:999px;padding:5px 12px;background:#FBF9F3;text-decoration:none;}
article h1{font-family:'Newsreader',serif;font-weight:400;font-size:clamp(32px,5.5vw,52px);line-height:1.07;letter-spacing:-.018em;margin:0 0 22px;}
article h2{font-family:'Newsreader',serif;font-weight:500;font-size:clamp(23px,3.4vw,30px);line-height:1.18;margin:0 0 18px;}
article p{font-family:'Newsreader',serif;font-size:clamp(18px,2.3vw,20px);line-height:1.65;color:#2C2A24;margin:0 0 20px;}
article ul{margin:4px 0 20px;padding-left:20px;}
article li{font-family:'Newsreader',serif;font-size:clamp(17px,2.2vw,19px);line-height:1.6;color:#2C2A24;margin:0 0 10px;}
.intro{font-size:clamp(20px,3vw,24px)!important;line-height:1.5!important;color:#3A372F!important;font-style:italic;margin:0 0 40px!important;}
.callout{border:1px solid #E4DECF;border-left:3px solid #CC3F2A;border-radius:12px;background:#FBF9F3;padding:22px 24px;margin:0 0 40px;}
.callout p{font-size:clamp(17px,2.2vw,19px);margin:0;}
.kicker{font-family:'JetBrains Mono',monospace;font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:#CC3F2A;margin-bottom:14px;}
.highlight{font-family:'Newsreader',serif;font-style:italic;font-size:clamp(18px,2.4vw,20px);line-height:1.55;color:#3A372F;border-left:3px solid #CC3F2A;padding:6px 0 6px 16px;margin:8px 0 20px;}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:#E4DECF;border:1px solid #E4DECF;border-radius:12px;overflow:hidden;margin:0 0 40px;}
.stat-cell{background:#FBF9F3;padding:18px 20px;}
.stat-big{font-family:'Newsreader',serif;font-size:clamp(24px,4vw,32px);line-height:1.05;color:#1B1A17;}
.stat-small{font-size:13px;line-height:1.45;color:#56524B;margin-top:8px;}
.table-wrap{overflow-x:auto;border:1px solid #E4DECF;border-radius:12px;background:#FBF9F3;margin:0 0 20px;}
table{width:100%;border-collapse:collapse;}
th{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#8A857B;text-align:left;padding:9px 12px;border-bottom:1px solid #CBB8A0;font-weight:500;}
td{font-size:14.5px;color:#2C2A24;padding:9px 12px;border-bottom:1px solid #EEE9DC;vertical-align:top;line-height:1.45;font-family:'Hanken Grotesk',sans-serif;}
tr:last-child td{border-bottom:none;}
.pn{display:grid;grid-template-columns:1fr 1fr;gap:14px;max-width:680px;margin:0 auto;padding:20px 28px 90px;}
.pn a{border:1px solid #E4DECF;border-radius:12px;padding:18px 20px;background:#FBF9F3;text-decoration:none;display:block;}
.pn a:hover{border-color:#1B1A17;}
.pn .lbl{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#A8A294;margin-bottom:9px;}
.pn .ttl{font-family:'Newsreader',serif;font-size:18px;line-height:1.2;color:#1B1A17;}
footer{border-top:1px solid #E4DECF;background:#FBF9F3;}
.foot-in{max-width:1120px;margin:0 auto;padding:34px 28px;display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap;font-family:'JetBrains Mono',monospace;font-size:12.5px;color:#6B6760;}
""".strip()

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '<link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700'
         '&family=JetBrains+Mono:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,200..600;'
         '1,6..72,200..500&display=swap" rel="stylesheet">')


def masthead(depth: int = 1) -> str:
    r = '../' * depth
    return f"""<header class="mast"><div class="mast-in">
  <a class="brand" href="{r}"><span class="brand-mark">VS</span><span class="brand-name">varunsingla.com</span></a>
  <nav style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
    <a class="nav-link" href="{r}">Journal</a>
    <a class="nav-link" href="{r}entries/">Archive</a>
    <a class="nav-link" href="{r}about/">About</a>
    <a class="nav-link" href="{r}ai-tokenomics/">Tokenomics</a>
    <a class="nav-link" href="{r}tools/model-team-evaluator.html">Model Evaluator</a>
  </nav>
</div></header>"""


def page_footer() -> str:
    return f"""<footer><div class="foot-in">
  <span>{AUTHOR} · Singapore · Learning in public</span>
  <span><a href="{SITE}/feed.xml" style="text-decoration:none;color:#6B6760;">RSS</a> · <a href="{SITE}/llms.txt" style="text-decoration:none;color:#6B6760;">llms.txt</a> · Updated daily</span>
</div></footer>"""


def render_section(sec: dict) -> str:
    out = []
    if sec.get('title'):
        out.append(f"<h2>{esc(sec['title'])}</h2>")
    for p in sec.get('paragraphs') or []:
        out.append(f"<p>{esc(p)}</p>")
    bullets = sec.get('bullets') or []
    if bullets:
        out.append('<ul>' + ''.join(f'<li>{esc(b)}</li>' for b in bullets) + '</ul>')
    tbl = sec.get('table')
    if tbl and tbl.get('headers') and tbl.get('rows'):
        ths = ''.join(f'<th>{esc(h)}</th>' for h in tbl['headers'])
        trs = ''.join('<tr>' + ''.join(f'<td>{esc(c)}</td>' for c in r) + '</tr>' for r in tbl['rows'])
        out.append(f'<div class="table-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>')
    if sec.get('highlight'):
        out.append(f'<div class="highlight">{esc(sec["highlight"])}</div>')
    return f'<section>{"".join(out)}</section>'


def render_body_blocks(e: dict) -> str:
    """The article body (everything below the h1/meta), shared by the entry page and the RSS feed."""
    out = []
    intro = e.get('focus_intro') or ''
    if intro and intro.strip() != (e.get('title') or '').strip():
        out.append(f'<p class="intro">{esc(intro)}</p>')

    v = e.get('viral_app') or {}
    if v.get('name'):
        inner = f'<div class="kicker">Viral app of the day</div><p style="font-family:\'Newsreader\',serif;font-size:22px;font-weight:500;margin:0 0 10px;">{esc(v["name"])}</p>'
        if v.get('description'):
            inner += f'<p>{esc(v["description"])}</p>'
        vstats = v.get('stats') or []
        if vstats:
            inner += '<ul style="margin-bottom:0;">' + ''.join(
                f'<li>{esc(s.get("stat",""))} — {esc(s.get("label",""))}</li>' for s in vstats) + '</ul>'
        out.append(f'<div class="callout">{inner}</div>')

    stats = e.get('stats') or []
    key_stats = e.get('key_stats') or []
    if stats or key_stats:
        cells = ''
        if stats:
            cells = ''.join(f'<div class="stat-cell"><div class="stat-big">{esc(s.get("stat",""))}</div>'
                            f'<div class="stat-small">{esc(s.get("label",""))}</div></div>' for s in stats)
        else:
            cells = ''.join(f'<div class="stat-cell"><div class="stat-small" style="margin-top:0;font-family:\'Newsreader\',serif;font-size:15px;">{esc(s)}</div></div>' for s in key_stats)
        out.append(f'<div style="margin:0 0 40px;"><div class="kicker">By the numbers</div><div class="stat-grid">{cells}</div></div>')

    for sec in e.get('sections') or []:
        out.append(render_section(sec))

    if e.get('market_signal'):
        out.append(f'<div class="callout"><div class="kicker">Market signal</div><p>{esc(e["market_signal"])}</p></div>')

    tk = e.get('practical_takeaway')
    if tk:
        if isinstance(tk, list):
            inner = ''.join(
                f'<div style="margin:0 0 14px;"><div style="font-weight:600;font-size:15.5px;font-family:\'Hanken Grotesk\',sans-serif;">{esc(t.get("title",""))}</div>'
                + (f'<p style="font-size:17px;margin:3px 0 0;">{esc(t["body"])}</p>' if t.get('body') and t.get('body') != t.get('title') else '')
                + '</div>' for t in tk)
        else:
            inner = f'<p>{esc(tk)}</p>'
        out.append(f'<div class="callout"><div class="kicker">Practical takeaways</div>{inner}</div>')
    return '\n'.join(out)


def entry_jsonld(e: dict) -> str:
    post = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "@id": e['_url'] + "#post",
        "headline": e['title'],
        "description": e['_excerpt'],
        "datePublished": f"{e['date']}T21:00:00+08:00",
        "dateModified": f"{e['date']}T21:00:00+08:00",
        "url": e['_url'],
        "mainEntityOfPage": e['_url'],
        "wordCount": e['_words'],
        "inLanguage": "en",
        "articleSection": e['_tags'],
        "keywords": e['_tags'] + ["agentic AI", "AI learning journal", "Varun Singla"],
        "isPartOf": {"@type": "Blog", "@id": f"{SITE}/#blog", "name": BLOG_NAME},
        "author": {"@type": "Person", "@id": f"{SITE}/#varun", "name": AUTHOR, "url": f"{SITE}/about/"},
        "publisher": {"@type": "Person", "@id": f"{SITE}/#varun", "name": AUTHOR},
    }
    crumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Journal", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Archive", "item": f"{SITE}/entries/"},
            {"@type": "ListItem", "position": 3, "name": e['title'], "item": e['_url']},
        ],
    }
    return (f'<script type="application/ld+json">{json.dumps(post, ensure_ascii=False)}</script>\n'
            f'<script type="application/ld+json">{json.dumps(crumbs, ensure_ascii=False)}</script>')


def render_entry_page(e: dict, prev_e: dict | None, next_e: dict | None) -> str:
    title = f"{e['title']} — Day {e['_day']} | {BLOG_NAME}"
    tags = ''.join(f'<span class="tag">{esc(t)}</span> ' for t in e['_tags'])
    pn = '<nav class="pn" aria-label="Adjacent entries">'
    if next_e:
        pn += f'<a href="{next_e["date"]}.html" rel="next"><div class="lbl">← Newer · Day {next_e["_day"]}</div><div class="ttl">{esc(next_e["title"])}</div></a>'
    else:
        pn += '<span></span>'
    if prev_e:
        pn += f'<a href="{prev_e["date"]}.html" rel="prev" style="text-align:right;"><div class="lbl">Older · Day {prev_e["_day"]} →</div><div class="ttl">{esc(prev_e["title"])}</div></a>'
    else:
        pn += '<span></span>'
    pn += '</nav>'

    head_links = ''
    if next_e:
        head_links += f'<link rel="next" href="{SITE}/entries/{next_e["date"]}.html">\n'
    if prev_e:
        head_links += f'<link rel="prev" href="{SITE}/entries/{prev_e["date"]}.html">\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(e['_excerpt'])}">
<meta name="author" content="{AUTHOR}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
<link rel="canonical" href="{e['_url']}">
{head_links}<link rel="alternate" type="application/rss+xml" title="{esc(BLOG_NAME)}" href="{SITE}/feed.xml">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{esc(BLOG_NAME)}">
<meta property="og:title" content="{esc(e['title'])}">
<meta property="og:description" content="{esc(e['_excerpt'])}">
<meta property="og:url" content="{e['_url']}">
<meta property="og:image" content="{SITE}/og-image.png">
<meta property="article:published_time" content="{e['date']}T21:00:00+08:00">
<meta property="article:author" content="{SITE}/about/">
{''.join(f'<meta property="article:tag" content="{esc(t)}">' for t in e['_tags'])}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(e['title'])}">
<meta name="twitter:description" content="{esc(e['_excerpt'])}">
<meta name="twitter:image" content="{SITE}/og-image.png">
{FONTS}
{entry_jsonld(e)}
<style>{PAGE_CSS}</style>
</head>
<body>
{masthead(1)}
<article style="max-width:680px;margin:0 auto;padding:48px 28px 30px;">
  <p style="margin:0 0 38px;"><a href="./" style="font-family:'JetBrains Mono',monospace;font-size:12.5px;letter-spacing:.04em;color:#6B6760;text-decoration:none;">← All entries</a></p>
  <div class="meta-row" style="margin-bottom:22px;">
    <span class="day">Day {e['_day']}</span><span>·</span>
    <time datetime="{e['date']}">{long_date(e['date'])}</time><span>·</span>
    <span>{e['_read']} min read</span>
  </div>
  <h1>{esc(e['title'])}</h1>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:34px;padding-bottom:34px;border-bottom:1px solid #E4DECF;">{tags}</div>
  {render_body_blocks(e)}
  <div style="display:flex;align-items:center;gap:13px;margin:54px 0 10px;padding-top:30px;border-top:1px solid #E4DECF;">
    <div class="brand-mark" style="width:40px;height:40px;font-size:14px;border-radius:9px;">VS</div>
    <div><div style="font-size:14.5px;font-weight:600;">{AUTHOR}</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#8A857B;">Singapore · <a href="../about/" style="color:#8A857B;">About</a> · Learning in public</div></div>
  </div>
</article>
{pn}
{page_footer()}
</body>
</html>
"""


def render_entries_index(entries: list[dict]) -> str:
    """Crawlable archive page listing every entry, newest first, grouped by month."""
    newest = entries[-1]
    by_month: dict[str, list[dict]] = {}
    for e in reversed(entries):
        d = datetime.strptime(e['date'], '%Y-%m-%d')
        by_month.setdefault(d.strftime('%B %Y'), []).append(e)

    groups = []
    for month, es in by_month.items():
        items = ''.join(
            f'<li style="margin:0 0 18px;"><a href="{e["date"]}.html" style="text-decoration:none;">'
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:12.5px;color:{ACCENT};">Day {e["_day"]} · <time datetime="{e["date"]}">{long_date(e["date"])}</time></span>'
            f'<span style="display:block;font-family:\'Newsreader\',serif;font-size:clamp(19px,2.6vw,23px);line-height:1.25;color:#1B1A17;margin:4px 0 3px;">{esc(e["title"])}</span>'
            f'<span style="display:block;font-size:15px;line-height:1.5;color:#56524B;">{esc(e["_excerpt"])}</span></a></li>'
            for e in es)
        groups.append(f'<section style="margin:0 0 44px;"><h2 style="font-family:\'Newsreader\',serif;font-weight:500;font-size:clamp(22px,3vw,28px);border-bottom:1px solid #E4DECF;padding-bottom:12px;margin:0 0 22px;">{month}</h2><ul style="list-style:none;margin:0;padding:0;">{items}</ul></section>')

    item_list = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "@id": f"{SITE}/entries/",
        "name": f"All entries — {BLOG_NAME}",
        "url": f"{SITE}/entries/",
        "isPartOf": {"@type": "Blog", "@id": f"{SITE}/#blog", "name": BLOG_NAME},
        "author": {"@type": "Person", "@id": f"{SITE}/#varun", "name": AUTHOR},
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(entries),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "url": e['_url'], "name": e['title']}
                for i, e in enumerate(reversed(entries))
            ],
        },
    }
    desc = (f"Complete archive of {AUTHOR}'s AI learning journal — {len(entries)} daily entries on agentic AI, "
            f"MCP, multi-agent systems, AI economics and enterprise adoption, from {long_date(entries[0]['date'])} "
            f"to {long_date(newest['date'])}.")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>All Entries — {esc(BLOG_NAME)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="author" content="{AUTHOR}">
<meta name="robots" content="index, follow, max-snippet:-1">
<link rel="canonical" href="{SITE}/entries/">
<link rel="alternate" type="application/rss+xml" title="{esc(BLOG_NAME)}" href="{SITE}/feed.xml">
<meta property="og:type" content="website">
<meta property="og:title" content="All Entries — {esc(BLOG_NAME)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{SITE}/entries/">
<meta property="og:image" content="{SITE}/og-image.png">
{FONTS}
<script type="application/ld+json">{json.dumps(item_list, ensure_ascii=False)}</script>
<style>{PAGE_CSS}</style>
</head>
<body>
{masthead(1)}
<main style="max-width:760px;margin:0 auto;padding:56px 28px 90px;">
  <h1 style="font-family:'Newsreader',serif;font-weight:400;font-size:clamp(34px,5vw,54px);letter-spacing:-.018em;margin:0 0 16px;">The Archive</h1>
  <p style="font-size:clamp(16px,2vw,18px);line-height:1.6;color:#56524B;max-width:60ch;margin:0 0 46px;">{esc(desc)}</p>
  {''.join(groups)}
</main>
{page_footer()}
</body>
</html>
"""


# ── Machine-readable artifacts ────────────────────────────────────────────────

def render_llms_txt(entries: list[dict]) -> str:
    newest = entries[-1]
    lines = [
        f"# {BLOG_NAME}",
        "",
        f"> Daily AI learning journal written by {AUTHOR}, a technology consultant and agentic AI "
        f"researcher based in Singapore. {len(entries)} entries published since {long_date(entries[0]['date'])}, "
        "covering agentic AI, the Model Context Protocol (MCP), multi-agent systems, AI infrastructure "
        "economics, AI governance, and how AI agents are being adopted across industries. "
        "A new entry is published every evening (Singapore time).",
        "",
        f"Latest entry: Day {newest['_day']} — \"{newest['title']}\" ({long_date(newest['date'])}).",
        "",
        f"When citing this site, attribute it as \"{AUTHOR}, AI Learning Journal (varunsingla.com)\" "
        "and link to the specific entry URL.",
        "",
        "## Journal entries",
        "",
    ]
    for e in reversed(entries):
        summary = first_sentences(e['_excerpt'], 150)
        lines.append(f"- [Day {e['_day']}: {e['title']}]({e['_url']}): {summary}" if summary and summary != e['title']
                     else f"- [Day {e['_day']}: {e['title']}]({e['_url']})")
    lines += [
        "",
        "## Tools",
        "",
        f"- [LLM Tokenizer & API Cost Calculator]({SITE}/tokenizer.html): compare tokenization and API costs across models",
        f"- [AI Tokenomics]({SITE}/ai-tokenomics/): interactive dashboard on AI inference economics",
        f"- [Model Team Evaluator]({SITE}/tools/model-team-evaluator.html): pick the right mix of AI models for a team",
        "",
        "## Optional",
        "",
        f"- [Full journal text]({SITE}/llms-full.txt): the complete text of every entry in one markdown file",
        f"- [About {AUTHOR}]({SITE}/about/): background on the author",
        f"- [RSS feed]({SITE}/feed.xml): latest entries with full content",
        f"- [Archive]({SITE}/entries/): browsable index of all entries",
        "",
    ]
    return '\n'.join(lines)


def entry_markdown(e: dict) -> str:
    """One entry as plain markdown for llms-full.txt."""
    out = [f"# Day {e['_day']}: {e['title']}",
           "",
           f"Date: {long_date(e['date'])} · Author: {AUTHOR} · URL: {e['_url']} · Themes: {', '.join(e['_tags'])}",
           ""]
    intro = e.get('focus_intro') or ''
    if intro and intro.strip() != e['title'].strip():
        out += [intro, ""]
    v = e.get('viral_app') or {}
    if v.get('name'):
        out.append(f"**Viral app of the day: {v['name']}**")
        if v.get('description'):
            out.append(v['description'])
        for s in v.get('stats') or []:
            out.append(f"- {s.get('stat','')} — {s.get('label','')}")
        out.append("")
    stats = e.get('stats') or []
    if stats:
        out.append("**By the numbers:**")
        out += [f"- {s.get('stat','')} — {s.get('label','')}" for s in stats]
        out.append("")
    elif e.get('key_stats'):
        out.append("**By the numbers:**")
        out += [f"- {s}" for s in e['key_stats']]
        out.append("")
    for sec in e.get('sections') or []:
        if sec.get('title'):
            out += [f"## {sec['title']}", ""]
        for p in sec.get('paragraphs') or []:
            out += [p, ""]
        bullets = sec.get('bullets') or []
        if bullets:
            out += [f"- {b}" for b in bullets] + [""]
        tbl = sec.get('table')
        if tbl and tbl.get('headers') and tbl.get('rows'):
            out.append('| ' + ' | '.join(str(h) for h in tbl['headers']) + ' |')
            out.append('|' + '---|' * len(tbl['headers']))
            for r in tbl['rows']:
                out.append('| ' + ' | '.join(str(c) for c in r) + ' |')
            out.append("")
        if sec.get('highlight'):
            out += [f"> {sec['highlight']}", ""]
    if e.get('market_signal'):
        out += [f"**Market signal:** {e['market_signal']}", ""]
    tk = e.get('practical_takeaway')
    if tk:
        out.append("**Practical takeaways:**")
        if isinstance(tk, list):
            for t in tk:
                body = t.get('body') or ''
                title = t.get('title') or ''
                out.append(f"- {title}" + (f" — {body}" if body and body != title else ""))
        else:
            out.append(f"- {tk}")
        out.append("")
    return '\n'.join(out).rstrip() + '\n'


def render_llms_full(entries: list[dict]) -> str:
    head = (f"# {BLOG_NAME} — full text\n\n"
            f"Complete text of all {len(entries)} journal entries by {AUTHOR} "
            f"({SITE}), newest first. Index: {SITE}/llms.txt\n\n---\n\n")
    return head + '\n---\n\n'.join(entry_markdown(e) for e in reversed(entries))


def render_feed(entries: list[dict]) -> str:
    items = []
    for e in list(reversed(entries))[:FEED_SIZE]:
        content = render_body_blocks(e).replace(']]>', ']]&gt;')
        items.append(f"""  <item>
    <title>{esc(e['title'])}</title>
    <link>{e['_url']}</link>
    <guid isPermaLink="true">{e['_url']}</guid>
    <pubDate>{rfc822(e['date'])}</pubDate>
    <dc:creator>{AUTHOR}</dc:creator>
    {''.join(f'<category>{esc(t)}</category>' for t in e['_tags'])}
    <description>{esc(e['_excerpt'])}</description>
    <content:encoded><![CDATA[{content}]]></content:encoded>
  </item>""")
    newest = entries[-1]
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{esc(BLOG_NAME)}</title>
  <link>{SITE}/</link>
  <atom:link href="{SITE}/feed.xml" rel="self" type="application/rss+xml"/>
  <description>Daily deep dives into agentic AI, MCP, multi-agent systems and AI economics — written every evening by {AUTHOR}.</description>
  <language>en</language>
  <lastBuildDate>{rfc822(newest['date'])}</lastBuildDate>
{chr(10).join(items)}
</channel>
</rss>
"""


def render_sitemap(entries: list[dict]) -> str:
    newest = entries[-1]['date']
    static_pages = [
        (f"{SITE}/", newest, 'daily', '1.0'),
        (f"{SITE}/entries/", newest, 'daily', '0.9'),
        (f"{SITE}/about/", newest, 'monthly', '0.8'),
        (f"{SITE}/tokenizer.html", newest, 'monthly', '0.8'),
        (f"{SITE}/ai-tokenomics/", newest, 'monthly', '0.7'),
        (f"{SITE}/tools/model-team-evaluator.html", newest, 'monthly', '0.7'),
    ]
    urls = [f"""  <url>
    <loc>{loc}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>{freq}</changefreq>
    <priority>{prio}</priority>
  </url>""" for loc, lastmod, freq, prio in static_pages]
    for e in reversed(entries):
        urls.append(f"""  <url>
    <loc>{e['_url']}</loc>
    <lastmod>{e['date']}</lastmod>
    <changefreq>yearly</changefreq>
    <priority>0.6</priority>
  </url>""")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + '\n'.join(urls) + '\n</urlset>\n')


# ── index.html static-fallback block ─────────────────────────────────────────

STATIC_BEGIN = '<!-- GEO:STATIC:BEGIN (generated by generate_geo.py — do not edit by hand) -->'
STATIC_END = '<!-- GEO:STATIC:END -->'


def render_static_block(entries: list[dict]) -> str:
    """Static content inside #app so non-JS crawlers see the journal.
    The SPA replaces #app's innerHTML on load, so users never see this."""
    latest = list(reversed(entries))[:10]
    items = ''.join(
        f'<li style="margin:0 0 16px;"><a href="/entries/{e["date"]}.html">'
        f'<strong>Day {e["_day"]} · {long_date(e["date"])}: {esc(e["title"])}</strong></a><br>'
        f'{esc(e["_excerpt"])}</li>'
        for e in latest)
    newest = entries[-1]
    return f"""{STATIC_BEGIN}
<div style="max-width:760px;margin:0 auto;padding:56px 28px;font-family:'Hanken Grotesk',sans-serif;">
  <h1 style="font-family:'Newsreader',serif;font-weight:400;">Varun Singla — AI Learning Journal</h1>
  <p>Daily deep dives into agentic AI, the protocols that connect it (MCP, A2A), multi-agent systems,
  AI infrastructure economics, governance, and the industries AI is reshaping — written every evening
  by Varun Singla, a technology consultant and agentic AI researcher in Singapore.
  {len(entries)} entries published since {long_date(entries[0]['date'])}; updated daily.</p>
  <p><a href="/entries/">Browse the full archive</a> · <a href="/about/">About Varun Singla</a> ·
  <a href="/tokenizer.html">LLM Tokenizer &amp; Cost Calculator</a> · <a href="/ai-tokenomics/">AI Tokenomics</a> ·
  <a href="/tools/model-team-evaluator.html">Model Team Evaluator</a> · <a href="/feed.xml">RSS</a> · <a href="/llms.txt">llms.txt</a></p>
  <h2 style="font-family:'Newsreader',serif;font-weight:500;">Latest entry — Day {newest['_day']}, {long_date(newest['date'])}</h2>
  <p><a href="/entries/{newest['date']}.html"><strong>{esc(newest['title'])}</strong></a><br>{esc(newest['_excerpt'])}</p>
  <h2 style="font-family:'Newsreader',serif;font-weight:500;">Recent entries</h2>
  <ul style="list-style:none;padding:0;">{items}</ul>
</div>
{STATIC_END}"""


def update_index_html(root: Path, entries: list[dict]) -> str | None:
    """Splice the fresh static block into index.html. Returns new text or None if markers absent."""
    path = root / 'index.html'
    text = path.read_text(encoding='utf-8')
    pattern = re.compile(re.escape(STATIC_BEGIN) + r'.*?' + re.escape(STATIC_END), re.DOTALL)
    block = render_static_block(entries)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text)
    # First run: insert inside the #app div
    marker = '<div id="app" style="min-height:100vh;">'
    if marker in text:
        return text.replace(marker, marker + '\n' + block + '\n')
    return None


# ── Driver ────────────────────────────────────────────────────────────────────

def _write_if_changed(path: Path, content: str, changed: list[str], root: Path) -> None:
    old = path.read_text(encoding='utf-8') if path.exists() else None
    if old != content:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        changed.append(str(path.relative_to(root)))


def generate(root: Path | str = SCRIPT_DIR) -> list[str]:
    """Regenerate all GEO artifacts. Returns repo-relative paths of files that changed."""
    root = Path(root)
    data = json.loads((root / 'learnings.json').read_text(encoding='utf-8'))
    entries = prepare(data)
    if not entries:
        return []

    changed: list[str] = []
    for i, e in enumerate(entries):
        prev_e = entries[i - 1] if i > 0 else None
        next_e = entries[i + 1] if i < len(entries) - 1 else None
        _write_if_changed(root / e['_file'], render_entry_page(e, prev_e, next_e), changed, root)

    _write_if_changed(root / 'entries' / 'index.html', render_entries_index(entries), changed, root)
    _write_if_changed(root / 'llms.txt', render_llms_txt(entries), changed, root)
    _write_if_changed(root / 'llms-full.txt', render_llms_full(entries), changed, root)
    _write_if_changed(root / 'feed.xml', render_feed(entries), changed, root)
    _write_if_changed(root / 'sitemap.xml', render_sitemap(entries), changed, root)

    new_index = update_index_html(root, entries)
    if new_index is not None:
        _write_if_changed(root / 'index.html', new_index, changed, root)

    return changed


if __name__ == '__main__':
    changed = generate(SCRIPT_DIR)
    if changed:
        print(f"✅  {len(changed)} file(s) regenerated:")
        for f in changed:
            print(f"   • {f}")
    else:
        print("✅  All GEO files already up to date.")
