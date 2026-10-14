#!/usr/bin/env python3
"""
Static site generator for varunsingla.com (GEO + reader pages).

Most AI crawlers (GPTBot, ClaudeBot, PerplexityBot, …) do not execute
JavaScript, and readers deserve fast, linkable pages, so everything that can
be static is rendered from learnings.json by this script:

  entries/<date>.html   one page per journal entry (+ JSON-LD, sources,
                        related entries, self-test, PDF download)
  entries/index.html    crawlable archive of all entries (theme filter)
  playbook/index.html   every practical takeaway, filterable by theme
  concepts/index.html   "the concept, explained simply" glossary
  watching/index.html   the TOMORROW / "what we're watching" tracker
  start/index.html      start here: how the journal works + learning paths
  weekly/*.html         one digest per ISO week (+ index)
  review/index.html     flashcards built from takeaways, concepts and quizzes
  index.json            light index the home page renders from (no 2 MB fetch)
  search.json           compact full-text index, loaded only when searching
  llms.txt / llms-full.txt / feed.xml / sitemap.xml
  index.html            refreshes the static-fallback block, the shared CSS,
                        masthead/footer and the data-version meta tag between
                        GEO markers (crawler/no-JS content + cache busting)

Run standalone (`python3 generate_geo.py`) or via update_site.py, which calls
generate() after each daily content update and pushes whatever changed.
Files are only rewritten when their content changes, so the returned list is
exactly what needs pushing.
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

SITE = "https://varunsingla.com"
AUTHOR = "Varun Singla"
BLOG_NAME = "Varun Singla · AI Learning Journal"
ACCENT = "#CC3F2A"
TZ = timezone(timedelta(hours=8))  # Singapore
FEED_SIZE = 20

SCRIPT_DIR = Path(__file__).parent

# ── Themes ────────────────────────────────────────────────────────────────────
# An entry's themes come from an explicit "Themes:" line in the PDF when one
# exists (entry['themes']); otherwise from keyword scoring over the title,
# subtitle, headings and body. The home page reads the result from index.json,
# so this is the single place the classification lives.
THEMES = ['Foundations & Protocols', 'Industry Verticals', 'Enterprise & Strategy',
          'Infrastructure & Economics', 'Models & Frontier', 'Governance & Safety']
RULES = {
    'Industry Verticals': ['healthcare', 'life science', 'clinical', 'hospital', 'pharma', 'telecom', 'network', 'insurance', 'underwriting', 'financial service', 'fp&a', ' finance', 'banking', 'wall street', 'manufacturing', 'industrial', 'supply chain', 'retail', 'e-commerce', 'ecommerce', 'legal', 'contract', ' hr ', 'people operation', 'education', 'edtech', 'marketing', 'customer success', ' customer', 'sales &', 'revenue operation', ' media', 'entertainment', 'energy & climate', 'energy &', 'scientific research', 'public sector', 'govtech', 'real estate', 'proptech', 'in financial', 'vertical', 'construction', 'automotive', 'robotaxi', 'agriculture', 'logistics', 'travel', 'hospitality', 'wet lab', 'math proof', 'theorem'],
    'Infrastructure & Economics': ['data centre', 'data center', 'data-centre', 'power wall', 'cooling', 'water wall', 'inference econom', 'compute map', 'sovereign ai', 'hyperscaler', 'capex', 'tokenomic', 'token economic', ' gpu', 'chip', 'silicon', 'power &', 'pricing', 'price war', 'half-price', 'cheaper', 'valuation', 'ipo', 'billion', 'revenue', 'tpu', 'nvidia', 'power grid', 'turbine', 'electricity', 'inference', 'cost'],
    'Governance & Safety': ['safety', 'governance', 'eu ai act', 'ai act', 'regulat', 'compliance', 'agent identity', 'identity 3.0', 'identity 2.0', 'spiffe', 'know your agent', ' kya', 'red team', 'red-team', 'fair-housing', 'liability', 'sandbox', 'breach', 'hack', 'rogue', 'probe', 'ftc', 'ban ', 'binding rules', 'watermark', 'self-replicat', 'incident', 'misalign', 'cyber', 'security', 'guardrail', 'lawsuit', 'sued', 'court', 'congress', 'white house', 'president', 'un security', 'policy', 'off switch', 'kill switch', 'teen-safety', 'transparency'],
    'Models & Frontier': ['frontier', 'model wars', 'open weight', 'open-weight', 'open-source', 'open source', 'multimodal', 'multi-modal', 'voice stack', 'gemini', 'mythos', 'vla', 'humanoid', 'robot', 'model race', 'reasoning model', 'quantiz', 'google i/o', 'i/o 2026', 'physical ai', 'gpt-', 'claude opus', 'claude sonnet', 'haiku', 'opus 5', 'deepseek', 'qwen', 'mistral', 'llama', 'grok', 'kimi', 'glm-', 'muse', 'astra', 'argon', 'benchmark', 'mixture-of-experts', 'moe', 'model router', 'new model', 'ships gpt', 'releases'],
    'Enterprise & Strategy': ['enterprise', 'coe', 'center of excellence', 'centre of excellence', ' roi', 'procurement', 'operating model', 'buyer', 'org chart', 'finops', 'moat', 'go-to-market', 'take rate', 'control plane', 'future of work', 'career', 'roles', 'cfo', 'cio', 'business case', 'adoption', 'scorecard', 'app store', 'skills economy', 'marketplace', 'agent economy', 'competitive', 'copilot', 'salesforce', 'microsoft', 'workspace', 'executives', 'payoff', 'super-app', 'productivity', 'workforce', 'pilots to production', 'agent fleets', 'cowork'],
    'Foundations & Protocols': ['mcp', 'model context protocol', 'a2a', 'agent-to-agent', 'protocol', 'memory', 'orchestrat', 'agentic rag', ' rag', 'observability', 'reliability', 'eval', 'testing', 'multi-agent', 'multi agent', 'communication', 'agent pattern', 'first agent', 'first ai agent', 'first production', 'tool optim', 'tool use', 'tool-use', 'interop', 'skill.md', 'building your', 'microservices', 'agent skill', 'data infrastructure', 'browser', 'debugging', 'routing', 'harness', 'agentic ai', 'agents', 'coding agent', 'self-improving', 'world model', 'formal verification', 'reverse engineer', 'open-source agent', 'self-healing', 'circuit breaker'],
}

STOP = set("""a an and are as at be by for from has have in into is it its of on or that the this to was were with will your you
we our their they them he she his her not no but if then than so such via per vs about after before over under between
how why what when where which who whom while just more most less new now today tomorrow week day days series stories story
three two one four five first last same own every still against inside outside like only also both each other any all""".split())

# ── Learning paths (curated; dates are validated against the data) ───────────
PATHS = [
    ("Agentic AI foundations", "What an agent is, why the industry moved from answering to acting, and how to build a first one.",
     ["2026-03-16", "2026-03-15", "2026-03-18", "2026-03-29", "2026-03-30", "2026-04-13"]),
    ("Protocols: MCP, A2A and interop", "The plumbing that lets agents use tools and talk to each other.",
     ["2026-03-22", "2026-03-23", "2026-04-08", "2026-06-20", "2026-05-18", "2026-05-23"]),
    ("Memory, orchestration and multi-agent systems", "How agents remember, coordinate and improve without retraining.",
     ["2026-03-19", "2026-04-04", "2026-04-05", "2026-05-06", "2026-05-04", "2026-07-08", "2026-07-09"]),
    ("Evals, reliability and observability", "Testing, red-teaming and watching agents in production.",
     ["2026-04-02", "2026-04-11", "2026-04-12", "2026-05-07", "2026-05-11", "2026-05-12"]),
    ("Economics: tokens, routing, inference and compute", "What agents cost, where the money goes, and the physical limits underneath.",
     ["2026-05-05", "2026-06-17", "2026-06-19", "2026-06-21", "2026-06-22", "2026-06-23", "2026-07-22", "2026-10-03"]),
    ("Security, identity, safety and governance", "Who an agent is allowed to be, what it may touch, and who gets to say so.",
     ["2026-03-27", "2026-04-10", "2026-05-16", "2026-06-15", "2026-07-21", "2026-08-23", "2026-10-04", "2026-10-11", "2026-10-14"]),
    ("Enterprise adoption and strategy", "Operating models, buying decisions and org design for agent-first companies.",
     ["2026-04-01", "2026-04-22", "2026-05-09", "2026-05-15", "2026-06-16", "2026-06-18", "2026-08-06"]),
    ("Industry deep dives", "Where agents are landing first, sector by sector.",
     ["2026-05-26", "2026-05-27", "2026-05-28", "2026-06-04", "2026-06-05", "2026-06-08", "2026-06-26", "2026-07-10"]),
    ("The frontier model race", "Model launches, open weights and pricing moves, as they happened.",
     ["2026-04-16", "2026-06-24", "2026-07-05", "2026-07-15", "2026-07-16", "2026-07-17", "2026-09-05", "2026-10-07", "2026-10-13"]),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def esc(s) -> str:
    return html.escape(str(s), quote=True) if s is not None else ''


def norm(s: str) -> str:
    return re.sub(r'\W+', ' ', (s or '').lower()).strip()


def first_sentences(text: str, max_len: int = 220) -> str:
    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    stop = max(cut.rfind('. '), cut.rfind('? '), cut.rfind('! '))
    if stop > max_len * 0.45:
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


def short_date(iso: str) -> str:
    d = datetime.strptime(iso[:10], '%Y-%m-%d')
    return f"{d.strftime('%b')} {d.day}"


def rfc822(iso: str) -> str:
    d = datetime.strptime(iso[:10], '%Y-%m-%d').replace(hour=21, tzinfo=TZ)
    return d.strftime('%a, %d %b %Y %H:%M:%S %z')


def split_heading(title: str) -> tuple[str, str]:
    """'3) China's AI Chip Market' -> ('3', "China's AI Chip Market")."""
    m = re.match(r"^\s*(\d{1,2})\s*[).:·\-—–]+\s*(.+)$", title or '')
    if m:
        return m.group(1), m.group(2).strip()
    return '', (title or '').strip()


def body_text(e: dict) -> str:
    parts = [e.get('focus_intro') or '', e.get('market_signal') or '']
    for s in e.get('sections') or []:
        parts.extend(s.get('paragraphs') or [])
        parts.extend(s.get('bullets') or [])
    return ' '.join(parts)


def keywords(text: str, min_len: int = 4) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9'\-]+", (text or '').lower())
            if len(w) >= min_len and w not in STOP}


def classify(e: dict) -> list[str]:
    explicit = [t for t in (e.get('themes') or []) if t in THEMES]
    if explicit:
        return explicit[:2]
    t = (e.get('title') or '').lower()
    sub = (e.get('subtitle') or '').lower()
    heads = ' '.join(s.get('title') or '' for s in e.get('sections') or []).lower()
    body = body_text(e).lower()
    score = {k: 0.0 for k in THEMES}
    for th, kws in RULES.items():
        body_hits = 0.0
        for k in kws:
            if k in t:
                score[th] += 3
            if k in sub:
                score[th] += 2
            if k in heads:
                score[th] += 1
            c = body.count(k)
            if c:
                body_hits += min(c, 3) * 0.4
        score[th] += min(body_hits, 3.0)
    ranked = sorted(THEMES, key=lambda k: (-score[k], THEMES.index(k)))
    chosen = [k for k in ranked if score[k] >= 2][:2]
    if not chosen:
        chosen = [ranked[0]] if score[ranked[0]] > 0 else ['Foundations & Protocols']
    if score['Industry Verticals'] >= 3 and 'Industry Verticals' not in chosen:
        chosen = ['Industry Verticals'] + chosen[:1]
    return chosen


def display_subtitle(e: dict) -> str:
    """Deck line for cards. When the deck starts with the title (Day 184+ PDFs
    name every story in one line), show the remainder so title + deck don't
    repeat each other."""
    sub = (e.get('subtitle') or '').strip()
    title = (e.get('title') or '').strip()
    if not sub:
        return ''
    ns, nt = norm(sub), norm(title)
    if nt and ns.startswith(nt) and len(ns) > len(nt) + 8:
        # find the cut in the raw string: walk the subtitle until the normalised prefix is consumed
        i, consumed = 0, ''
        while i < len(sub) and consumed != nt:
            consumed = norm(sub[:i + 1])
            i += 1
        rest = sub[i:].lstrip(' ,;:-—–)]}').strip()
        if rest:
            return rest[:1].upper() + rest[1:]
        return ''
    if ns == nt:
        return ''
    return sub


_CONCEPT_RE = re.compile(r"the concept,?\s*(?:explained\s+)?simply\s*[:\-—–]\s*", re.I)


def extract_concepts(e: dict) -> list[dict]:
    out = []
    for s in e.get('sections') or []:
        _, heading = split_heading(s.get('title') or '')
        for p in s.get('paragraphs') or []:
            m = _CONCEPT_RE.search(p)
            if not m:
                continue
            text = p[m.end():].strip()
            why = ''
            wm = re.search(r"\bwhy it matters\s*[:\-—–]\s*", text, re.I)
            if wm:
                why = text[wm.end():].strip()
                text = text[:wm.start()].strip()
            if len(text) < 40:
                continue
            out.append({'term': heading or e.get('title', ''), 'text': text[:900], 'why': why[:500]})
    return out


_PHRASE_RE = re.compile(r"(?:(?:[A-Z][\w'’.\-]*|GPT-\d[\w.]*|[A-Z]{2,}\d*)(?:\s+(?:[A-Z][\w'’.\-]*|\d[\d.]*[A-Za-z]*|GPT-\d[\w.]*)){0,3})")
_PHRASE_STOP = {'whether', 'what', 'we', 'the', 'watching', 'day', 'tomorrow', 'plus', 'on', 'two', 'three', 'i', 'a', 'in',
                'if', 'how', 'and', 'also', 'next', 'separately', 'meanwhile', 'this', 'that', 'there', 'then', 'it', 'its',
                'our', 'as', 'at', 'by', 'for', 'from', 'of', 'or', 'to', 'with', 'us', 'ai', 'who', 'when', 'where', 'now',
                'first', 'second', 'third', 'one', 'new', 'more', 'most', 'both', 'all', 'any', 'each', 'but', 'so', 'yet',
                'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'january', 'february', 'march',
                'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december', 'q1', 'q2', 'q3', 'q4'}


def key_phrases(text: str) -> list[str]:
    seen, out = set(), []
    for m in _PHRASE_RE.finditer(text or ''):
        ph = m.group(0).strip(" .,;:'\"")
        words = ph.split()
        words = [w for w in words if w.lower().strip("'’.") not in _PHRASE_STOP or any(ch.isdigit() for ch in w)]
        ph = ' '.join(words)
        if not ph:
            continue
        low = ph.lower()
        if low in seen or low in _PHRASE_STOP:
            continue
        if len(ph) < 5 and not any(ch.isdigit() for ch in ph):
            continue
        if len(words) == 1 and words[0].lower() in {'anthropic', 'openai', 'google', 'microsoft', 'meta', 'apple', 'nvidia',
                                                   'amazon', 'claude', 'chatgpt', 'gemini', 'washington', 'china', 'congress'}:
            continue  # too generic to prove a follow-up on its own
        seen.add(low)
        out.append(ph)
    return out[:12]


def iso_week(iso: str) -> str:
    d = datetime.strptime(iso[:10], '%Y-%m-%d').date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_bounds(key: str) -> tuple[str, str]:
    y, w = key.split('-W')
    start = datetime.strptime(f'{y}-W{int(w)}-1', '%G-W%V-%u').date()
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


# ── Prepare entries ───────────────────────────────────────────────────────────

def _pdf_lookup(root: Path) -> dict[str, str]:
    found = {}
    for p in sorted(root.glob('AI_Learning_Day*_*.pdf')):
        m = re.search(r'_(\d{4}-\d{2}-\d{2})\.pdf$', p.name)
        if m:
            found.setdefault(m.group(1), p.name)
    return found


def prepare(data: dict, root: Path | None = None) -> list[dict]:
    """Filter, sort ascending, and annotate entries with derived fields."""
    root = Path(root) if root else SCRIPT_DIR
    pdfs = _pdf_lookup(root)
    entries = [e for e in data.get('learnings', []) if e.get('title') and str(e['title']).strip()]
    entries.sort(key=lambda e: str(e['date']))
    for i, e in enumerate(entries):
        e['_day'] = i + 1
        e['_tags'] = classify(e)
        e['_words'] = word_count(e)
        e['_read'] = max(3, round(e['_words'] / 210))
        e['_sub'] = display_subtitle(e)
        intro = e.get('focus_intro') or ''
        if not intro and e.get('sections'):
            paras = e['sections'][0].get('paragraphs') or []
            intro = paras[0] if paras else ''
        e['_intro'] = intro
        e['_excerpt'] = first_sentences(e['_sub'] or intro, 220) if (e['_sub'] or intro) else ''
        e['_file'] = f"entries/{e['date']}.html"
        e['_url'] = f"{SITE}/entries/{e['date']}.html"
        e['_pdf'] = pdfs.get(e['date'], '')
        e['_concepts'] = extract_concepts(e)
        e['_week'] = iso_week(e['date'])
        e['_kw'] = keywords(e['title'] + ' ' + (e.get('subtitle') or ''))
        e['_hkw'] = keywords(' '.join(s.get('title') or '' for s in e.get('sections') or []))
        tk = e.get('practical_takeaway')
        e['_takeaways'] = [t for t in tk if isinstance(t, dict) and (t.get('title') or t.get('body'))] if isinstance(tk, list) \
            else ([{'title': '', 'body': tk}] if isinstance(tk, str) and tk.strip() else [])
    # Related entries: shared themes + shared title/heading keywords.
    for e in entries:
        scored = []
        for o in entries:
            if o is e:
                continue
            s = 2 * len(set(e['_tags']) & set(o['_tags'])) + 2 * len(e['_kw'] & o['_kw']) \
                + 0.5 * len(e['_hkw'] & o['_hkw']) + 0.5 * len(e['_kw'] & o['_hkw'])
            if s >= 3:
                scored.append((s, o['date'], o))
        scored.sort(key=lambda x: (-x[0], x[1]))
        e['_related'] = [o for _, _, o in scored[:3]]
    # Watch list follow-ups: does a later entry pick up a named thing?
    by_date = {e['date']: e for e in entries}
    for e in entries:
        e['_followups'] = []
        tp = e.get('tomorrow_preview') or ''
        if not tp:
            continue
        phrases = key_phrases(tp)
        later = [o for o in entries if o['date'] > e['date']][:45]
        hits: list[tuple[str, dict]] = []
        for ph in phrases:
            low = ph.lower()
            for o in later:
                hay = (o['title'] + ' ' + (o.get('subtitle') or '') + ' ' +
                       ' '.join(s.get('title') or '' for s in o.get('sections') or [])).lower()
                if low in hay:
                    if all(h[1] is not o for h in hits):
                        hits.append((ph, o))
                    break
            if len(hits) >= 2:
                break
        e['_followups'] = hits
    return entries


def site_stats(entries: list[dict]) -> dict:
    dates = [datetime.strptime(e['date'], '%Y-%m-%d').date() for e in entries]
    cur = best = 1
    for i in range(1, len(dates)):
        cur = cur + 1 if (dates[i] - dates[i - 1]).days == 1 else 1
        best = max(best, cur)
    return {
        'entries': len(entries),
        'words': sum(e['_words'] for e in entries),
        'started': entries[0]['date'] if entries else '',
        'latest': entries[-1]['date'] if entries else '',
        'streak': cur if entries else 0,
        'longest_streak': best if entries else 0,
        'takeaways': sum(len(e['_takeaways']) for e in entries),
        'concepts': sum(len(e['_concepts']) for e in entries),
        'themes': {t: sum(1 for e in entries if t in e['_tags']) for t in THEMES},
    }


# ── Shared chrome ─────────────────────────────────────────────────────────────

SITE_CSS = """
:root{--bg:#F7F4ED;--surface:#FBF9F3;--surface2:#F3ECDD;--border:#E4DECF;--border-soft:#EEE9DC;--border-strong:#CBB8A0;
--text:#1B1A17;--text2:#2C2A24;--muted:#56524B;--muted2:#6B6760;--faint:#726D63;--faintest:#8A857B;
--accent:#CC3F2A;--accent-dark:#A83120;--accent-tint:#F4E7E2;--shadow:rgba(27,26,23,.4);
--serif:'Newsreader',Georgia,serif;--sans:'Hanken Grotesk',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;--mono:'JetBrains Mono',ui-monospace,Menlo,monospace;color-scheme:light;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161512;--surface:#1E1C18;--surface2:#26231E;--border:#2F2B25;--border-soft:#2A2722;--border-strong:#4A443A;
--text:#EDE8DC;--text2:#DCD6C8;--muted:#B5AE9F;--muted2:#A39C8D;--faint:#8F887A;--faintest:#7A746A;--accent:#E25A45;--accent-dark:#CC3F2A;--accent-tint:#3A241F;--shadow:rgba(0,0,0,.6);color-scheme:dark;}}
:root[data-theme="dark"]{--bg:#161512;--surface:#1E1C18;--surface2:#26231E;--border:#2F2B25;--border-soft:#2A2722;--border-strong:#4A443A;
--text:#EDE8DC;--text2:#DCD6C8;--muted:#B5AE9F;--muted2:#A39C8D;--faint:#8F887A;--faintest:#7A746A;--accent:#E25A45;--accent-dark:#CC3F2A;--accent-tint:#3A241F;--shadow:rgba(0,0,0,.6);color-scheme:dark;}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;background:var(--bg);}
body{font-family:var(--sans);color:var(--text);-webkit-font-smoothing:antialiased;line-height:1.5;}
::selection{background:var(--accent);color:#fff;}
a{color:inherit;}
img{max-width:100%;}
.skip{position:absolute;left:-999px;top:8px;background:var(--text);color:var(--bg);padding:8px 14px;border-radius:8px;z-index:100;}
.skip:focus{left:12px;}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px;}
@media (min-width:640px){.wrap{padding:0 28px;}}
.mast{position:sticky;top:0;z-index:50;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:saturate(140%) blur(12px);-webkit-backdrop-filter:saturate(140%) blur(12px);border-bottom:1px solid var(--border);}
.mast-in{max-width:1120px;margin:0 auto;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;}
@media (min-width:640px){.mast-in{padding:14px 28px;}}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;flex-shrink:0;}
.brand-mark{width:30px;height:30px;border-radius:7px;background:var(--text);color:var(--bg);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;letter-spacing:.02em;}
.brand-name{font-family:var(--mono);font-size:13.5px;color:var(--text);}
.nav{display:flex;align-items:center;gap:2px;flex-wrap:wrap;}
.nav-link{font-size:14px;font-weight:500;color:var(--muted2);text-decoration:none;padding:7px 10px;border-radius:8px;transition:.18s ease;white-space:nowrap;}
.nav-link:hover{color:var(--text);background:var(--surface2);}
.nav-link.active{font-weight:600;color:var(--text);}
.menu-btn,.theme-btn{border:1px solid var(--border);background:var(--surface);color:var(--muted2);border-radius:8px;cursor:pointer;font-family:var(--mono);font-size:12px;padding:7px 10px;line-height:1;}
.menu-btn:hover,.theme-btn:hover{color:var(--text);border-color:var(--border-strong);}
.menu-btn{display:none;}
.mast-right{display:flex;align-items:center;gap:8px;}
@media (max-width:880px){
  .menu-btn{display:inline-flex;align-items:center;gap:6px;}
  .nav{display:none;position:absolute;left:0;right:0;top:100%;background:var(--bg);border-bottom:1px solid var(--border);padding:8px 12px 12px;flex-direction:column;align-items:stretch;gap:2px;box-shadow:0 20px 40px -24px var(--shadow);}
  .nav.open{display:flex;}
  .nav-link{padding:11px 10px;font-size:15px;}
}
.kicker{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:14px;}
.eyebrow{font-family:var(--mono);font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);}
.tag{font-family:var(--mono);font-size:11.5px;letter-spacing:.04em;color:var(--muted2);border:1px solid var(--border);border-radius:999px;padding:5px 12px;background:var(--surface);text-decoration:none;display:inline-block;}
.tag:hover{border-color:var(--text);color:var(--text);}
.chip{font-family:var(--mono);font-size:12px;letter-spacing:.02em;font-weight:500;padding:7px 13px;border-radius:999px;cursor:pointer;transition:all .18s ease;border:1px solid var(--border);background:transparent;color:var(--muted2);}
.chip:hover{border-color:var(--border-strong);color:var(--text);}
.chip.active{border:1px solid var(--text);background:var(--text);color:var(--bg);}
.chips{display:flex;gap:8px;flex-wrap:wrap;}
.card{border:1px solid var(--border);border-radius:14px;background:var(--surface);padding:20px 22px;}
.card-link{display:block;text-decoration:none;transition:border-color .2s ease,transform .2s ease,box-shadow .25s ease;}
.card-link:hover{border-color:var(--border-strong);transform:translateY(-2px);box-shadow:0 18px 40px -28px var(--shadow);}
.callout{border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:12px;background:var(--surface);padding:22px 24px;margin:0 0 40px;}
.callout p{font-size:clamp(17px,2.2vw,19px);margin:0;}
.meta-row{display:flex;align-items:center;gap:13px;flex-wrap:wrap;font-family:var(--mono);font-size:13px;color:var(--faint);}
.meta-row .day{color:var(--accent);font-weight:500;}
.page-h1{font-family:var(--serif);font-weight:400;font-size:clamp(34px,5vw,54px);letter-spacing:-.018em;line-height:1.05;margin:0 0 16px;}
.lede{font-size:clamp(16px,2vw,18px);line-height:1.6;color:var(--muted);max-width:62ch;margin:0 0 36px;}
.section-h2{font-family:var(--serif);font-weight:500;font-size:clamp(22px,3vw,28px);border-bottom:1px solid var(--border);padding-bottom:12px;margin:0 0 22px;}
.filter-input{width:100%;max-width:420px;font-family:var(--sans);font-size:15px;padding:11px 14px;border:1px solid var(--border);border-radius:10px;background:var(--surface);color:var(--text);}
.filter-input:focus{outline:2px solid var(--accent);outline-offset:1px;}
article h1{font-family:var(--serif);font-weight:400;font-size:clamp(32px,5.5vw,52px);line-height:1.07;letter-spacing:-.018em;margin:0 0 16px;}
article h2{font-family:var(--serif);font-weight:500;font-size:clamp(23px,3.4vw,30px);line-height:1.18;margin:0 0 18px;}
article h2 .num{font-family:var(--mono);font-size:13px;letter-spacing:.1em;color:var(--accent);display:block;margin-bottom:6px;}
article p{font-family:var(--serif);font-size:clamp(18px,2.3vw,20px);line-height:1.65;color:var(--text2);margin:0 0 20px;}
article ul{margin:4px 0 20px;padding-left:20px;}
article li{font-family:var(--serif);font-size:clamp(17px,2.2vw,19px);line-height:1.6;color:var(--text2);margin:0 0 10px;}
.deck{font-family:var(--serif);font-size:clamp(19px,2.6vw,23px);line-height:1.45;color:var(--muted);margin:0 0 22px;letter-spacing:-.005em;}
.intro{font-size:clamp(19px,2.6vw,22px)!important;line-height:1.55!important;color:var(--text2)!important;font-style:italic;margin:0 0 36px!important;}
.highlight{font-family:var(--serif);font-style:italic;font-size:clamp(18px,2.4vw,20px);line-height:1.55;color:var(--text2);border-left:3px solid var(--accent);padding:6px 0 6px 16px;margin:8px 0 20px;}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin:0 0 40px;}
.stat-cell{background:var(--surface);padding:18px 20px;}
.stat-big{font-family:var(--serif);font-size:clamp(24px,4vw,32px);line-height:1.05;color:var(--text);}
.stat-small{font-size:13px;line-height:1.45;color:var(--muted);margin-top:8px;}
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--surface);margin:0 0 20px;}
table{width:100%;border-collapse:collapse;}
th{font-family:var(--mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);text-align:left;padding:9px 12px;border-bottom:1px solid var(--border-strong);font-weight:500;}
td{font-size:14.5px;color:var(--text2);padding:9px 12px;border-bottom:1px solid var(--border-soft);vertical-align:top;line-height:1.45;font-family:var(--sans);}
tr:last-child td{border-bottom:none;}
.tk-item{margin:0 0 14px;}
.tk-title{font-weight:600;font-size:15.5px;font-family:var(--sans);color:var(--text);}
.tk-body{font-family:var(--serif);font-size:17px;line-height:1.55;color:var(--text2);margin:3px 0 0;}
details.quiz{border:1px solid var(--border);border-radius:10px;background:var(--surface);padding:12px 16px;margin:0 0 10px;}
details.quiz summary{cursor:pointer;font-family:var(--sans);font-weight:600;font-size:15.5px;color:var(--text);}
details.quiz p{font-size:16.5px;margin:10px 0 0;}
.related{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:0 0 10px;}
.related a{border:1px solid var(--border);border-radius:12px;padding:16px 18px;background:var(--surface);text-decoration:none;display:block;}
.related a:hover{border-color:var(--text);}
.related .lbl{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin-bottom:8px;}
.related .ttl{font-family:var(--serif);font-size:17px;line-height:1.25;color:var(--text);}
.pn{display:grid;grid-template-columns:1fr 1fr;gap:14px;max-width:680px;margin:0 auto;padding:20px 20px 90px;}
.pn a{border:1px solid var(--border);border-radius:12px;padding:18px 20px;background:var(--surface);text-decoration:none;display:block;}
.pn a:hover{border-color:var(--text);}
.pn .lbl{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);margin-bottom:9px;}
.pn .ttl{font-family:var(--serif);font-size:18px;line-height:1.2;color:var(--text);}
.sources{font-size:14.5px;line-height:1.55;color:var(--muted);border-top:1px solid var(--border);padding-top:18px;margin:0 0 30px;}
.sources a{color:var(--accent);}
.entry-list{list-style:none;margin:0;padding:0;}
.entry-list li{margin:0 0 18px;}
.entry-list a{text-decoration:none;display:block;}
.entry-list .d{font-family:var(--mono);font-size:12.5px;color:var(--accent);}
.entry-list .t{display:block;font-family:var(--serif);font-size:clamp(19px,2.6vw,23px);line-height:1.25;color:var(--text);margin:4px 0 3px;}
.entry-list .s{display:block;font-size:15px;line-height:1.5;color:var(--muted);}
.entry-list a:hover .t{color:var(--accent);}
footer.foot{border-top:1px solid var(--border);background:var(--surface);margin-top:40px;}
.foot-in{max-width:1120px;margin:0 auto;padding:30px 20px;display:flex;align-items:flex-start;justify-content:space-between;gap:18px;flex-wrap:wrap;font-family:var(--mono);font-size:12.5px;color:var(--muted2);}
@media (min-width:640px){.foot-in{padding:34px 28px;}}
.foot-in a{text-decoration:none;color:var(--muted2);}
.foot-in a:hover{color:var(--text);}
.foot-links{display:flex;gap:14px;flex-wrap:wrap;}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;}}
"""

SITE_JS = """
(function(){
  try{var t=localStorage.getItem('vs-theme');if(t==='dark'||t==='light'){document.documentElement.setAttribute('data-theme',t);}}catch(e){}
  function ready(fn){if(document.readyState!=='loading'){fn();}else{document.addEventListener('DOMContentLoaded',fn);}}
  ready(function(){
    var btn=document.querySelector('.menu-btn'),nav=document.querySelector('.nav');
    if(btn&&nav){btn.addEventListener('click',function(){var open=nav.classList.toggle('open');btn.setAttribute('aria-expanded',open?'true':'false');});}
    var tb=document.querySelector('.theme-btn');
    if(tb){tb.addEventListener('click',function(){
      var cur=document.documentElement.getAttribute('data-theme');
      var sysDark=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches;
      var isDark=cur?cur==='dark':sysDark;
      var next=isDark?'light':'dark';
      document.documentElement.setAttribute('data-theme',next);
      try{localStorage.setItem('vs-theme',next);}catch(e){}
    });}
  });
})();
"""

FAVICON = ('<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 64 64%27%3E'
           '%3Crect width=%2764%27 height=%2764%27 rx=%2714%27 fill=%27%231B1A17%27/%3E%3Ctext x=%2732%27 y=%2742%27 '
           'font-family=%27Helvetica,Arial,sans-serif%27 font-size=%2728%27 font-weight=%27700%27 fill=%27%23F7F4ED%27 '
           'text-anchor=%27middle%27%3EVS%3C/text%3E%3C/svg%3E">')

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '<link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700'
         '&family=JetBrains+Mono:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,200..600;'
         '1,6..72,200..500&display=swap" rel="stylesheet">')

NAV_ITEMS = [('Journal', '/'), ('Archive', '/entries/'), ('Playbook', '/playbook/'), ('Concepts', '/concepts/'),
             ('Watching', '/watching/'), ('Review', '/review/'), ('Start Here', '/start/'), ('About', '/about/')]


def masthead(active: str = '') -> str:
    links = ''
    for label, href in NAV_ITEMS:
        cls = ' active' if label == active else ''
        cur = ' aria-current="page"' if label == active else ''
        links += f'<a class="nav-link{cls}" href="{href}"{cur}>{label}</a>'
    return f"""<a class="skip" href="#main">Skip to content</a>
<header class="mast"><div class="mast-in">
  <a class="brand" href="/"><span class="brand-mark" aria-hidden="true">VS</span><span class="brand-name">varunsingla.com</span></a>
  <div class="mast-right">
    <nav class="nav" aria-label="Site">{links}</nav>
    <button class="theme-btn" type="button" aria-label="Toggle dark mode" title="Toggle dark mode">◐</button>
    <button class="menu-btn" type="button" aria-expanded="false" aria-controls="nav" aria-label="Open menu">Menu ☰</button>
  </div>
</div></header>"""


def page_footer() -> str:
    return f"""<footer class="foot"><div class="foot-in">
  <div><span class="brand-mark" style="display:inline-flex;width:26px;height:26px;font-size:11px;border-radius:6px;vertical-align:middle;margin-right:8px;">VS</span>{AUTHOR} · Singapore · Learning in public</div>
  <div class="foot-links">
    <a href="/weekly/">Weekly digest</a><a href="/tokenizer.html">Tokenizer</a><a href="/ai-tokenomics/">Tokenomics</a>
    <a href="/tools/model-team-evaluator.html">Model Evaluator</a><a href="{SITE}/feed.xml">RSS</a><a href="{SITE}/llms.txt">llms.txt</a>
  </div>
  <div>Updated daily · © 2026</div>
</div></footer>
<script>{SITE_JS}</script>"""


def page_shell(*, title: str, description: str, canonical: str, body: str, active: str = '',
               jsonld: str = '', extra_head: str = '', extra_css: str = '', og_type: str = 'website') -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="author" content="{AUTHOR}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
<link rel="canonical" href="{canonical}">
<link rel="alternate" type="application/rss+xml" title="{esc(BLOG_NAME)}" href="{SITE}/feed.xml">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="{esc(BLOG_NAME)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(description)}">
<meta name="twitter:image" content="{SITE}/og-image.png">
{extra_head}{FAVICON}
{FONTS}
{jsonld}
<style>{SITE_CSS}{extra_css}</style>
</head>
<body>
{masthead(active)}
{body}
{page_footer()}
</body>
</html>
"""


def linkify(text: str) -> str:
    """Escape, then turn bare URLs into links."""
    out = esc(text)
    return re.sub(r'(https?://[^\s<>"\')]+)', r'<a href="\1" rel="nofollow noopener">\1</a>', out)


# ── Entry page ────────────────────────────────────────────────────────────────

def render_section(sec: dict) -> str:
    out = []
    num, heading = split_heading(sec.get('title') or '')
    if heading:
        num_html = f'<span class="num">Part {esc(num)}</span>' if num else ''
        out.append(f'<h2>{num_html}{esc(heading)}</h2>')
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


def render_takeaways(e: dict) -> str:
    tks = e['_takeaways']
    if not tks:
        return ''
    items = []
    for t in tks:
        title, body = (t.get('title') or '').strip(), (t.get('body') or '').strip()
        inner = f'<div class="tk-title">{esc(title)}</div>' if title else ''
        if body and body != title:
            inner += f'<p class="tk-body">{esc(body)}</p>'
        items.append(f'<div class="tk-item">{inner}</div>')
    return f'<div class="callout"><div class="kicker">Practical takeaways</div>{"".join(items)}</div>'


def render_body_blocks(e: dict, for_feed: bool = False) -> str:
    """The article body (everything below the h1/meta), shared by the entry page and the RSS feed."""
    out = []
    intro = e.get('focus_intro') or ''
    if intro and norm(intro) != norm(e.get('title') or '') and norm(intro) != norm(e.get('subtitle') or ''):
        out.append(f'<p class="intro">{esc(intro)}</p>')

    v = e.get('viral_app') or {}
    if v.get('name'):
        inner = (f'<div class="kicker">Viral / open-source spotlight</div>'
                 f'<p style="font-family:var(--serif);font-size:22px;font-weight:500;margin:0 0 10px;">{esc(v["name"])}</p>')
        if v.get('description'):
            inner += f'<p>{esc(v["description"])}</p>'
        vstats = v.get('stats') or []
        if vstats:
            inner += '<ul style="margin-bottom:0;">' + ''.join(
                f'<li>{esc(s.get("stat", ""))} — {esc(s.get("label", ""))}</li>' for s in vstats) + '</ul>'
        out.append(f'<div class="callout">{inner}</div>')

    stats = e.get('stats') or []
    key_stats = e.get('key_stats') or []
    if stats or key_stats:
        if stats:
            cells = ''.join(f'<div class="stat-cell"><div class="stat-big">{esc(s.get("stat", ""))}</div>'
                            f'<div class="stat-small">{esc(s.get("label", ""))}</div></div>' for s in stats)
        else:
            cells = ''.join(f'<div class="stat-cell"><div class="stat-small" style="margin-top:0;font-family:var(--serif);font-size:15px;">{esc(s)}</div></div>' for s in key_stats)
        out.append(f'<div style="margin:0 0 40px;"><div class="kicker">By the numbers</div><div class="stat-grid">{cells}</div></div>')

    for sec in e.get('sections') or []:
        out.append(render_section(sec))

    if e.get('market_signal'):
        out.append(f'<div class="callout"><div class="kicker">Market signal</div><p>{esc(e["market_signal"])}</p></div>')

    out.append(render_takeaways(e))

    if e.get('quiz'):
        qs = ''.join(f'<details class="quiz"><summary>{esc(q.get("q", ""))}</summary><p>{esc(q.get("a", ""))}</p></details>'
                     for q in e['quiz'] if q.get('q'))
        out.append(f'<div style="margin:0 0 40px;"><div class="kicker">Self-test</div>{qs}</div>')

    if e.get('tomorrow_preview'):
        link = '' if for_feed else ' · <a href="/watching/" style="color:var(--accent);">tracker</a>'
        out.append(f'<div style="margin:0 0 30px;padding:18px 0 0;border-top:1px solid var(--border-soft);">'
                   f'<div class="eyebrow" style="margin-bottom:7px;">What we\'re watching{link}</div>'
                   f'<p style="font-style:italic;font-size:17px;line-height:1.55;color:var(--muted);margin:0;">{esc(e["tomorrow_preview"])}</p></div>')

    if e.get('sources'):
        out.append(f'<div class="sources"><strong>Sources.</strong> {linkify(e["sources"])}</div>')
    return '\n'.join(out)


def entry_jsonld(e: dict) -> str:
    post = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "@id": e['_url'] + "#post",
        "headline": e['title'],
        **({"alternativeHeadline": e['subtitle']} if e.get('subtitle') else {}),
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
    tags = ''.join(f'<a class="tag" href="/entries/?theme={esc(t)}">{esc(t)}</a> ' for t in e['_tags'])
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
    head_links += f'<meta property="article:published_time" content="{e["date"]}T21:00:00+08:00">\n'
    head_links += f'<meta property="article:author" content="{SITE}/about/">\n'
    head_links += ''.join(f'<meta property="article:tag" content="{esc(t)}">\n' for t in e['_tags'])

    deck = f'<p class="deck">{esc(e["_sub"])}</p>' if e['_sub'] else ''
    pdf = (f' · <a href="/{esc(e["_pdf"])}" style="color:var(--faint);">PDF</a>' if e['_pdf'] else '')
    related = ''
    if e['_related']:
        cards = ''.join(f'<a href="/entries/{r["date"]}.html"><div class="lbl">Day {r["_day"]} · {esc(short_date(r["date"]))}</div>'
                        f'<div class="ttl">{esc(r["title"])}</div></a>' for r in e['_related'])
        related = f'<div style="margin:44px 0 0;"><div class="kicker">Related entries</div><div class="related">{cards}</div></div>'

    body = f"""<main id="main">
<article style="max-width:680px;margin:0 auto;padding:40px 20px 30px;">
  <p style="margin:0 0 30px;"><a href="/entries/" style="font-family:var(--mono);font-size:12.5px;letter-spacing:.04em;color:var(--muted2);text-decoration:none;">← All entries</a></p>
  <div class="meta-row" style="margin-bottom:18px;">
    <span class="day">Day {e['_day']}</span><span aria-hidden="true">·</span>
    <time datetime="{e['date']}">{long_date(e['date'])}</time><span aria-hidden="true">·</span>
    <span>{e['_read']} min read{pdf}</span>
  </div>
  <h1>{esc(e['title'])}</h1>
  {deck}
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:34px;padding-bottom:30px;border-bottom:1px solid var(--border);">{tags}</div>
  {render_body_blocks(e)}
  {related}
  <div style="display:flex;align-items:center;gap:13px;margin:54px 0 10px;padding-top:30px;border-top:1px solid var(--border);">
    <div class="brand-mark" style="width:40px;height:40px;font-size:14px;border-radius:9px;">VS</div>
    <div><div style="font-size:14.5px;font-weight:600;">{AUTHOR}</div>
    <div style="font-family:var(--mono);font-size:12px;color:var(--faint);">Singapore · <a href="/about/" style="color:var(--faint);">About</a> · Learning in public</div></div>
  </div>
</article>
{pn}
</main>"""
    return page_shell(title=title, description=e['_excerpt'] or e['title'], canonical=e['_url'], body=body,
                      jsonld=entry_jsonld(e), extra_head=head_links, og_type='article')


# ── Archive ───────────────────────────────────────────────────────────────────

ARCHIVE_JS = """
(function(){
  var chips=document.querySelectorAll('.chip[data-theme]');var items=document.querySelectorAll('.entry-list li');var months=document.querySelectorAll('.month-group');
  function apply(theme){
    chips.forEach(function(c){c.classList.toggle('active',c.getAttribute('data-theme')===theme);c.setAttribute('aria-pressed',c.getAttribute('data-theme')===theme?'true':'false');});
    items.forEach(function(li){var ok=theme==='All'||(li.getAttribute('data-themes')||'').split('|').indexOf(theme)>=0;li.style.display=ok?'':'none';});
    months.forEach(function(m){var any=false;m.querySelectorAll('.entry-list li').forEach(function(li){if(li.style.display!=='none')any=true;});m.style.display=any?'':'none';});
    var c=document.getElementById('count');if(c){var n=0;items.forEach(function(li){if(li.style.display!=='none')n++;});c.textContent=n+' entr'+(n===1?'y':'ies');}
  }
  chips.forEach(function(c){c.addEventListener('click',function(){var t=c.getAttribute('data-theme');apply(t);try{history.replaceState(null,'',t==='All'?location.pathname:'?theme='+encodeURIComponent(t));}catch(e){}});});
  var q=new URLSearchParams(location.search).get('theme');apply(q&&document.querySelector('.chip[data-theme="'+q.replace(/"/g,'')+'"]')?q:'All');
})();
"""


def render_entries_index(entries: list[dict]) -> str:
    """Crawlable archive page listing every entry, newest first, grouped by month, with a theme filter."""
    newest = entries[-1]
    by_month: dict[str, list[dict]] = {}
    for e in reversed(entries):
        d = datetime.strptime(e['date'], '%Y-%m-%d')
        by_month.setdefault(d.strftime('%B %Y'), []).append(e)

    groups = []
    for month, es in by_month.items():
        items = ''.join(
            f'<li data-themes="{esc("|".join(e["_tags"]))}"><a href="{e["date"]}.html">'
            f'<span class="d">Day {e["_day"]} · <time datetime="{e["date"]}">{long_date(e["date"])}</time></span>'
            f'<span class="t">{esc(e["title"])}</span>'
            f'<span class="s">{esc(e["_sub"] or e["_excerpt"])}</span></a></li>'
            for e in es)
        groups.append(f'<section class="month-group" style="margin:0 0 44px;"><h2 class="section-h2">{month}</h2><ul class="entry-list">{items}</ul></section>')

    chips = ''.join(f'<button class="chip{" active" if t == "All" else ""}" type="button" data-theme="{esc(t)}" aria-pressed="{"true" if t == "All" else "false"}">{esc(t)}</button>'
                    for t in ['All'] + THEMES)
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
    body = f"""<main id="main" class="wrap" style="max-width:760px;padding-top:48px;padding-bottom:60px;">
  <h1 class="page-h1">The Archive</h1>
  <p class="lede">{esc(desc)}</p>
  <div class="chips" style="margin:0 0 10px;">{chips}</div>
  <p class="eyebrow" id="count" style="margin:0 0 34px;">{len(entries)} entries</p>
  {''.join(groups)}
</main>
<script>{ARCHIVE_JS}</script>"""
    return page_shell(title=f"All Entries — {BLOG_NAME}", description=desc, canonical=f"{SITE}/entries/", body=body,
                      active='Archive', jsonld=f'<script type="application/ld+json">{json.dumps(item_list, ensure_ascii=False)}</script>')


# ── Playbook ──────────────────────────────────────────────────────────────────

FILTER_JS = """
(function(){
  var chips=document.querySelectorAll('.chip[data-theme]');var blocks=document.querySelectorAll('[data-block]');var input=document.getElementById('q');var theme='All';
  function apply(){
    var q=(input&&input.value||'').trim().toLowerCase();var n=0;
    blocks.forEach(function(b){
      var okTheme=theme==='All'||(b.getAttribute('data-themes')||'').split('|').indexOf(theme)>=0;
      var okQ=!q||(b.getAttribute('data-text')||'').indexOf(q)>=0;
      var show=okTheme&&okQ;b.style.display=show?'':'none';if(show)n+=parseInt(b.getAttribute('data-n')||'1',10);
    });
    var c=document.getElementById('count');if(c)c.textContent=n+' '+(c.getAttribute('data-unit')||'items');
  }
  chips.forEach(function(c){c.addEventListener('click',function(){theme=c.getAttribute('data-theme');chips.forEach(function(x){x.classList.toggle('active',x===c);x.setAttribute('aria-pressed',x===c?'true':'false');});apply();});});
  if(input){input.addEventListener('input',apply);}
  var q=new URLSearchParams(location.search).get('theme');if(q){var c=document.querySelector('.chip[data-theme="'+q.replace(/"/g,'')+'"]');if(c)c.click();}
})();
"""


def theme_chips() -> str:
    return ''.join(f'<button class="chip{" active" if t == "All" else ""}" type="button" data-theme="{esc(t)}" aria-pressed="{"true" if t == "All" else "false"}">{esc(t)}</button>'
                   for t in ['All'] + THEMES)


def render_playbook(entries: list[dict], stats: dict) -> str:
    blocks = []
    for e in reversed(entries):
        if not e['_takeaways']:
            continue
        items = ''.join(
            f'<li><strong>{esc(t.get("title") or "")}</strong>'
            + (f' <span>{esc(t["body"])}</span>' if t.get('body') and t.get('body') != t.get('title') else '') + '</li>'
            for t in e['_takeaways'])
        text = norm(e['title'] + ' ' + ' '.join((t.get('title') or '') + ' ' + (t.get('body') or '') for t in e['_takeaways']))
        blocks.append(f"""<section class="card" data-block data-n="{len(e['_takeaways'])}" data-themes="{esc('|'.join(e['_tags']))}" data-text="{esc(text)}" style="margin:0 0 14px;">
  <div class="meta-row" style="margin-bottom:8px;"><span class="day">Day {e['_day']}</span><span aria-hidden="true">·</span><time datetime="{e['date']}">{long_date(e['date'])}</time><span aria-hidden="true">·</span><span>{esc(e['_tags'][0])}</span></div>
  <h2 style="font-family:var(--serif);font-weight:500;font-size:clamp(19px,2.6vw,23px);line-height:1.25;margin:0 0 12px;"><a href="/entries/{e['date']}.html" style="text-decoration:none;color:var(--text);">{esc(e['title'])}</a></h2>
  <ul class="pb-list">{items}</ul>
</section>""")
    desc = (f"Every practical takeaway from {AUTHOR}'s AI learning journal in one place: {stats['takeaways']} actions "
            f"from {sum(1 for e in entries if e['_takeaways'])} daily entries, filterable by theme.")
    body = f"""<main id="main" class="wrap" style="max-width:820px;padding-top:48px;padding-bottom:60px;">
  <h1 class="page-h1">The Playbook</h1>
  <p class="lede">{esc(desc)} Newest first. Each block links to the entry it came from.</p>
  <div class="chips" style="margin:0 0 14px;">{theme_chips()}</div>
  <input id="q" class="filter-input" type="search" placeholder="Filter takeaways… (e.g. memory, pricing, sandbox)" aria-label="Filter takeaways">
  <p class="eyebrow" id="count" data-unit="takeaways" style="margin:12px 0 28px;">{stats['takeaways']} takeaways</p>
  {''.join(blocks)}
</main>
<script>{FILTER_JS}</script>"""
    css = ".pb-list{margin:0;padding-left:18px;}.pb-list li{font-size:15.5px;line-height:1.5;color:var(--text2);margin:0 0 8px;}.pb-list strong{color:var(--text);}.pb-list span{color:var(--muted);}"
    return page_shell(title=f"Playbook — {BLOG_NAME}", description=desc, canonical=f"{SITE}/playbook/", body=body,
                      active='Playbook', extra_css=css)


# ── Concepts ──────────────────────────────────────────────────────────────────

def render_concepts(entries: list[dict], stats: dict) -> str:
    cards = []
    for e in reversed(entries):
        for c in e['_concepts']:
            why = f'<p style="margin:10px 0 0;font-size:15px;color:var(--muted);"><strong style="color:var(--text);">Why it matters.</strong> {esc(c["why"])}</p>' if c['why'] else ''
            cards.append(f"""<section class="card" data-block data-themes="{esc('|'.join(e['_tags']))}" data-text="{esc(norm(c['term'] + ' ' + c['text'] + ' ' + c['why']))}" style="margin:0 0 14px;">
  <div class="meta-row" style="margin-bottom:8px;"><span class="day">Day {e['_day']}</span><span aria-hidden="true">·</span><time datetime="{e['date']}">{long_date(e['date'])}</time></div>
  <h2 style="font-family:var(--serif);font-weight:500;font-size:clamp(19px,2.6vw,23px);line-height:1.25;margin:0 0 10px;">{esc(c['term'])}</h2>
  <p style="margin:0;font-size:16px;line-height:1.6;color:var(--text2);">{esc(c['text'])}</p>
  {why}
  <p style="margin:12px 0 0;"><a href="/entries/{e['date']}.html" style="font-family:var(--mono);font-size:12.5px;color:var(--accent);text-decoration:none;">Read the entry →</a></p>
</section>""")
    desc = (f"Plain-language explanations of the ideas behind the news — {stats['concepts']} concepts pulled from the "
            f"\"concept, explained simply\" passages in {AUTHOR}'s daily AI learning journal.")
    body = f"""<main id="main" class="wrap" style="max-width:820px;padding-top:48px;padding-bottom:60px;">
  <h1 class="page-h1">Concepts, explained simply</h1>
  <p class="lede">{esc(desc)} Newest first. For the full glossary of what the journal has covered, see <a href="/start/">Start here</a>.</p>
  <div class="chips" style="margin:0 0 14px;">{theme_chips()}</div>
  <input id="q" class="filter-input" type="search" placeholder="Filter concepts… (e.g. open weights, sandbox, harness)" aria-label="Filter concepts">
  <p class="eyebrow" id="count" data-unit="concepts" style="margin:12px 0 28px;">{stats['concepts']} concepts</p>
  {''.join(cards)}
</main>
<script>{FILTER_JS}</script>"""
    return page_shell(title=f"Concepts — {BLOG_NAME}", description=desc, canonical=f"{SITE}/concepts/", body=body, active='Concepts')


# ── Watching ──────────────────────────────────────────────────────────────────

def render_watching(entries: list[dict]) -> str:
    items = []
    n_total = n_follow = 0
    for e in reversed(entries):
        tp = e.get('tomorrow_preview') or ''
        if not tp:
            continue
        n_total += 1
        fu = ''
        if e['_followups']:
            n_follow += 1
            fu = '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">' + ''.join(
                f'<a class="tag" href="/entries/{o["date"]}.html" title="Mentions {esc(ph)}">↳ {esc(short_date(o["date"]))}: {esc(first_sentences(o["title"], 60))}</a>'
                for ph, o in e['_followups']) + '</div>'
        items.append(f"""<section class="card" data-block data-themes="{esc('|'.join(e['_tags']))}" data-text="{esc(norm(e['title'] + ' ' + tp))}" style="margin:0 0 14px;">
  <div class="meta-row" style="margin-bottom:8px;"><span class="day">Day {e['_day']}</span><span aria-hidden="true">·</span><time datetime="{e['date']}">{long_date(e['date'])}</time><span aria-hidden="true">·</span><a href="/entries/{e['date']}.html" style="color:var(--faint);text-decoration:none;">{esc(first_sentences(e['title'], 70))}</a></div>
  <p style="margin:0;font-size:16px;line-height:1.6;color:var(--text2);">{esc(tp)}</p>
  {fu}
</section>""")
    desc = (f"What the journal said it would watch next, day by day, and which later entries picked the thread up — "
            f"{n_total} watch lists, {n_follow} with a likely follow-up.")
    body = f"""<main id="main" class="wrap" style="max-width:820px;padding-top:48px;padding-bottom:60px;">
  <h1 class="page-h1">What we're watching</h1>
  <p class="lede">{esc(desc)} Follow-up links are matched automatically on names and model versions, so treat them as leads, not verdicts.</p>
  <div class="chips" style="margin:0 0 14px;">{theme_chips()}</div>
  <input id="q" class="filter-input" type="search" placeholder="Filter the watch list… (e.g. Mistral, GPT-6, EU)" aria-label="Filter the watch list">
  <p class="eyebrow" id="count" data-unit="watch lists" style="margin:12px 0 28px;">{n_total} watch lists</p>
  {''.join(items)}
</main>
<script>{FILTER_JS}</script>"""
    return page_shell(title=f"What we're watching — {BLOG_NAME}", description=desc, canonical=f"{SITE}/watching/", body=body, active='Watching')


# ── Start here ────────────────────────────────────────────────────────────────

def render_start(entries: list[dict], stats: dict) -> str:
    by_date = {e['date']: e for e in entries}
    paths = []
    for name, blurb, dates in PATHS:
        es = [by_date[d] for d in dates if d in by_date]
        if not es:
            continue
        steps = ''.join(
            f'<li><a href="/entries/{e["date"]}.html" style="text-decoration:none;color:var(--text);">{esc(e["title"])}</a>'
            f'<span style="display:block;font-family:var(--mono);font-size:12px;color:var(--faint);margin-top:2px;">Day {e["_day"]} · {esc(short_date(e["date"]))} · {e["_read"]} min</span></li>'
            for e in es)
        paths.append(f"""<section class="card" style="margin:0 0 16px;">
  <h3 style="font-family:var(--serif);font-weight:500;font-size:clamp(20px,2.8vw,24px);margin:0 0 6px;">{esc(name)}</h3>
  <p style="margin:0 0 14px;color:var(--muted);font-size:15.5px;">{esc(blurb)} <span style="font-family:var(--mono);font-size:12px;color:var(--faint);">{len(es)} entries · ~{sum(e['_read'] for e in es)} min</span></p>
  <ol class="path-list">{steps}</ol>
</section>""")
    recap_entry = next((e for e in reversed(entries) if e.get('recap')), None)
    recap = ''
    if recap_entry:
        recap = f"""<section style="margin:0 0 50px;">
  <h2 class="section-h2">Where the series has been</h2>
  <p style="font-size:16.5px;line-height:1.65;color:var(--text2);margin:0 0 8px;">{esc(recap_entry['recap'])}</p>
  <p class="eyebrow" style="margin:0;">Recap as written on Day {recap_entry['_day']} · <a href="/entries/{recap_entry['date']}.html" style="color:var(--faint);">{esc(long_date(recap_entry['date']))}</a></p>
</section>"""
    theme_rows = ''.join(f'<li><a href="/entries/?theme={esc(t)}" style="text-decoration:none;color:var(--text);">{esc(t)}</a> <span style="font-family:var(--mono);font-size:12px;color:var(--faint);">{n}</span></li>'
                         for t, n in stats['themes'].items())
    desc = (f"New here? How {AUTHOR}'s daily AI learning journal works, {len(paths)} curated learning paths through "
            f"{stats['entries']} entries, and where the series has been so far.")
    body = f"""<main id="main" class="wrap" style="max-width:820px;padding-top:48px;padding-bottom:60px;">
  <h1 class="page-h1">Start here</h1>
  <p class="lede">Every evening since {long_date(stats['started'])}, one entry: the day's agentic-AI news, the concept behind it explained simply, why it matters, and practical takeaways. {stats['entries']} entries and about {stats['words'] // 1000},000 words so far, with a current streak of {stats['streak']} days.</p>

  <section style="margin:0 0 50px;">
    <h2 class="section-h2">How to use this site</h2>
    <ul class="how-list">
      <li><a href="/">Journal</a> — the latest entry, and the archive by month.</li>
      <li><a href="/playbook/">Playbook</a> — every practical takeaway, filterable by theme. The fastest way to act on what the journal has learned.</li>
      <li><a href="/concepts/">Concepts</a> — the ideas behind the news, explained in plain language.</li>
      <li><a href="/watching/">Watching</a> — what each entry said to watch next, and which later entries followed up.</li>
      <li><a href="/review/">Review</a> — flashcards built from the takeaways, concepts and self-tests, for spaced repetition.</li>
      <li><a href="/weekly/">Weekly digest</a> — one page per week when daily is too much.</li>
      <li><a href="/tokenizer.html">Tokenizer</a>, <a href="/ai-tokenomics/">Tokenomics</a> and the <a href="/tools/model-team-evaluator.html">Model Team Evaluator</a> — tools for the cost side of agents.</li>
      <li><a href="{SITE}/feed.xml">RSS</a> and <a href="{SITE}/llms.txt">llms.txt</a> for readers and machines.</li>
    </ul>
  </section>

  <section style="margin:0 0 50px;">
    <h2 class="section-h2">Learning paths</h2>
    <p style="color:var(--muted);margin:0 0 18px;">Curated sequences through the archive. Read them in order; each one takes an evening or two.</p>
    {''.join(paths)}
  </section>

  {recap}

  <section style="margin:0 0 30px;">
    <h2 class="section-h2">Browse by theme</h2>
    <ul class="how-list">{theme_rows}</ul>
  </section>
</main>"""
    css = (".how-list{list-style:none;margin:0;padding:0;}.how-list li{font-size:16.5px;line-height:1.6;color:var(--text2);margin:0 0 10px;}"
           ".how-list a{color:var(--text);font-weight:600;}.path-list{margin:0;padding-left:22px;}.path-list li{font-size:16px;line-height:1.4;margin:0 0 10px;color:var(--text2);}")
    return page_shell(title=f"Start here — {BLOG_NAME}", description=desc, canonical=f"{SITE}/start/", body=body,
                      active='Start Here', extra_css=css)


# ── Weekly digests ────────────────────────────────────────────────────────────

def _week_label(key: str) -> str:
    s, e = week_bounds(key)
    return f"{long_date(s)} – {long_date(e)}"


def _week_digest_html(key: str, es: list[dict]) -> str:
    es = sorted(es, key=lambda e: e['date'], reverse=True)
    entries_html = ''.join(
        f'<li><a href="/entries/{e["date"]}.html"><span class="d">Day {e["_day"]} · {esc(long_date(e["date"]))}</span>'
        f'<span class="t">{esc(e["title"])}</span><span class="s">{esc(e["_sub"] or e["_excerpt"])}</span></a></li>' for e in es)
    tks = []
    for e in es:
        for t in e['_takeaways'][:2]:
            if t.get('title'):
                tks.append(f'<li><strong>{esc(t["title"])}</strong>' + (f' <span style="color:var(--muted);">{esc(t["body"])}</span>' if t.get('body') and t['body'] != t['title'] else '')
                           + f' <a href="/entries/{e["date"]}.html" style="font-family:var(--mono);font-size:11.5px;color:var(--faint);text-decoration:none;">Day {e["_day"]}</a></li>')
    picks = [f'<li><strong>{esc((e.get("viral_app") or {}).get("name", ""))}</strong> <a href="/entries/{e["date"]}.html" style="font-family:var(--mono);font-size:11.5px;color:var(--faint);text-decoration:none;">Day {e["_day"]}</a></li>'
             for e in es if (e.get('viral_app') or {}).get('name')]
    watch = [f'<li>{esc(first_sentences(e["tomorrow_preview"], 260))} <a href="/entries/{e["date"]}.html" style="font-family:var(--mono);font-size:11.5px;color:var(--faint);text-decoration:none;">Day {e["_day"]}</a></li>'
             for e in es if e.get('tomorrow_preview')]
    themes = Counter(t for e in es for t in e['_tags'])
    theme_line = ' · '.join(f'{esc(t)} ({n})' for t, n in themes.most_common())
    out = f"""<p class="eyebrow" style="margin:0 0 20px;">{len(es)} entries · {sum(e['_read'] for e in es)} min total · {theme_line}</p>
<h2 class="section-h2">Entries</h2>
<ul class="entry-list">{entries_html}</ul>
"""
    if tks:
        out += f'<h2 class="section-h2" style="margin-top:36px;">Takeaways of the week</h2><ul class="wk-list">{"".join(tks)}</ul>'
    if picks:
        out += f'<h2 class="section-h2" style="margin-top:36px;">Viral and open-source picks</h2><ul class="wk-list">{"".join(picks)}</ul>'
    if watch:
        out += f'<h2 class="section-h2" style="margin-top:36px;">Watch list</h2><ul class="wk-list">{"".join(watch)}</ul>'
    return out


WEEK_CSS = ".wk-list{margin:0;padding-left:20px;}.wk-list li{font-size:15.5px;line-height:1.55;color:var(--text2);margin:0 0 10px;}"


def render_week_page(key: str, es: list[dict], prev_key: str | None, next_key: str | None) -> str:
    label = _week_label(key)
    nav = '<nav class="pn" aria-label="Adjacent weeks" style="padding-left:0;padding-right:0;max-width:none;">'
    nav += (f'<a href="{next_key}.html"><div class="lbl">← Newer week</div><div class="ttl">{esc(_week_label(next_key))}</div></a>' if next_key else '<span></span>')
    nav += (f'<a href="{prev_key}.html" style="text-align:right;"><div class="lbl">Older week →</div><div class="ttl">{esc(_week_label(prev_key))}</div></a>' if prev_key else '<span></span>')
    nav += '</nav>'
    desc = f"Weekly digest of {AUTHOR}'s AI learning journal for {label}: {len(es)} entries, the week's takeaways, picks and watch list."
    body = f"""<main id="main" class="wrap" style="max-width:820px;padding-top:48px;padding-bottom:30px;">
  <p style="margin:0 0 30px;"><a href="/weekly/" style="font-family:var(--mono);font-size:12.5px;letter-spacing:.04em;color:var(--muted2);text-decoration:none;">← All weeks</a></p>
  <p class="kicker">Weekly digest · {esc(key)}</p>
  <h1 class="page-h1">{esc(label)}</h1>
  {_week_digest_html(key, es)}
  {nav}
</main>"""
    return page_shell(title=f"Week of {label} — {BLOG_NAME}", description=desc, canonical=f"{SITE}/weekly/{key}.html", body=body, extra_css=WEEK_CSS)


def render_weekly_index(weeks: list[tuple[str, list[dict]]]) -> str:
    latest_key, latest_es = weeks[0]
    rows = ''.join(
        f'<li><a href="{k}.html" style="text-decoration:none;display:block;">'
        f'<span class="d">{esc(k)} · {len(es)} entries</span>'
        f'<span class="t" style="font-size:clamp(17px,2.4vw,20px);">{esc(_week_label(k))}</span>'
        f'<span class="s">{esc(" · ".join(first_sentences(e["title"], 48) for e in sorted(es, key=lambda x: x["date"], reverse=True)[:3]))}</span></a></li>'
        for k, es in weeks[1:])
    desc = f"Weekly digests of {AUTHOR}'s daily AI learning journal: one page per week with the entries, takeaways, picks and watch list."
    body = f"""<main id="main" class="wrap" style="max-width:820px;padding-top:48px;padding-bottom:60px;">
  <h1 class="page-h1">Weekly digest</h1>
  <p class="lede">{esc(desc)} The current week is below; earlier weeks follow. Subscribe by <a href="{SITE}/feed.xml">RSS</a> to get every entry as it lands.</p>
  <section style="margin:0 0 50px;">
    <p class="kicker">This week · <a href="{latest_key}.html" style="color:var(--accent);">{esc(latest_key)}</a></p>
    <h2 style="font-family:var(--serif);font-weight:400;font-size:clamp(26px,3.6vw,36px);letter-spacing:-.015em;margin:0 0 18px;">{esc(_week_label(latest_key))}</h2>
    {_week_digest_html(latest_key, latest_es)}
  </section>
  <h2 class="section-h2">Earlier weeks</h2>
  <ul class="entry-list">{rows}</ul>
</main>"""
    return page_shell(title=f"Weekly digest — {BLOG_NAME}", description=desc, canonical=f"{SITE}/weekly/", body=body, extra_css=WEEK_CSS)


# ── Review (flashcards) ───────────────────────────────────────────────────────

REVIEW_JS = r"""
(function(){
  var ALL=JSON.parse(document.getElementById('cards-data').textContent);
  var state={filter:'All',kind:'all',i:0,flipped:false,known:{}};
  try{state.known=JSON.parse(localStorage.getItem('vs-review-known')||'{}')||{};}catch(e){state.known={};}
  function save(){try{localStorage.setItem('vs-review-known',JSON.stringify(state.known));}catch(e){}}
  function pool(){return ALL.filter(function(c){return (state.filter==='All'||c.th.indexOf(state.filter)>=0)&&(state.kind==='all'||c.k===state.kind)&&!(state.hideKnown&&state.known[c.id]);});}
  var deck=[];
  function shuffle(a){for(var i=a.length-1;i>0;i--){var j=Math.floor(Math.random()*(i+1));var t=a[i];a[i]=a[j];a[j]=t;}return a;}
  function rebuild(){deck=shuffle(pool().slice());state.i=0;state.flipped=false;render();}
  function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function render(){
    var el=document.getElementById('card');var c=deck[state.i];var known=Object.keys(state.known).length;
    document.getElementById('progress').textContent=deck.length?((state.i+1)+' / '+deck.length+' · '+known+' marked known'):('0 cards · '+known+' marked known');
    if(!c){el.innerHTML='<div class="fc-front"><p class="fc-q">No cards match this filter'+(state.hideKnown?' (known cards are hidden)':'')+'.</p></div>';return;}
    var kind=c.k==='quiz'?'Self-test':(c.k==='concept'?'Concept':'Takeaway');
    el.innerHTML='<div class="fc-meta">'+kind+' · Day '+c.d+' · '+esc(c.th[0])+(state.known[c.id]?' · <span style="color:var(--accent)">known</span>':'')+'</div>'
      +'<p class="fc-q">'+esc(c.f)+'</p>'
      +(state.flipped?'<div class="fc-a"><p>'+esc(c.b)+'</p><a href="'+c.u+'">'+esc(c.t)+' →</a></div>':'<p class="fc-hint">Tap or press space to reveal</p>');
  }
  function next(){if(!deck.length)return;state.i=(state.i+1)%deck.length;state.flipped=false;render();}
  function prev(){if(!deck.length)return;state.i=(state.i-1+deck.length)%deck.length;state.flipped=false;render();}
  function flip(){state.flipped=!state.flipped;render();}
  function mark(v){var c=deck[state.i];if(!c)return;if(v){state.known[c.id]=1;}else{delete state.known[c.id];}save();next();}
  document.getElementById('card').addEventListener('click',flip);
  document.getElementById('flip').addEventListener('click',flip);
  document.getElementById('next').addEventListener('click',next);
  document.getElementById('prev').addEventListener('click',prev);
  document.getElementById('again').addEventListener('click',function(){mark(false);});
  document.getElementById('got').addEventListener('click',function(){mark(true);});
  document.getElementById('shuffle').addEventListener('click',rebuild);
  document.getElementById('reset').addEventListener('click',function(){if(confirm('Forget which cards you marked as known?')){state.known={};save();rebuild();}});
  document.getElementById('hideknown').addEventListener('change',function(ev){state.hideKnown=ev.target.checked;rebuild();});
  document.querySelectorAll('.chip[data-theme]').forEach(function(ch){ch.addEventListener('click',function(){state.filter=ch.getAttribute('data-theme');document.querySelectorAll('.chip[data-theme]').forEach(function(x){x.classList.toggle('active',x===ch);x.setAttribute('aria-pressed',x===ch?'true':'false');});rebuild();});});
  document.querySelectorAll('.chip[data-kind]').forEach(function(ch){ch.addEventListener('click',function(){state.kind=ch.getAttribute('data-kind');document.querySelectorAll('.chip[data-kind]').forEach(function(x){x.classList.toggle('active',x===ch);x.setAttribute('aria-pressed',x===ch?'true':'false');});rebuild();});});
  document.addEventListener('keydown',function(ev){if(ev.target&&/input|textarea|select/i.test(ev.target.tagName))return;
    if(ev.key===' '){ev.preventDefault();flip();}else if(ev.key==='ArrowRight'){next();}else if(ev.key==='ArrowLeft'){prev();}else if(ev.key==='1'){mark(false);}else if(ev.key==='2'){mark(true);}});
  rebuild();
})();
"""


def build_cards(entries: list[dict]) -> list[dict]:
    cards = []
    for e in entries:
        base = {'d': e['_day'], 'u': f'/entries/{e["date"]}.html', 't': e['title'], 'th': e['_tags']}
        for i, t in enumerate(e['_takeaways']):
            title, body = (t.get('title') or '').strip(), (t.get('body') or '').strip()
            if title and body and body != title and len(body) > 25:
                cards.append({**base, 'id': f'{e["date"]}-t{i}', 'k': 'takeaway', 'f': title, 'b': body[:600]})
        for i, c in enumerate(e['_concepts']):
            cards.append({**base, 'id': f'{e["date"]}-c{i}', 'k': 'concept', 'f': f'Explain simply: {c["term"]}', 'b': c['text'][:600]})
        for i, q in enumerate(e.get('quiz') or []):
            if q.get('q') and q.get('a'):
                cards.append({**base, 'id': f'{e["date"]}-q{i}', 'k': 'quiz', 'f': q['q'], 'b': q['a'][:600]})
    return cards


def render_review(entries: list[dict]) -> str:
    cards = build_cards(entries)
    kinds = Counter(c['k'] for c in cards)
    kind_chips = ''.join(
        f'<button class="chip{" active" if k == "all" else ""}" type="button" data-kind="{k}" aria-pressed="{"true" if k == "all" else "false"}">{label}</button>'
        for k, label in [('all', f'All ({len(cards)})'), ('takeaway', f'Takeaways ({kinds.get("takeaway", 0)})'),
                         ('concept', f'Concepts ({kinds.get("concept", 0)})'), ('quiz', f'Self-tests ({kinds.get("quiz", 0)})')])
    desc = (f"Flashcards for spaced repetition: {len(cards)} cards built from the takeaways, concept explanations and "
            f"self-tests in {AUTHOR}'s AI learning journal. Progress stays in your browser.")
    body = f"""<main id="main" class="wrap" style="max-width:760px;padding-top:48px;padding-bottom:60px;">
  <h1 class="page-h1">Review</h1>
  <p class="lede">{esc(desc)} Space flips a card, ← → move, 1 = again, 2 = got it.</p>
  <div class="chips" style="margin:0 0 10px;">{kind_chips}</div>
  <div class="chips" style="margin:0 0 22px;">{theme_chips()}</div>
  <div id="card" class="fc" role="button" tabindex="0" aria-live="polite"></div>
  <div class="fc-actions">
    <button id="prev" class="btn" type="button">← Prev</button>
    <button id="flip" class="btn" type="button">Flip</button>
    <button id="next" class="btn" type="button">Next →</button>
    <span style="flex:1"></span>
    <button id="again" class="btn" type="button">Again</button>
    <button id="got" class="btn btn-primary" type="button">Got it ✓</button>
  </div>
  <div class="fc-foot">
    <span id="progress" class="eyebrow"></span>
    <label style="font-family:var(--mono);font-size:12px;color:var(--muted2);display:flex;align-items:center;gap:6px;"><input id="hideknown" type="checkbox"> hide known</label>
    <button id="shuffle" class="btn btn-sm" type="button">Shuffle</button>
    <button id="reset" class="btn btn-sm" type="button">Reset progress</button>
  </div>
  <script id="cards-data" type="application/json">{json.dumps(cards, ensure_ascii=False).replace('</', '<\\/')}</script>
</main>
<script>{REVIEW_JS}</script>"""
    css = (".fc{border:1px solid var(--border);border-radius:18px;background:var(--surface);padding:clamp(24px,4vw,40px);min-height:260px;cursor:pointer;box-shadow:0 18px 50px -30px var(--shadow);}"
           ".fc:focus{outline:2px solid var(--accent);outline-offset:3px;}.fc-meta{font-family:var(--mono);font-size:11.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);margin-bottom:16px;}"
           ".fc-q{font-family:var(--serif);font-size:clamp(22px,3.2vw,28px);line-height:1.3;color:var(--text);margin:0 0 16px;}.fc-hint{font-family:var(--mono);font-size:12px;color:var(--faintest);margin:0;}"
           ".fc-a{border-top:1px solid var(--border);padding-top:16px;}.fc-a p{font-family:var(--serif);font-size:clamp(17px,2.3vw,20px);line-height:1.6;color:var(--text2);margin:0 0 12px;}.fc-a a{font-family:var(--mono);font-size:12.5px;color:var(--accent);text-decoration:none;}"
           ".fc-actions{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 10px;}.fc-foot{display:flex;gap:14px;flex-wrap:wrap;align-items:center;}"
           ".btn{font-family:var(--mono);font-size:13px;padding:10px 14px;border-radius:9px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;}.btn:hover{border-color:var(--text);}"
           ".btn-primary{background:var(--text);color:var(--bg);border-color:var(--text);}.btn-sm{font-size:11.5px;padding:7px 10px;}")
    return page_shell(title=f"Review — {BLOG_NAME}", description=desc, canonical=f"{SITE}/review/", body=body, active='Review', extra_css=css)


# ── Machine-readable artifacts ────────────────────────────────────────────────

def render_index_json(entries: list[dict], stats: dict) -> str:
    items = [{
        'date': e['date'], 'day': e['_day'], 'title': e['title'], 'sub': e['_sub'], 'excerpt': e['_excerpt'],
        'tags': e['_tags'], 'read': e['_read'], 'words': e['_words'], 'url': f'/entries/{e["date"]}.html',
        **({'viral': (e.get('viral_app') or {}).get('name', '')[:120]} if (e.get('viral_app') or {}).get('name') else {}),
        **({'quiz': True} if e.get('quiz') else {}),
        **({'pdf': '/' + e['_pdf']} if e['_pdf'] else {}),
    } for e in reversed(entries)]
    return json.dumps({'generated': datetime.now(TZ).strftime('%Y-%m-%dT%H:%M:%S%z'), 'stats': stats, 'themes': THEMES, 'entries': items},
                      ensure_ascii=False, separators=(',', ':'))


def render_search_json(entries: list[dict]) -> str:
    items = []
    for e in reversed(entries):
        heads = ' '.join(split_heading(s.get('title') or '')[1] for s in e.get('sections') or [])
        tks = ' '.join((t.get('title') or '') for t in e['_takeaways'])
        text = re.sub(r'\s+', ' ', body_text(e))[:3000]
        items.append({'d': e['date'], 'n': e['_day'], 't': e['title'], 's': e['_sub'], 'h': heads, 'k': tks,
                      'v': (e.get('viral_app') or {}).get('name', '')[:120], 'x': text, 'th': e['_tags']})
    return json.dumps(items, ensure_ascii=False, separators=(',', ':'))


def render_llms_txt(entries: list[dict], stats: dict) -> str:
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
        "## Reader pages",
        "",
        f"- [Start here]({SITE}/start/): how the journal works and curated learning paths",
        f"- [Playbook]({SITE}/playbook/): all {stats['takeaways']} practical takeaways, by theme",
        f"- [Concepts]({SITE}/concepts/): {stats['concepts']} plain-language concept explanations",
        f"- [What we're watching]({SITE}/watching/): the day-by-day watch list and follow-ups",
        f"- [Weekly digest]({SITE}/weekly/): one page per week",
        f"- [Review]({SITE}/review/): flashcards for spaced repetition",
        f"- [Archive]({SITE}/entries/): browsable index of all entries",
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
        "",
    ]
    return '\n'.join(lines)


def entry_markdown(e: dict) -> str:
    """One entry as plain markdown for llms-full.txt."""
    out = [f"# Day {e['_day']}: {e['title']}", ""]
    if e.get('subtitle'):
        out += [f"*{e['subtitle']}*", ""]
    out += [f"Date: {long_date(e['date'])} · Author: {AUTHOR} · URL: {e['_url']} · Themes: {', '.join(e['_tags'])}", ""]
    intro = e.get('focus_intro') or ''
    if intro and intro.strip() != e['title'].strip():
        out += [intro, ""]
    v = e.get('viral_app') or {}
    if v.get('name'):
        out.append(f"**Viral / open-source spotlight: {v['name']}**")
        if v.get('description'):
            out.append(v['description'])
        for s in v.get('stats') or []:
            out.append(f"- {s.get('stat', '')} — {s.get('label', '')}")
        out.append("")
    stats = e.get('stats') or []
    if stats:
        out.append("**By the numbers:**")
        out += [f"- {s.get('stat', '')} — {s.get('label', '')}" for s in stats]
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
    if e['_takeaways']:
        out.append("**Practical takeaways:**")
        for t in e['_takeaways']:
            body = t.get('body') or ''
            title = t.get('title') or ''
            out.append(f"- {title}" + (f" — {body}" if body and body != title else ""))
        out.append("")
    if e.get('quiz'):
        out.append("**Self-test:**")
        for q in e['quiz']:
            out.append(f"- Q: {q.get('q', '')} A: {q.get('a', '')}")
        out.append("")
    if e.get('tomorrow_preview'):
        out += [f"**What we're watching:** {e['tomorrow_preview']}", ""]
    if e.get('sources'):
        out += [f"Sources: {e['sources']}", ""]
    return '\n'.join(out).rstrip() + '\n'


def render_llms_full(entries: list[dict]) -> str:
    head = (f"# {BLOG_NAME} — full text\n\n"
            f"Complete text of all {len(entries)} journal entries by {AUTHOR} "
            f"({SITE}), newest first. Index: {SITE}/llms.txt\n\n---\n\n")
    return head + '\n---\n\n'.join(entry_markdown(e) for e in reversed(entries))


def render_feed(entries: list[dict]) -> str:
    items = []
    for e in list(reversed(entries))[:FEED_SIZE]:
        content = render_body_blocks(e, for_feed=True).replace(']]>', ']]&gt;')
        deck = f'<p><em>{esc(e["_sub"])}</em></p>' if e['_sub'] else ''
        items.append(f"""  <item>
    <title>{esc(e['title'])}</title>
    <link>{e['_url']}</link>
    <guid isPermaLink="true">{e['_url']}</guid>
    <pubDate>{rfc822(e['date'])}</pubDate>
    <dc:creator>{AUTHOR}</dc:creator>
    {''.join(f'<category>{esc(t)}</category>' for t in e['_tags'])}
    <description>{esc(e['_excerpt'])}</description>
    <content:encoded><![CDATA[{deck}{content}]]></content:encoded>
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


def render_sitemap(entries: list[dict], week_keys: list[str]) -> str:
    newest = entries[-1]['date']
    static_pages = [
        (f"{SITE}/", newest, 'daily', '1.0'),
        (f"{SITE}/entries/", newest, 'daily', '0.9'),
        (f"{SITE}/start/", newest, 'weekly', '0.9'),
        (f"{SITE}/playbook/", newest, 'daily', '0.8'),
        (f"{SITE}/concepts/", newest, 'daily', '0.8'),
        (f"{SITE}/watching/", newest, 'daily', '0.7'),
        (f"{SITE}/weekly/", newest, 'weekly', '0.7'),
        (f"{SITE}/review/", newest, 'weekly', '0.6'),
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
    for k in week_keys:
        urls.append(f"""  <url>
    <loc>{SITE}/weekly/{k}.html</loc>
    <lastmod>{week_bounds(k)[1] if week_bounds(k)[1] < newest else newest}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.4</priority>
  </url>""")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + '\n'.join(urls) + '\n</urlset>\n')


# ── index.html: static-fallback block, chrome, data version ──────────────────

STATIC_BEGIN = '<!-- GEO:STATIC:BEGIN (generated by generate_geo.py — do not edit by hand) -->'
STATIC_END = '<!-- GEO:STATIC:END -->'
CSS_BEGIN = '/* GEO:CSS:BEGIN (generated by generate_geo.py — do not edit by hand) */'
CSS_END = '/* GEO:CSS:END */'
MAST_BEGIN = '<!-- GEO:MASTHEAD:BEGIN (generated by generate_geo.py — do not edit by hand) -->'
MAST_END = '<!-- GEO:MASTHEAD:END -->'
FOOT_BEGIN = '<!-- GEO:FOOTER:BEGIN (generated by generate_geo.py — do not edit by hand) -->'
FOOT_END = '<!-- GEO:FOOTER:END -->'


def render_static_block(entries: list[dict], stats: dict) -> str:
    """Static content inside #app so non-JS crawlers see the journal.
    The home page script replaces it on load, so users never see this."""
    latest = list(reversed(entries))[:10]
    items = ''.join(
        f'<li style="margin:0 0 16px;"><a href="/entries/{e["date"]}.html">'
        f'<strong>Day {e["_day"]} · {long_date(e["date"])}: {esc(e["title"])}</strong></a><br>'
        f'{esc(e["_sub"] or e["_excerpt"])}</li>'
        for e in latest)
    newest = entries[-1]
    return f"""{STATIC_BEGIN}
<div style="max-width:760px;margin:0 auto;padding:56px 28px;font-family:var(--sans);">
  <h1 style="font-family:var(--serif);font-weight:400;">Varun Singla — AI Learning Journal</h1>
  <p>Daily deep dives into agentic AI, the protocols that connect it (MCP, A2A), multi-agent systems,
  AI infrastructure economics, governance, and the industries AI is reshaping — written every evening
  by Varun Singla, a technology consultant and agentic AI researcher in Singapore.
  {len(entries)} entries published since {long_date(entries[0]['date'])}; updated daily.</p>
  <p><a href="/start/">Start here</a> · <a href="/entries/">Browse the full archive</a> · <a href="/playbook/">Playbook</a> ·
  <a href="/concepts/">Concepts</a> · <a href="/watching/">What we're watching</a> · <a href="/weekly/">Weekly digest</a> ·
  <a href="/review/">Review</a> · <a href="/about/">About Varun Singla</a> ·
  <a href="/tokenizer.html">LLM Tokenizer &amp; Cost Calculator</a> · <a href="/ai-tokenomics/">AI Tokenomics</a> ·
  <a href="/tools/model-team-evaluator.html">Model Team Evaluator</a> · <a href="/feed.xml">RSS</a> · <a href="/llms.txt">llms.txt</a></p>
  <h2 style="font-family:var(--serif);font-weight:500;">Latest entry — Day {newest['_day']}, {long_date(newest['date'])}</h2>
  <p><a href="/entries/{newest['date']}.html"><strong>{esc(newest['title'])}</strong></a><br>{esc(newest['_sub'] or newest['_excerpt'])}</p>
  <h2 style="font-family:var(--serif);font-weight:500;">Recent entries</h2>
  <ul style="list-style:none;padding:0;">{items}</ul>
</div>
{STATIC_END}"""


def _splice(text: str, begin: str, end: str, block: str) -> str:
    pattern = re.compile(re.escape(begin) + r'.*?' + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text)
    return text


def update_index_html(root: Path, entries: list[dict], stats: dict) -> str | None:
    """Refresh the generated regions of index.html. Returns new text or None if markers absent."""
    path = root / 'index.html'
    text = path.read_text(encoding='utf-8')
    if STATIC_BEGIN not in text:
        return None
    text = _splice(text, STATIC_BEGIN, STATIC_END, render_static_block(entries, stats))
    text = _splice(text, CSS_BEGIN, CSS_END, CSS_BEGIN + SITE_CSS + CSS_END)
    text = _splice(text, MAST_BEGIN, MAST_END, MAST_BEGIN + '\n' + masthead('Journal') + '\n' + MAST_END)
    text = _splice(text, FOOT_BEGIN, FOOT_END, FOOT_BEGIN + '\n' + page_footer() + '\n' + FOOT_END)
    version = f"{stats['latest']}-{stats['entries']}"
    text = re.sub(r'<meta name="journal-data-version" content="[^"]*">',
                  f'<meta name="journal-data-version" content="{version}">', text)
    return text


# ── Driver ────────────────────────────────────────────────────────────────────

def _write_if_changed(path: Path, content: str, changed: list[str], root: Path) -> None:
    old = path.read_text(encoding='utf-8') if path.exists() else None
    if old != content:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        changed.append(str(path.relative_to(root)))


def generate(root: Path | str = SCRIPT_DIR) -> list[str]:
    """Regenerate all generated artifacts. Returns repo-relative paths of files that changed."""
    root = Path(root)
    data = json.loads((root / 'learnings.json').read_text(encoding='utf-8'))
    entries = prepare(data, root)
    if not entries:
        return []
    stats = site_stats(entries)

    changed: list[str] = []
    for i, e in enumerate(entries):
        prev_e = entries[i - 1] if i > 0 else None
        next_e = entries[i + 1] if i < len(entries) - 1 else None
        _write_if_changed(root / e['_file'], render_entry_page(e, prev_e, next_e), changed, root)

    _write_if_changed(root / 'entries' / 'index.html', render_entries_index(entries), changed, root)
    _write_if_changed(root / 'playbook' / 'index.html', render_playbook(entries, stats), changed, root)
    _write_if_changed(root / 'concepts' / 'index.html', render_concepts(entries, stats), changed, root)
    _write_if_changed(root / 'watching' / 'index.html', render_watching(entries), changed, root)
    _write_if_changed(root / 'start' / 'index.html', render_start(entries, stats), changed, root)
    _write_if_changed(root / 'review' / 'index.html', render_review(entries), changed, root)

    weeks: dict[str, list[dict]] = {}
    for e in entries:
        weeks.setdefault(e['_week'], []).append(e)
    week_keys = sorted(weeks, reverse=True)
    for i, k in enumerate(week_keys):
        newer = week_keys[i - 1] if i > 0 else None
        older = week_keys[i + 1] if i < len(week_keys) - 1 else None
        _write_if_changed(root / 'weekly' / f'{k}.html', render_week_page(k, weeks[k], older, newer), changed, root)
    _write_if_changed(root / 'weekly' / 'index.html', render_weekly_index([(k, weeks[k]) for k in week_keys]), changed, root)

    _write_if_changed(root / 'index.json', render_index_json(entries, stats), changed, root)
    _write_if_changed(root / 'search.json', render_search_json(entries), changed, root)
    _write_if_changed(root / 'llms.txt', render_llms_txt(entries, stats), changed, root)
    _write_if_changed(root / 'llms-full.txt', render_llms_full(entries), changed, root)
    _write_if_changed(root / 'feed.xml', render_feed(entries), changed, root)
    _write_if_changed(root / 'sitemap.xml', render_sitemap(entries, week_keys), changed, root)

    new_index = update_index_html(root, entries, stats)
    if new_index is not None:
        _write_if_changed(root / 'index.html', new_index, changed, root)

    return changed


if __name__ == '__main__':
    changed = generate(SCRIPT_DIR)
    if changed:
        print(f"✅  {len(changed)} file(s) regenerated:")
        for f in changed[:40]:
            print(f"   • {f}")
        if len(changed) > 40:
            print(f"   … and {len(changed) - 40} more")
    else:
        print("✅  All generated files already up to date.")
