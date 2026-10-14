#!/usr/bin/env python3
"""
update_site.py — Auto-update varunsingla.com AI learning blog

Every evening:
  1. Finds today's (or the most recent unprocessed) daily AI learning PDF
  2. Extracts full rich content — sections, bullets, tables, takeaways
  3. Merges into learnings.json
  4. Pushes directly to GitHub via REST API (no git required)

Run:  python3 update_site.py
"""

import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Auto-install pdfplumber if missing ────────────────────────────────────────
try:
    import pdfplumber
except ImportError:
    print("   Installing pdfplumber …")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "pdfplumber", "--break-system-packages", "-q"],
        check=True,
    )
    import pdfplumber

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR     = Path(__file__).parent.resolve()
LEARNINGS_JSON = SCRIPT_DIR / "learnings.json"
WORKSPACE_DIR  = SCRIPT_DIR.parent          # Personal Files folder
CONFIG_FILE    = SCRIPT_DIR / "config.json"
# ─────────────────────────────────────────────────────────────────────────────

MONTHS = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
    "sep":9,"oct":10,"nov":11,"dec":12,
}


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"⚠️   config.json malformed: {e}")
    return {}


# ── PDF discovery ─────────────────────────────────────────────────────────────

def extract_date_from_filename(name: str) -> datetime | None:
    """Try to parse a date from common PDF filename patterns."""
    name = name.lower().replace("_", "-").replace(" ", "-")
    # YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    # MonthDD_YYYY or MonthDD-YYYY or Month-DD-YYYY (with explicit year)
    m = re.search(r"([a-z]+)[- ]?(\d{1,2})[,_-]?\s*(\d{4})", name)
    if m:
        month = MONTHS.get(m[1][:3])
        if month:
            try:
                return datetime(int(m[3]), month, int(m[2]))
            except ValueError:
                pass
    # MonthDD without a year — e.g. "apr06" or "apr6" at end of filename.
    # Assume current year (these are daily learning PDFs, always recent).
    # Use finditer so non-month words like "day16" are skipped.
    for m in re.finditer(r"([a-z]+)(\d{1,2})(?:[^0-9]|$)", name):
        month = MONTHS.get(m[1][:3])
        if month:
            try:
                return datetime(datetime.now().year, month, int(m[2]))
            except ValueError:
                pass
    return None


def find_daily_pdfs() -> list[tuple[datetime, Path]]:
    """Return list of (date, path) for all AI learning PDFs, newest first.
    Case-insensitive: scans all PDFs and filters by name keywords."""
    keywords = ["daily", "learning", "ai", "trends"]
    seen = set()
    results = []
    for p in WORKSPACE_DIR.glob("**/*.pdf"):
        if p in seen:
            continue
        name_lower = p.stem.lower()
        # Must contain at least 2 of the keywords to be a learning PDF
        # (avoids telco docs, playbooks, etc.)
        matches = sum(1 for k in keywords if k in name_lower)
        if matches < 2:
            continue
        seen.add(p)
        dt = extract_date_from_filename(p.stem)
        if dt:
            results.append((dt, p))
    results.sort(key=lambda x: x[0], reverse=True)
    return results


def find_unprocessed_pdf(learnings: list[dict]) -> tuple[datetime, Path] | None:
    """Return the most recent PDF not yet in learnings.json."""
    processed_dates = {l["date"] for l in learnings}
    for dt, path in find_daily_pdfs():
        if dt.strftime("%Y-%m-%d") not in processed_dates:
            return dt, path
    return None


# ── PDF parsing ───────────────────────────────────────────────────────────────

def clean(text: str) -> str:
    """Strip extra whitespace and ALL known PDF encoding artifacts.

    Handles artifacts produced by pdfplumber's font-decoding failures:
      • â(x)¢   — UTF-8 bullet U+2022 mis-decoded as Latin-1
      • (cid:N) — unresolved glyph IDs from embedded font tables
      • ﬁ ﬂ ﬀ ﬃ ﬄ — OpenType ligatures that should be plain ASCII
      • fi used as → — fi-ligature glyph slot repurposed as an arrow
      • nn / n  — stray bullet-character artifacts at line start
    """
    # ── OpenType / Latin ligature normalisation ───────────────────────────────
    _LIGATURES = {
        '\ufb00': 'ff', '\ufb01': 'fi', '\ufb02': 'fl',
        '\ufb03': 'ffi', '\ufb04': 'ffl', '\ufb05': 'st', '\ufb06': 'st',
    }
    for lig, rep in _LIGATURES.items():
        text = text.replace(lig, rep)

    # ── fi-ligature used as → between state-machine words ────────────────────
    # e.g. "submitted fi working fi completed" → "submitted → working → completed"
    # Pattern: fi surrounded by spaces between lowercase/hyphenated words
    text = re.sub(r'(?<=[a-z\-])\s+fi\s+(?=[a-z])', ' → ', text)

    # ── fi-ligature used as / between CamelCase words (table separators) ──────
    # e.g. "HostfiClientfiServer" → "Host/Client/Server"
    text = re.sub(r'([A-Z][a-z]+)fi([A-Z])', r'\1/\2', text)

    # ── Garbled bullet: â(any 0-1 char)¢  →  •  ─────────────────────────────
    # UTF-8 bullet (U+2022) = \xe2\x80\xa2; when decoded as Latin-1:
    #   \xe2 → â (U+00E2)
    #   \x80 → control char / 'n' / euro sign (pdfplumber variability)
    #   \xa2 → ¢ (U+00A2)
    text = re.sub(r'\u00e2.?\u00a2', '• ', text)

    # ── (cid:N) unresolved glyph IDs ─────────────────────────────────────────
    # cid:127 is typically • (middle dot / bullet); others are unknown → drop
    text = re.sub(r'\(cid:127\)', '• ', text)
    text = re.sub(r'\(cid:\d+\)', '', text)

    # ── Whitespace normalisation ──────────────────────────────────────────────
    text = re.sub(r"\s+", " ", text).strip()

    # ── Unicode smart punctuation → consistent ASCII-friendly equivalents ─────
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u2014", "--").replace("\u2013", "-")
    text = text.replace("\u2022", "•")          # actual bullet → bullet
    text = text.replace("\u201c", '"').replace("\u201d", '"')

    # ── Stray leading artifact chars (nn / n at line start) ──────────────────
    # These are bullet artifacts that survived the â¢ pass above
    text = re.sub(r'^n{1,2}\s+', '• ', text)

    # ── Collapse duplicate bullet markers ────────────────────────────────────
    text = re.sub(r'(•\s*){2,}', '• ', text)

    return text.strip()


def clean_table_cell(cell) -> str:
    """Clean a single table cell (may be None or multi-line)."""
    if cell is None:
        return ""
    text = str(cell)
    # Normalise internal newlines to spaces before clean()
    text = text.replace("\n", " ")
    return clean(text)


def is_section_heading(line: str) -> bool:
    """Detect a major section heading (numbered or known keywords)."""
    line = line.strip()
    # "1. Title" style
    if re.match(r"^\d+\.\s+\S", line):
        return True
    # "01 — Title" or "01 - Title" or "01 -- Title" style
    if re.match(r"^\d{1,2}\s*[-—–]{1,2}\s+\S", line):
        return True
    # "1 · Title" style (middle dot separator, used in some PDF layouts)
    if re.match(r"^\d{1,2}\s*[·•]\s+\S", line):
        return True
    # "1) Title" style (Day ~100+ layout). Requires an uppercase letter within
    # the first word (allowing camelCase brand names like "xAI", "iPhone"),
    # so wrapped lines like "80) and Chinese models…" don't false-positive.
    if re.match(r"^\d\)\s+(?:[A-Z]|[a-z]{1,2}[A-Z])", line):
        return True
    # "TOMORROW" preview heading — standalone line only (with optional 'n'
    # bullet-artifact prefix and trailing punctuation), so it doesn't
    # false-positive on sentences/subtitles that merely start with the word
    # "Tomorrow" (e.g. "Tomorrow, No Opt-Out Required", "tomorrow's automatic
    # switch…" mid-takeaway continuation text).
    if re.match(r"^(?:n\s+)?tomorrow['’]?s?\s*[:.]?$", line, re.I):
        return True
    headings = [
        "today's focus", "today's topic", "what's inside", "key announcements",
        "what is ", "core architecture", "how it works", "roadmap", "key concept",
        "what's making", "the big shift", "the scary part", "numbers worth",
        "practical takeaway", "key takeaway", "market signal", "viral app",
        "sources", "further reading", "what are ", "why exploding",
        "real-world", "challenges", "learning roadmap", "key vocabulary",
        "application examples", "deep dive", "use cases", "agent communication",
        "glossary", "action points", "your action",
        "main topic", "industry flash",
        # Day ~100+ layout headings
        "viral /", "viral spotlight", "open-source spotlight", "oss spotlight",
        "practical takeaways",
        # Handle 'n' bullet artifact prefix (e.g. "n Practical Takeaways for Varun", "n Market Signal")
        "n practical takeaway", "n market signal", "n viral app", "n breaking",
        "n today's focus",
    ]
    low = line.lower()
    for h in headings:
        # Cap length so a body sentence that merely *starts* with a heading
        # keyword ("Roadmap, pricing, and even its willingness to work with
        # rival platforms can shift overnight…") isn't misread as a heading —
        # real headings using these generic keywords are short standalone
        # labels, not full sentences.
        if low.startswith(h) and len(line) < 60:
            return True
    return False


def is_bullet(line: str) -> bool:
    """Detect bullet lines — including cleaned artifact bullets."""
    return bool(
        re.match(r"^[•\-\*▸▶◆●▪]\s", line)
        or re.match(r"^\d+\.\s", line)
    )


def extract_bullet_text(line: str) -> str:
    """Strip leading bullet marker."""
    line = re.sub(r"^[•\-\*▸▶◆●▪]\s+", "", line)
    line = re.sub(r"^\d+\.\s+", "", line)
    return line.strip()


def parse_date_from_text(text: str) -> tuple[str, str, int | None]:
    """Extract date_str, display_date, issue_number from PDF header text."""
    # Issue / Edition number  — handles both "Issue #2" and "Edition #3"
    issue = None
    m = re.search(r"(?:issue|edition)\s*#?(\d+)", text, re.IGNORECASE)
    if m:
        issue = int(m[1])

    # Try "Month DD, YYYY" or "Day, Month DD, YYYY"
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2}),?\s+(\d{4})", text, re.IGNORECASE
    )
    if m:
        month_num = MONTHS[m[1].lower()[:3]]
        day, year = int(m[2]), int(m[3])
        dt = datetime(year, month_num, day)
        return dt.strftime("%Y-%m-%d"), f"{m[1]} {day}, {year}", issue

    # Try YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        dt = datetime(int(m[1]), int(m[2]), int(m[3]))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%B %-d, %Y"), issue

    return "", "", issue


def _extract_text_outside_tables(page) -> str:
    """Extract text from a pdfplumber page, EXCLUDING table regions.

    This prevents table cell content from bleeding into the paragraph text
    (the primary source of garbled content in previous parser versions).
    """
    found_tables = page.find_tables()
    if not found_tables:
        return page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""

    table_bboxes = [t.bbox for t in found_tables]

    def _not_in_any_table(obj):
        ox0 = obj.get('x0', 9999)
        ox1 = obj.get('x1', 0)
        ot  = obj.get('top', 9999)
        ob  = obj.get('bottom', 0)
        for (tx0, tt, tx1, tb) in table_bboxes:
            # Allow 2pt tolerance on all edges
            if ox0 >= tx0 - 2 and ox1 <= tx1 + 2 and ot >= tt - 2 and ob <= tb + 2:
                return False
        return True

    return page.filter(_not_in_any_table).extract_text(x_tolerance=1.5, y_tolerance=3) or ""


def _is_toc_table(table: list[list]) -> bool:
    """Return True if this looks like a navigation/TOC table (not content).
    TOC tables are single-column lists of numbered items or 'What's Inside' headers."""
    if not table:
        return False
    # All rows have ≤ 1 column → likely a single-column nav list
    if all(len(row) <= 1 for row in table):
        return True
    # First cell contains a known navigation header
    first_cell = str(table[0][0] or "").strip() if table and table[0] else ""
    if re.search(r"what.s inside|table of contents|contents", first_cell, re.I):
        return True
    return False


def _extract_stat_box_tables(raw_tables: list[list]) -> list[str]:
    """Pull key-stats from 'stat box' tables — single-row or two-row tables
    where cells contain a big number + label (e.g. '150+\\nOrganisations…')."""
    stats = []
    for table in raw_tables:
        if not table:
            continue
        # Flatten — stat box tables typically have 1-3 rows, 2-4 cols
        all_cells = []
        for row in table:
            for cell in row:
                if cell and str(cell).strip():
                    all_cells.append(clean_table_cell(cell))
        for cell_text in all_cells:
            # Matches e.g. "150+ Organisations adopting A2A" or "$73B Samsung AI chip"
            if re.match(r'^[\$]?\d[\d,\.]+[%+KMBkTx]*\b', cell_text) and 5 < len(cell_text) < 120:
                # Compact to one clean line
                stats.append(re.sub(r'\s+', ' ', cell_text).strip())
    return stats


def _page_tables_with_bbox(page) -> list[dict]:
    """Return all tables on a page with their bounding boxes and extracted data.
    Each item: {'bbox': (x0,top,x1,bottom), 'data': [[cell, …], …], 'row_bboxes': [...]}"""
    results = []
    for ft in page.find_tables():
        extracted = ft.extract()
        if extracted:
            try:
                row_bboxes = [r.bbox for r in ft.rows]
            except Exception:
                row_bboxes = []
            results.append({'bbox': ft.bbox, 'data': extracted, 'row_bboxes': row_bboxes})
    return results


# Standalone box headers ("VIRAL / OPEN-SOURCE SPOTLIGHT", "MARKET SIGNAL", …) that
# pdfplumber sometimes groups into a bordered-box table as a header-only row, with
# the actual title/body text left as ordinary paragraph text outside the table.
# When that happens the header text never reaches `lines`, so downstream parsing
# (which finds these sections by searching for the header string) sees nothing and
# either drops the section or misattributes a neighboring table cell to it.
_SPECIAL_HEADER_RE = re.compile(
    r'^(viral app(\s+of\s+the\s+day)?|viral\s*/\s*open.source spotlight|open.source spotlight|'
    r'viral spotlight|oss spotlight|market signal|practical takeaways|tomorrow)$', re.I
)


def _text_lines_with_y(page, not_in_table) -> list[tuple[float, str]]:
    """Group words outside detected tables into visual lines, each tagged with its
    top y-position, so they can be interleaved with orphan table-header markers."""
    rows: dict[int, list[tuple[float, str]]] = {}
    for w in page.extract_words(x_tolerance=1.5, y_tolerance=3):
        if not not_in_table(w):
            continue
        y_key = int(w['top'] / 4) * 4
        rows.setdefault(y_key, []).append((w['x0'], w['text']))
    out = []
    for y in sorted(rows):
        words = sorted(rows[y], key=lambda x: x[0])
        out.append((float(y), ' '.join(ww[1] for ww in words)))
    return out


def _left_col_lines(page, top_skip: float = 0.0) -> list[str]:
    """Extract lines from the LEFT column only (x0 < 55% page width),
    skipping the top N points (to avoid the header/title region).
    Words are grouped into visual lines by their vertical position."""
    pw = page.width
    col_limit = pw * 0.55
    rows: dict[int, list[tuple[float, str]]] = {}
    for w in page.extract_words(x_tolerance=1.5, y_tolerance=3):
        if w['top'] < top_skip:
            continue
        if w['x0'] > col_limit:
            continue
        # Bucket by 4pt vertical bands → stable grouping across slight y-shifts
        y_key = int(w['top'] / 4) * 4
        rows.setdefault(y_key, []).append((w['x0'], w['text']))
    lines = []
    for y in sorted(rows):
        words = sorted(rows[y], key=lambda x: x[0])
        lines.append(' '.join(w[1] for w in words))
    return lines


def _is_list_break_heading(ln: str) -> bool:
    """True if `ln` looks like a heading/subheading that should end whatever
    bullet or paragraph text was accumulating (not itself list content)."""
    return bool(
        re.match(r'^\d+\.\s+[A-Z]', ln)
        or re.match(r'^[A-Z][A-Za-z ]{3,40}:?\s*$', ln)
        or re.match(r'^Stage \d', ln)
        or re.match(r'^Layer \d', ln)
        or re.match(r'^Step \d', ln)
    )


def _bullets_from_lines(lines: list[str]) -> list[str]:
    """Convert a list of visual text lines into clean bullet strings.
    Handles (cid:127) bullets, 'n ' artifacts, and multi-line continuations."""
    bullets: list[str] = []
    current: list[str] = []

    def flush():
        if current:
            b = clean(' '.join(current))
            if len(b) > 20:
                bullets.append(b)
            current.clear()

    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        # Detect bullet starters
        is_start = bool(
            re.match(r'^\(cid:127\)', ln)
            or re.match(r'^n\s+\S', ln)          # 'n' artifact bullet
            or re.match(r'^[•▸▶◆●▪]\s', ln)
        )
        # Detect section headings / subheadings — stop accumulation
        is_heading = _is_list_break_heading(ln)
        if is_start:
            flush()
            stripped = re.sub(r'^\(cid:127\)\s*|^n\s+|^[•▸▶◆●▪]\s*', '', ln)
            current.append(stripped)
        elif is_heading:
            flush()
        elif current:
            # Continuation line — append if it looks like prose (not a new element)
            if not re.match(r'^\d+\.\s', ln):
                current.append(ln)
        # Lines outside any bullet context are ignored (headings, subheadings, etc.)

    flush()
    return bullets


def _clean_stat_cell(cell: str) -> dict | None:
    """Parse a stat cell like '63%\norgs can\'t...' → {'stat': '63%', 'label': '...'}.
    Works whether the number and label are separated by \\n or by a space."""
    if not cell:
        return None
    cell = cell.strip()
    # Split on first newline if present
    if '\n' in cell:
        parts = cell.split('\n', 1)
        stat, label = parts[0].strip(), parts[1].strip()
    else:
        # Try splitting after the numeric token
        m = re.match(r'^([\$£€]?[\d,\.]+[%+KMBTkx]*\+?)\s+(.*)', cell)
        if m:
            stat, label = m.group(1), m.group(2)
        else:
            return None
    stat = clean(stat)
    label = clean(label)
    # Support numeric stats AND rank/hash stats like "#1", "#3"
    if re.match(r'^[\$£€#]?[\d,]', stat) and label:
        return {'stat': stat, 'label': label}
    return None


def _is_stat_box(table_data: list[list]) -> bool:
    """Return True if this looks like a stat-box table (single row, 2–5 cols, all numeric)."""
    if not table_data or len(table_data) > 2:
        return False
    # Check the first (and possibly only) row
    row = table_data[0]
    if len(row) < 2 or len(row) > 6:
        return False
    numeric_count = sum(
        1 for cell in row
        if cell and re.match(r'^[\$£€#]?[\d,\.]+[%+KMBTkx]*|^#\d', str(cell).strip())
    )
    return numeric_count >= len(row) // 2


def _extract_table_clean(table_data: list[list]) -> dict | None:
    """Convert raw pdfplumber table data to a clean {'headers': [], 'rows': [[]]} dict.
    Filters blank rows. Returns None if table is trivially empty."""
    if not table_data or len(table_data) < 1:
        return None
    cleaned = []
    for row in table_data:
        clean_row = [clean_table_cell(cell) for cell in (row or [])]
        if any(c for c in clean_row):
            cleaned.append(clean_row)
    if len(cleaned) < 1:
        return None
    if len(cleaned) == 1:
        # Single-row table with header only — still useful as a key-value if 2 cols
        if len(cleaned[0]) >= 2:
            return {'headers': cleaned[0], 'rows': []}
        return None
    return {'headers': cleaned[0], 'rows': cleaned[1:]}


def _find_viral_app_in_tables(page_tables: list[dict]) -> dict | None:
    """Scan page tables for the 'VIRAL APP OF THE DAY' pattern.
    Returns {'name': str, 'description': str, 'stats': [...]} or None."""
    # Collect all cell text for scanning
    for tbl in page_tables:
        for row in tbl['data']:
            for cell in row:
                if cell and re.search(r'viral app', str(cell), re.I):
                    # This table or a nearby one is the viral app section.
                    # The name is usually in the same or next cell.
                    # Return a signal to the caller.
                    return tbl  # caller will process further
    return None


_SMALL_WORDS = {
    'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'in', 'of', 'on',
    'or', 'the', 'to', 'vs', 'via', 'nor', 'per',
}


def _smart_title_case(s: str) -> str:
    """Title-case a phrase, keeping small words lowercase and acronyms intact."""
    words = s.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if 0 < i < len(words) - 1 and lw in _SMALL_WORDS:
            out.append(lw)
        elif w.isupper() and len(w) > 1:      # keep acronyms (MCP, RL, …)
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return ' '.join(out)


_SENT_END = re.compile(r"[.!?…][\"'”’)\]]*$")


def _ends_sentence(text: str) -> bool:
    return bool(_SENT_END.search(text.strip()))


def _trim_to_sentence(text: str, min_len: int = 50) -> str:
    """Cut text back to its last complete sentence; '' if none long enough.
    Sentence ends are terminal punctuation followed by whitespace, so
    decimals ("78.7%") and version numbers ("GPT-5.5") don't count."""
    text = text.strip()
    if not text or _ends_sentence(text):
        return text
    end = None
    for m in re.finditer(r"[.!?…][\"'”’)\]]*(?=\s)", text):
        end = m.end()
    if end and end >= min_len:
        return text[:end].strip()
    return ""


_FOOTER_RE = re.compile(r'varunsingla\.com|generated by|agentic ai daily', re.I)

# Per-page running header/footer ("Varun Singla · Daily AI Learning Page 3"),
# repeated at the top of every page. Unlike _FOOTER_RE (genuine end-of-content
# markers), this can appear mid-block whenever a list item spans a page break,
# so it must be skipped rather than treated as a terminator.
_PAGE_HEADER_RE = re.compile(r'^varun singla\b.*\bpage\s*\d+\s*$', re.I)


def _extract_numbered_takeaways(all_flat_lines: list[str]) -> tuple[list[dict], tuple[int, int] | None]:
    """Extract takeaways from the Day ~100+ layout:

        PRACTICAL TAKEAWAYS
        1. Improve the memory and the skills before you fine-tune
        <body lines…>
        2. Treat every learning write as a deploy
        <body lines…>

    Returns (items, (start_idx, end_idx)) where the index range covers the
    takeaway block in all_flat_lines, so section building can skip it.
    Returns ([], None) if no such block exists.
    """
    for i, ln in enumerate(all_flat_lines):
        if not re.match(r'^(?:[n•]\s+)?practical takeaways?\b', ln.strip(), re.I):
            continue
        items: list[dict] = []
        current: dict | None = None
        j = i + 1
        while j < len(all_flat_lines):
            l = all_flat_lines[j].strip()
            m_num = re.match(r'^(\d{1,2})[.)]\s+(.+)$', l)
            if m_num:
                if current:
                    items.append(current)
                current = {'title': clean(m_num.group(2)), 'body': []}
            elif _PAGE_HEADER_RE.match(l):
                j += 1
                continue
            elif _FOOTER_RE.search(l) or (is_section_heading(l) and not re.match(r'^\d', l)):
                break
            elif current is not None:
                # Wrapped title continuation starts lowercase before any body.
                # extract_text() can wrap a long title mid-sentence onto a line
                # that immediately runs into the body prose with no separator
                # (e.g. "...any other" / "perimeter. OpenAI's incident shows...").
                # A length cap alone mis-splits these — instead keep pulling
                # continuation text into the title only until its own sentence
                # actually ends, then hand the remainder of that line to body.
                title_done = bool(re.search(r'[.!?]"?$', current['title']))
                if not current['body'] and not title_done and re.match(r'^[a-z]', l):
                    m_end = re.match(r'^(.*?[.!?])(?:\s+(.*))?$', l)
                    if m_end:
                        current['title'] = clean(current['title'] + ' ' + m_end.group(1))
                        if m_end.group(2):
                            current['body'].append(m_end.group(2))
                    else:
                        current['title'] = clean(current['title'] + ' ' + l)
                else:
                    current['body'].append(l)
            j += 1
        if current:
            items.append(current)
        takeaways = [
            {'title': it['title'], 'body': clean(' '.join(it['body']))}
            for it in items if it['body']
        ]
        if takeaways:
            return takeaways, (i, j)
        return [], None
    return [], None


# ── v5 additions: front matter, sources, watch list, themes, quiz, repair ──────
#
# Everything below was added so that (a) new PDFs get a real headline, a deck
# line ("subtitle"), sources, the TOMORROW watch list, explicit themes and an
# optional SELF-TEST block, and (b) existing entries in learnings.json can be
# repaired in place (repair_all) without losing any text: whenever a stored
# value is replaced by something that is not a superset of it, the old value is
# kept under <field>_original.

SCHEMA_VERSION = 2          # bump when repair_entry learns a new, re-runnable fix

THEMES = ['Foundations & Protocols', 'Industry Verticals', 'Enterprise & Strategy',
          'Infrastructure & Economics', 'Models & Frontier', 'Governance & Safety']

_THEME_ALIASES = {
    'foundations': THEMES[0], 'protocols': THEMES[0], 'foundations & protocols': THEMES[0],
    'foundations and protocols': THEMES[0], 'agent foundations': THEMES[0],
    'industry': THEMES[1], 'industry verticals': THEMES[1], 'verticals': THEMES[1], 'industries': THEMES[1],
    'enterprise': THEMES[2], 'strategy': THEMES[2], 'enterprise & strategy': THEMES[2],
    'enterprise and strategy': THEMES[2], 'enterprise ai': THEMES[2], 'business': THEMES[2],
    'infrastructure': THEMES[3], 'economics': THEMES[3], 'infrastructure & economics': THEMES[3],
    'infrastructure and economics': THEMES[3], 'compute': THEMES[3], 'chips': THEMES[3],
    'models': THEMES[4], 'frontier': THEMES[4], 'models & frontier': THEMES[4],
    'models and frontier': THEMES[4], 'frontier models': THEMES[4], 'model race': THEMES[4],
    'governance': THEMES[5], 'safety': THEMES[5], 'governance & safety': THEMES[5],
    'governance and safety': THEMES[5], 'ai safety & governance': THEMES[5],
    'ai safety and governance': THEMES[5], 'safety & governance': THEMES[5],
    'ai safety': THEMES[5], 'regulation': THEMES[5], 'policy': THEMES[5], 'security': THEMES[5],
}

_RUNNING_HDR_RE = re.compile(
    r"^(?:varun singla\b|varun's daily ai brief|ai daily learning\s*(?:[·•|\-—–]|$)|daily ai learning\s*(?:[·•|\-—–]|$)|"
    r"agentic ai daily\b|day\s*\d+\s*[|·•]|.*\bpage\s*\d+\s*$|\w+ \d{1,2}, \d{4}\s*[·•|]\s*issue)", re.I)
_GENERIC_TITLE_RE = re.compile(
    r"^(?:ai learning(?:\s*[-—–:]+\s*day\s*\d+)?|ai daily learning|daily ai learning|agentic ai daily|"
    r"agentic ai learning(?: series)?|ai learning journal|day\s*\d+)\s*[.:]?\s*$", re.I)
_META_LINE_RE = re.compile(
    r"^(?:day\s*\d+\s*[·•|]|(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+\w+ \d|"
    r"\w+ \d{1,2}, \d{4}\s*[·•|]|issue\s*#?\d+)", re.I)
_DATE_PREFIX_RE = re.compile(
    r"^(?:\w+day,?\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2},?\s+\d{4}\s*(?:[-—–:|·]+\s*)+", re.I)
_FOCUS_PREFIX_RE = re.compile(r"^today.s\s+(?:focus|topic)\s*[:\-—–]\s*", re.I)
_DAY_PREFIX_RE = re.compile(r"^day\s*\d+\s*(?:[-—–·|:]+\s*)+", re.I)
_SHOUT_WORD_RE = re.compile(r"^[A-Z][A-Z0-9&'’.\-]*[A-Z]$")

# Acronyms that stay upper-case even when the body text never mentions them.
_ACRONYMS = {
    'AI', 'US', 'U.S.', 'UK', 'EU', 'UN', 'FTC', 'NSA', 'FBI', 'CIA', 'CISA', 'SEC', 'DOJ', 'FDA', 'NHS',
    'NIST', 'ISO', 'GPT', 'MCP', 'A2A', 'API', 'APIS', 'CEO', 'CFO', 'CIO', 'CTO', 'COO', 'CRM', 'UI', 'UX',
    'GPU', 'GPUS', 'TPU', 'TPUS', 'CPU', 'IPO', 'DMA', 'ROI', 'LLM', 'LLMS', 'RAG', 'OSS', 'MIT', 'NYU',
    'IDC', 'REA', 'IETF', 'AIMS', 'KYA', 'HR', 'SPIFFE', 'OS', 'SDK', 'AWS', 'IBM', 'AMD', 'VLA', 'WAIC',
    'H1', 'H2', 'R&D', 'M&A', 'FP&A', 'B2B', 'B2C', 'VC', 'TV', 'PR', 'IOT', 'DEI', 'ML', 'NLP', 'MOE',
    'RL', 'RLHF', 'OTEL', 'WORM', 'GPAI', 'CES', 'MVP', 'SLA', 'SOC', 'SOTA', 'OSS', 'GDP', 'ETF', 'PE',
    'AGI', 'ASI', 'ARC', 'NFT', 'DAO', 'EV', 'EVS', 'ESG', 'IT', 'OT', 'KPI', 'KPIS', 'OKR', 'F-16', 'X',
    'DMA', 'DSA', 'GDPR', 'HIPAA', 'FINRA', 'CPQ', 'BSS', 'OSS/BSS', 'ERP', 'SAP', 'MIT-LICENSED',
}

try:
    import statistics as _statistics
    from collections import Counter as _Counter
except ImportError:  # pragma: no cover
    _statistics = None
    _Counter = None


def _tokens(text: str) -> list[str]:
    return [w.strip("\"'“”‘’()[]{}.,;:!?…") for w in (text or '').split()]


def build_corpus(entry: dict | None = None, entries: list[dict] | None = None) -> dict:
    """Count how each word is cased in the entry's own prose (and, optionally,
    across all entries). Used to turn ALL-CAPS headlines back into the casing
    the author actually uses ("PALISADE" -> "Palisade", "REA" stays "REA")."""
    corpus: dict[str, _Counter] = {}

    def feed(text: str):
        for w in _tokens(text):
            if len(w) < 2 or not any(ch.isalpha() for ch in w):
                continue
            corpus.setdefault(w.lower(), _Counter())[w] += 1

    def feed_entry(e: dict):
        feed(e.get('focus_intro') or '')
        feed(e.get('market_signal') or '')
        va = e.get('viral_app') or {}
        feed(va.get('description') or '')
        for s in e.get('sections') or []:
            for p in s.get('paragraphs') or []:
                feed(p)
            for b in s.get('bullets') or []:
                feed(b)
        tk = e.get('practical_takeaway')
        if isinstance(tk, list):
            for t in tk:
                feed((t.get('title') or '') + ' ' + (t.get('body') or ''))
        elif isinstance(tk, str):
            feed(tk)

    for e in entries or []:
        feed_entry(e)
    if entry:
        feed_entry(entry)
    return corpus


def _corpus_casing(word: str, corpus: dict | None) -> str | None:
    """Most frequent casing of `word` seen in prose, or None if unseen.
    Sentence-initial capitals are discounted so 'The' doesn't beat 'the'."""
    if not corpus:
        return None
    c = corpus.get(word.lower())
    if not c:
        return None
    best = c.most_common()
    if len(best) >= 2 and best[0][0] == word.lower().capitalize() and best[1][0] == word.lower():
        # "The" 40 vs "the" 30 — prefer the plain lowercase form unless it is rare
        if best[1][1] * 2 >= best[0][1]:
            return best[1][0]
    return best[0][0]


def _recase_word(w: str, corpus: dict | None, first: bool, last: bool) -> str:
    """Title-case one token, keeping brand casing (OpenAI, GPT-6), acronyms and
    small words. ALL-CAPS tokens are re-cased from the prose corpus."""
    lead = re.match(r"^[\"'“‘(\[]*", w).group(0)
    trail = re.search(r"[\"'”’)\].,;:!?…]*$", w).group(0)
    core = w[len(lead):len(w) - len(trail)] if trail else w[len(lead):]
    if not core:
        return w
    low = core.lower()
    has_lower = any(ch.islower() for ch in core)
    has_upper = any(ch.isupper() for ch in core)
    small = (low in _SMALL_WORDS or low in {'yet', 'so'}) and not first and not last

    def cap(s: str) -> str:
        if '-' not in s:
            return s[:1].upper() + s[1:]
        parts = s.split('-')
        return '-'.join(p if (i > 0 and p in _SMALL_WORDS) else p[:1].upper() + p[1:] for i, p in enumerate(parts))

    seen = _corpus_casing(core, corpus)
    brand = bool(seen and seen.lower() == low and any(ch.isupper() for ch in seen[1:]) and seen != core.upper())
    if has_lower and has_upper:
        out = core                                        # OpenAI, GPT-6, ChatGPT's, MIT-licensed
    elif has_upper and not has_lower:                     # ALL CAPS (or a single capital letter)
        if core.upper() in _ACRONYMS or (len(core) == 1 and core.isalpha()):
            out = core
        elif seen == core.upper():
            out = core                                    # the prose writes it in caps too: an acronym
        elif brand:
            out = seen                                    # "OPENAI" -> "OpenAI"
        elif not seen and len(core) <= 3 and core.isalpha():
            out = core                                    # unknown short caps: assume acronym (NSA)
        else:
            out = low if small else cap(low)
    else:                                                 # all lowercase
        if small:
            out = low
        elif brand:
            out = seen                                    # "openai" -> "OpenAI"
        else:
            out = cap(low)
    if first and out[:1].islower():
        out = out[:1].upper() + out[1:]
    return lead + out + trail


def to_title_case(text: str, corpus: dict | None = None) -> str:
    """Headline casing with brand/acronym preservation."""
    words = text.split()
    n = len(words)
    out = []
    for i, w in enumerate(words):
        out.append(_recase_word(w, corpus, i == 0, i == n - 1))
    s = ' '.join(out)
    # Capitalise the first word after a colon / dash ("...Wheel: enterprise" -> "...Wheel: Enterprise")
    s = re.sub(r"([:–—]|--)\s+([a-z])", lambda m: f"{m.group(1)} {m.group(2).upper()}", s)
    return s


def is_shouting(text: str) -> bool:
    """True for ALL-CAPS phrases (three or more words, >=70% of letters upper-case)."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 8 or len(text.split()) < 3:
        return False
    upper = sum(1 for ch in letters if ch.isupper())
    return upper / len(letters) >= 0.7


def recase_heading(text: str, corpus: dict | None = None) -> str:
    """Turn 'AI SELF-REPLICATION: WHAT THE STUDY SHOWS' into title case, but
    leave mixed-case headings untouched. Keeps a leading 'N)' / 'N.' marker."""
    if not text or not is_shouting(text):
        return text
    m = re.match(r"^(\d{1,2}\s*[).:·\-—–]+\s*)(.*)$", text)
    prefix, body = (m.group(1), m.group(2)) if m else ('', text)
    return prefix + to_title_case(body, corpus)


def sentence_case(text: str) -> str:
    text = (text or '').strip()
    if not text:
        return text
    if is_shouting(text):
        text = text[:1].upper() + text[1:].lower()
    return text[:1].upper() + text[1:]


def tidy_deck(text: str, corpus: dict | None = None) -> str:
    """Deck line for display: 'AGENT FLEETS TAKE THE WHEEL: Enterprise AI…'
    becomes 'Agent Fleets Take the Wheel: Enterprise AI…'."""
    text = (text or '').strip()
    if not text:
        return text
    m = re.match(r"^([^:]{6,80}):\s+(.+)$", text)
    if m and is_shouting(m.group(1)):
        return to_title_case(m.group(1), corpus) + ': ' + m.group(2)
    return sentence_case(text)


def _join_headline(lines: list[str], hint: str = '') -> str:
    """Join the wrapped lines of a headline. Many PDFs set a headline and its
    sub-headline in the same font on consecutive lines; the stored title
    (hint) or a conservative heuristic decides whether the first break is a
    plain wrap (' ') or a headline/sub-headline break (' -- ')."""
    lines = [clean(l) for l in lines if clean(l)]
    if not lines:
        return ''
    if len(lines) == 1:
        head = lines[0]
    else:
        l1, l2 = lines[0], lines[1]
        sep = None
        if hint:
            m = re.search(re.escape(l1).replace(r'\ ', r'\s+'), hint, re.I)
            if m:
                after = hint[m.end():].lstrip()
                if re.match(r'^(?:--|—|–|:)', after):
                    sep = ' -- '
                elif after and l2 and after.lower().startswith(l2.split()[0].lower()):
                    sep = ' '
        if sep is None:
            sep = ' '                                     # a wrapped headline, by default
        head = l1 + sep + ' '.join([l2] + lines[2:])
    head = clean(head)
    head = re.sub(r'(\S)--(\S)', r'\1 -- \2', head)
    head = re.sub(r'\s*--\s*--\s*', ' -- ', head)
    return head


def extract_front_matter(pdf_path) -> dict:
    """Headline / deck / lede from page 1, using font sizes rather than text
    heuristics. Returns {'headline','generic','deck','lede','kicker'}; every
    value is '' when not found. Works across all the PDF layouts used since
    Day 61 (big headline + smaller deck, 'AI Learning — Day N' + deck line,
    kicker + headline, headline + 'Plus:' deck + meta line + lede)."""
    out = {'headline': '', 'generic': False, 'deck': '', 'lede': '', 'kicker': '', 'headline_lines': []}
    if _statistics is None:
        return out
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return out
            page = pdf.pages[0]
            raw = page.extract_text_lines(layout=False, strip=True, return_chars=True,
                                          x_tolerance=1.5, y_tolerance=3)
            ph = float(page.height)
    except Exception as exc:  # pragma: no cover - corrupt PDF
        print(f"   ⚠️  front matter extraction failed: {exc}")
        return out

    size_counter: _Counter = _Counter()
    lines: list[dict] = []
    for ln in raw:
        chars = [c for c in ln.get('chars', []) if (c.get('text') or '').strip()]
        if not chars:
            continue
        sizes = [round(float(c.get('size') or 0), 1) for c in chars]
        text = clean(ln.get('text', ''))
        if not text:
            continue
        size_counter.update(sizes)
        lines.append({'size': round(_statistics.median(sizes), 1), 'top': float(ln.get('top', 0)),
                      'bottom': float(ln.get('bottom', 0)), 'text': text})
    if not lines:
        return out
    body = size_counter.most_common(1)[0][0]
    lines.sort(key=lambda l: l['top'])

    def is_noise(t: str) -> bool:
        return bool(_RUNNING_HDR_RE.match(t) or _META_LINE_RE.match(t)
                    or t.upper().rstrip(':') in ("TODAY'S FOCUS", "TODAY'S TOPIC", "WHAT'S INSIDE"))

    def textish(t: str) -> bool:
        letters = sum(ch.isalpha() for ch in t)
        return letters >= 3 and letters >= len(t) * 0.4

    top = [l for l in lines if l['top'] < ph * 0.6]
    cands = [l for l in top if l['top'] < ph * 0.45 and not is_noise(l['text']) and textish(l['text'])]
    if not cands:
        return out
    # Headline = first run of lines at the largest text size. Stat strips
    # (big numbers) are not text-ish, so they never win.
    max_size = max(l['size'] for l in cands)
    if max_size < body * 1.15 and len(cands[0]['text']) > 120:
        return out                                        # nothing looks like a headline
    start = next(i for i, l in enumerate(top) if l in cands and l['size'] >= max_size - 0.3)
    group, i = [], start
    while i < len(top) and abs(top[i]['size'] - max_size) <= 0.6 and not is_noise(top[i]['text']):
        group.append(top[i]['text'])
        i += 1
    headline = _join_headline(group)
    generic = bool(_GENERIC_TITLE_RE.match(headline))
    out['headline'] = '' if generic else headline
    out['headline_lines'] = [] if generic else list(group)
    out['generic'] = generic
    out['kicker'] = clean(' '.join(l['text'] for l in top[:start]
                                   if not is_noise(l['text']) and textish(l['text']) and l['size'] > body + 0.5))

    # Deck = the run of lines right after the headline, until a meta line,
    # a section heading, a stat strip, or a change of font size.
    deck_lines: list[str] = []
    deck_size = None
    j = i
    while j < len(top):
        t, sz = top[j]['text'], top[j]['size']
        if _RUNNING_HDR_RE.match(t):
            j += 1
            continue
        if _META_LINE_RE.match(t) or t.upper().rstrip(':') in ("TODAY'S FOCUS", "TODAY'S TOPIC", "WHAT'S INSIDE"):
            if deck_lines:
                break
            j += 1
            continue
        if is_section_heading(t) or re.match(r'^\d{1,2}\)\s', t) or _GENERIC_TITLE_RE.match(t):
            break
        if not textish(t):
            break
        if _FOCUS_PREFIX_RE.match(t) and deck_lines:
            break
        if deck_size is None:
            deck_size = sz
        elif abs(sz - deck_size) > 0.6:
            break
        if deck_lines and top[j]['top'] - top[j - 1]['bottom'] > 14:
            break                                         # paragraph gap
        deck_lines.append(t)
        j += 1
        if sum(len(x) for x in deck_lines) > 1500:
            break
    deck = clean(' '.join(deck_lines))
    deck = _DATE_PREFIX_RE.sub('', deck)
    deck = _FOCUS_PREFIX_RE.sub('', deck).strip()
    deck = re.sub(r"^(?:--|—|–|-)\s*", '', deck).strip()
    if deck and len(deck) <= 380:
        out['deck'] = deck
        # Lede = next paragraph at body size
        lede_lines: list[str] = []
        k = j
        while k < len(top):
            t = top[k]['text']
            if _RUNNING_HDR_RE.match(t) or _META_LINE_RE.match(t) or t.upper().rstrip(':') in ("TODAY'S FOCUS", "TODAY'S TOPIC"):
                k += 1
                if lede_lines:
                    break
                continue
            if is_section_heading(t) or re.match(r'^\d{1,2}\)\s', t) or not textish(t):
                break
            if abs(top[k]['size'] - body) > 0.8:
                break
            if lede_lines and top[k]['top'] - top[k - 1]['bottom'] > 10:
                break
            lede_lines.append(t)
            k += 1
            if sum(len(x) for x in lede_lines) > 1500:
                break
        if (not deck and len(lede_lines) >= 2 and len(lede_lines[0]) < 70
                and not _ends_sentence(lede_lines[0]) and lede_lines[1][:1].isupper()):
            out['deck'] = lede_lines[0]                   # e.g. "Getting better without retraining the base model"
            lede_lines = lede_lines[1:]
        lede = clean(' '.join(lede_lines))
        out['lede'] = _FOCUS_PREFIX_RE.sub('', lede).strip()
    elif deck:
        out['lede'] = deck                                # too long for a deck: it is the lede
    if out['lede'][:1].islower():
        out['lede'] = out['lede'][:1].upper() + out['lede'][1:]
    if not out['deck'] and out['lede'] and len(out['lede']) < 130 and not _ends_sentence(out['lede']):
        out['deck'], out['lede'] = out['lede'], ''        # a short unpunctuated line under the headline is a deck
    return out


def headline_from_deck(deck: str) -> str:
    """First clause of a deck line, trimmed to headline length."""
    t = _DATE_PREFIX_RE.sub('', deck or '')
    t = _FOCUS_PREFIX_RE.sub('', t).strip()
    if not t:
        return ''
    cut = None
    for m in re.finditer(r"(\.\s|\?\s|!\s|\s--\s|\s—\s|;\s|,\s)", t):
        if m.start() >= 30:
            cut = m.start()
            break
    cand = t[:cut] if cut else t
    if len(cand) > 110:
        c2 = max(cand.rfind(', ', 0, 110), cand.rfind(' -- ', 0, 110), cand.rfind(': ', 0, 110))
        if c2 < 40:
            c2 = cand.rfind(' ', 0, 110)
        cand = cand[:c2]
    cand = re.sub(r"[\s,;:\-—–]+$", '', cand).strip()
    return cand


def extract_sources(all_flat_lines: list[str]) -> str:
    for i, ln in enumerate(all_flat_lines):
        m = re.match(r'^(?:[n•]\s+)?sources?\s*[:\-—–]\s*(.*)$', ln.strip(), re.I)
        if not m:
            continue
        parts = [m.group(1).strip()] if m.group(1).strip() else []
        for l in all_flat_lines[i + 1:i + 10]:
            l = l.strip()
            if _PAGE_HEADER_RE.match(l):
                continue
            if (_FOOTER_RE.search(l) or is_section_heading(l) or len(l) < 3
                    or re.match(r'^(topics covered|tomorrow|practical takeaway|market signal|self.test|quiz)', l, re.I)):
                break
            parts.append(l)
        txt = clean(' '.join(parts))
        if len(txt) > 20:
            return txt[:1500]
    return ''


def extract_tomorrow_block(all_flat_lines: list[str]) -> str:
    """The TOMORROW / 'What we're watching' box, as full sentences."""
    for i, ln in enumerate(all_flat_lines):
        t = ln.strip()
        if not re.match(r"^(?:[n•]\s+)?tomorrow(?:['’]s)?(?:\s*[-—–:]+\s*day\s*\d+\s*(?:preview)?)?\s*[:.]?\s*$", t, re.I):
            continue
        parts: list[str] = []
        for l in all_flat_lines[i + 1:i + 16]:
            l = l.strip()
            if _PAGE_HEADER_RE.match(l):
                continue
            if (_FOOTER_RE.search(l) or len(l) < 3
                    or re.match(r'^(topics covered|sources?\b|practical takeaway|market signal|recap|self.test|quiz)', l, re.I)
                    or (is_section_heading(l) and not re.match(r'^tomorrow', l, re.I))):
                break
            parts.append(l)
        txt = clean(' '.join(parts))
        txt = re.sub(r"^(?:what we.re watching|watching|next in the tech pipeline|tomorrow\s*[-—–:]+\s*day\s*\d+)\s*[:\-—–]*\s*",
                     '', txt, flags=re.I)
        txt = _trim_to_sentence(txt) or txt
        if len(txt) > 15:
            return txt[:1200]
    return ''


def extract_recap(all_flat_lines: list[str]) -> str:
    """'Topics covered so far' recap paragraph (a running curriculum map)."""
    for i, ln in enumerate(all_flat_lines):
        m = re.match(r'^(?:[n•]\s+)?topics covered so far\s*(?:\([^)]*\))?\s*[:\-—–]?\s*(.*)$', ln.strip(), re.I)
        if not m:
            continue
        parts = [m.group(1).strip()] if m.group(1).strip() else []
        for l in all_flat_lines[i + 1:i + 24]:
            l = l.strip()
            if _PAGE_HEADER_RE.match(l):
                continue
            if (_FOOTER_RE.search(l) or len(l) < 3 or re.match(r'^(sources?\s*[:\-]|tomorrow|self.test|quiz)', l, re.I)
                    or (is_section_heading(l) and not is_bullet(l))):
                break
            parts.append(l)
        txt = clean(' '.join(parts))
        if len(txt) > 40:
            return txt[:2500]
    return ''


def match_themes(text: str) -> list[str]:
    found: list[str] = []
    for raw in re.split(r'[,;/|·•]+', text or ''):
        key = re.sub(r'\s+', ' ', raw.strip().lower().strip('.'))
        if not key:
            continue
        th = _THEME_ALIASES.get(key)
        if not th:
            for alias, theme in _THEME_ALIASES.items():
                if alias in key:
                    th = theme
                    break
        if th and th not in found:
            found.append(th)
    return sorted(found, key=THEMES.index)[:2]


def extract_themes(all_flat_lines: list[str]) -> list[str]:
    for ln in all_flat_lines[:120]:
        m = re.match(r'^(?:[n•]\s+)?themes?\s*:\s*(.+)$', ln.strip(), re.I)
        if m:
            themes = match_themes(m.group(1))
            if themes:
                return themes
    return []


def extract_quiz(all_flat_lines: list[str]) -> list[dict]:
    """SELF-TEST block: 'Q1. question' / 'A1. answer' pairs (answers may wrap)."""
    for i, ln in enumerate(all_flat_lines):
        if not re.match(r'^(?:[n•]\s+)?(self[- ]test|quiz|test yourself|check your understanding)\s*[:.]?\s*$', ln.strip(), re.I):
            continue
        items: list[dict] = []
        cur: dict | None = None
        for l in all_flat_lines[i + 1:i + 80]:
            l = l.strip()
            if _PAGE_HEADER_RE.match(l):
                continue
            if (_FOOTER_RE.search(l) or is_section_heading(l)
                    or re.match(r'^(topics covered|sources?\b|tomorrow|practical takeaway|market signal)', l, re.I)):
                break
            mq = re.match(r'^(?:[n•]\s+)?Q(?:\d{1,2})?\s*[.):]\s*(.+)$', l, re.I)
            ma = re.match(r'^(?:[n•]\s+)?A(?:\d{1,2})?\s*[.):]\s*(.+)$', l, re.I)
            if mq:
                cur = {'q': clean(mq.group(1)), 'a': ''}
                items.append(cur)
            elif ma and cur is not None:
                cur['a'] = clean(ma.group(1))
            elif cur is not None and len(l) > 2:
                if cur['a']:
                    cur['a'] = clean(cur['a'] + ' ' + l)
                else:
                    cur['q'] = clean(cur['q'] + ' ' + l)
        items = [it for it in items if it['q'] and it['a']]
        if items:
            return items[:10]
    return []


_VIRAL_PREFIX_RE = re.compile(
    r"^(?:viral app\s*)?(?:of the day\s*[:\-—–]*\s*)?(?:(?:today.s pick|spotlight|pick)\s*:\s*)?", re.I)


def normalize_viral(v: dict | None) -> dict | None:
    """Re-split a viral-app name that ran into its description at a PDF line
    break. The concatenation name+description is preserved exactly; only the
    split point (and a leading 'Today's pick:' label) changes."""
    if not v or not isinstance(v, dict) or not v.get('name'):
        return v
    name = clean(v.get('name') or '')
    desc = clean(v.get('description') or '')
    stripped = _VIRAL_PREFIX_RE.sub('', name).strip() if len(name) > 12 else name
    if stripped and len(stripped) >= 3:
        name = stripped
    if len(name) > 70 and desc and not desc.lower().startswith(name.lower()[:30]):
        full = name + ' ' + desc
        cut = None
        for m in re.finditer(r"(\.\s(?=[A-Z\"'(])|\s--\s|\s—\s|:\s)", full):
            if 20 <= m.start() <= 120:
                cut = m.start()
                break
        if cut is None:
            for m in re.finditer(r",\s", full):
                if 25 <= m.start() <= 90:
                    cut = m.start()
                    break
        if cut is None:
            cut = full.rfind(' ', 0, 100)
        if cut and cut > 10:
            name, desc = full[:cut].strip(), full[cut:].strip()
            desc = re.sub(r"^[.,:;\-—–\s]+", '', desc)
    name = re.sub(r"[\s,:;\-—–]+$", '', name)
    if name[:1].islower():
        name = name[:1].upper() + name[1:]
    out = dict(v)
    out['name'] = name
    out['description'] = desc
    return out


def _norm_text(s: str) -> str:
    return re.sub(r'\W+', ' ', (s or '').lower()).strip()


def dedupe_intro(entry: dict, lede: str = '') -> bool:
    """If focus_intro repeats the first body paragraph, keep the text once.
    Returns True when the entry changed. No text is dropped: the longer of
    the two copies survives (as the body paragraph), the intro becomes the
    PDF lede when one is available, else empty (the subtitle fills the slot)."""
    intro = entry.get('focus_intro') or ''
    secs = entry.get('sections') or []
    paras = (secs[0].get('paragraphs') or []) if secs else []
    first = paras[0] if paras else ''
    ni, nf = _norm_text(intro), _norm_text(first)
    if not ni or not nf:
        return False
    if not (ni == nf or nf.startswith(ni[:150]) or ni.startswith(nf[:150])):
        return False
    if len(ni) > len(nf):
        paras[0] = intro                                   # longer copy wins, nothing lost
    nl = _norm_text(lede)
    if nl and nl != _norm_text(paras[0]) and not _norm_text(paras[0]).startswith(nl[:150]):
        entry['focus_intro'] = lede
    else:
        entry['focus_intro'] = ''
    return True


_DANGLING_RE = re.compile(
    r"(?:^|\s)(?:a|an|the|of|to|for|and|or|but|nor|so|with|without|in|on|at|by|from|into|onto|over|under|"
    r"after|before|between|through|your|our|their|its|his|her|is|are|was|were|be|as|that|this|these|those|"
    r"not|no|if|than|then|which|who|whom|how|why|what|when|where|while|vs\.?|&|--|—|-)$", re.I)


def title_problem(title: str) -> str:
    """Why a stored title is unusable ('' when it is fine)."""
    t = (title or '').strip()
    if not t:
        return 'empty'
    if _GENERIC_TITLE_RE.match(t) or re.match(r'^ai learning\s*[-—–]+\s*day\s*\d+', t, re.I):
        return 'generic'
    if re.search(r'varunsingla\.com|agentic ai series|learning series|agentic ai daily', t, re.I):
        return 'header'
    if re.match(r'^(day\s*\d+\s*[|•·]|\w+ \d{1,2}, \d{4}\s*[|•·])', t, re.I):
        return 'header'
    if re.match(r'^[a-z]', t):
        return 'fragment'
    if re.match(r'^(today we|if the last|yesterday|this week|just shipped)\b', t, re.I) and not re.search(r'[.!?]$', t):
        return 'fragment'
    if _DANGLING_RE.search(t) or t.endswith((',', ':', ';')):
        return 'truncated'
    if len(t) > 95 and not re.search(r"[.!?]$", t) and re.match(r'^(today we|if the|three stories|yesterday)', t, re.I):
        return 'fragment'
    if len(t) > 140:
        return 'fragment'
    return ''


def _entry_text(entry: dict) -> str:
    parts = [entry.get('focus_intro') or '', entry.get('market_signal') or '']
    for s in entry.get('sections') or []:
        parts.extend(s.get('paragraphs') or [])
        parts.extend(s.get('bullets') or [])
    return ' '.join(parts)


_BOILERPLATE_HEADING_RE = re.compile(
    r"(viral|takeaway|market signal|today.s focus|what.s inside|tomorrow|sources|recap|by the numbers|"
    r"key stats|at a glance|what is it\??$)", re.I)


def _heading_as_title(entry: dict, corpus: dict | None) -> str:
    for s in entry.get('sections') or []:
        h = (s.get('title') or '').strip()
        h = re.sub(r"^\d{1,2}\s*[).:·\-—–]+\s*", '', h)
        if 10 <= len(h) <= 100 and not _BOILERPLATE_HEADING_RE.search(h) and not _DANGLING_RE.search(h):
            return to_title_case(h, corpus)
    return ''


def repair_title_from_json(entry: dict, corpus: dict | None) -> str:
    """Best-effort headline for an entry whose PDF is not on disk."""
    t = (entry.get('title') or '').strip()
    problem = title_problem(t)
    if not problem:
        return ''
    if problem == 'header':
        segs = [s.strip() for s in re.split(r'\s*[|•·]\s*', t) if s.strip()]
        segs = [s for s in segs
                if not re.match(r'^(day\s*\d+|\w+ \d{1,2}, \d{4}|agentic ai.*series.*|.*varunsingla\.com.*)$', s, re.I)]
        if segs and 10 <= len(segs[0]) <= 100:
            seg = to_title_case(segs[0], corpus) if is_shouting(segs[0]) else segs[0]
            if title_problem(seg) == 'truncated':
                t, problem = seg, 'truncated'          # fall through to the truncation fix
            else:
                return seg
        else:
            return _heading_as_title(entry, corpus)
    if problem == 'truncated':
        stem = _DAY_PREFIX_RE.sub('', t)
        words = stem.split()
        if len(words) >= 4:
            tail = ' '.join(words[-4:])
            text = _entry_text(entry)
            idx = text.lower().find(tail.lower())
            if idx >= 0:
                rest = text[idx + len(tail):]
                m = re.match(r"^([^.!?;:\n]{1,80}?)(?=[.,;:!?]|\s--\s|\s—\s|$)", rest)
                if m and m.group(1).strip():
                    cand = clean(stem + m.group(1))
                    cand = re.sub(r"[\s,;:\-—–&]+$", '', cand)
                    if len(cand) <= 120 and not _DANGLING_RE.search(cand):
                        return cand
        cand = re.sub(r"[\s,;:]*(?:--|—|-|&|\b\w{1,5})$", '', stem).strip() if _DANGLING_RE.search(stem) else stem
        cand = re.sub(r"[\s,;:\-—–&]+$", '', cand)
        if len(cand) >= 25 and not _DANGLING_RE.search(cand):
            return cand
        return _heading_as_title(entry, corpus) or cand
    # generic / fragment
    return _heading_as_title(entry, corpus)


# Hand-checked titles for early entries whose PDF is no longer on disk and
# whose stored title was a header artifact or a cut-off lede. Each one reuses
# the entry's own wording (lede, section headings, takeaways); the stored
# title is kept under title_original.
TITLE_OVERRIDES = {
    '2026-03-25': 'Production Multi-Agent Systems',
    '2026-04-06': 'Attie by Bluesky -- The First Agentic AI App to Go Viral',
    '2026-04-14': 'Self-Healing Agents in Production: Circuit Breakers and Drift Detection',
    '2026-04-20': 'The Future of Work in an Agentic Economy',
    '2026-04-21': 'The Open-Source Agent Stack: Open Source vs Proprietary in 2026',
    '2026-04-27': 'Agentic AI Crosses Into Hospital Wards, Pharma Pipelines, and Clinical Workflows',
    '2026-04-28': 'The Agent Economy Meets Climate & Energy',
    '2026-04-29': 'Which Roles Are Exploding in Demand -- and How to Position Yourself',
    '2026-05-07': 'Beyond LLM-as-Judge: Trajectory Evals & Continuous Production Monitoring',
    '2026-05-08': 'Anthropic Finance Agents',
    '2026-05-14': 'From SPIFFE Workload Identity to Know Your Agent (KYA) and the IETF AIMS Framework',
    '2026-05-19': 'Google I/O 2026 -- Gemini Spark & the Big Tech Agentic Pivot',
    '2026-05-21': "The Agentic Enterprise Buyer's Checklist",
    '2026-05-24': 'Head-to-Head Economics, Take Rates, and Discovery Across the Five Major Agent Channels',
    '2026-05-28': 'Agentic AI in Manufacturing & Industrial Operations',
    '2026-05-30': 'Agentic AI in Marketing & Customer Experience',
    '2026-06-10': 'Agentic AI in Scientific Research & Discovery',
}


def _store_original(entry: dict, field: str, old_value) -> None:
    key = f'{field}_original'
    if old_value and key not in entry:
        entry[key] = old_value


def repair_entry(entry: dict, pdf_path=None, global_corpus: dict | None = None) -> list[str]:
    """Idempotent in-place repair of one stored entry. Returns a list of what
    changed. Nothing is ever deleted: replaced titles/intros go to
    *_original, viral names are only re-split, headings only re-cased."""
    changes: list[str] = []
    corpus = build_corpus(entry)
    if global_corpus:
        for k, c in global_corpus.items():
            corpus.setdefault(k, _Counter()).update(c)

    old_title = (entry.get('title') or '').strip()
    fm = extract_front_matter(pdf_path) if pdf_path else {}
    new_title = ''
    override = TITLE_OVERRIDES.get(entry.get('date', ''))
    if override and not pdf_path:
        new_title = override
    subtitle = (entry.get('subtitle') or '').strip()
    lede = fm.get('lede', '') if fm else ''

    if fm and fm.get('headline'):
        head = _join_headline(fm.get('headline_lines') or [fm['headline']], hint=old_title) or fm['headline']
        head = to_title_case(head, corpus) if is_shouting(head) else head
        head = re.sub(r"\s*--\s*$", '', head).strip()
        deck = fm.get('deck', '')
        problem = title_problem(old_title)
        old_norm, head_norm = _norm_text(old_title), _norm_text(head)
        if (problem or old_norm.startswith(head_norm[:40]) or head_norm.startswith(old_norm[:40])
                or (deck and old_norm.startswith(_norm_text(deck)[:40]))):
            new_title = head
        if deck and not subtitle:
            subtitle = tidy_deck(deck, corpus)
        elif not deck and fm.get('kicker') and not subtitle and len(fm['kicker']) < 90:
            subtitle = fm['kicker']
    elif fm and (fm.get('deck') or lede):
        deck = fm.get('deck') or ''
        base = deck or (re.split(r'(?<=[.!?])\s', lede)[0] if lede else '')
        cand = headline_from_deck(base)
        if cand:
            new_title = to_title_case(cand, corpus)
        if deck and not subtitle:
            subtitle = tidy_deck(deck, corpus)

    if not new_title and not override and title_problem(old_title):
        new_title = repair_title_from_json(entry, corpus)
    if not new_title and old_title:
        stripped = _DAY_PREFIX_RE.sub('', old_title).strip()
        if stripped != old_title and len(stripped) >= 10:
            new_title = stripped
        elif is_shouting(old_title):
            new_title = to_title_case(old_title, corpus)
    if new_title:
        new_title = re.sub(r'\s*--\s*--\s*', ' -- ', new_title)
        new_title = _DAY_PREFIX_RE.sub('', new_title).strip()
        new_title = re.sub(r"[\s,;:\-—–]+$", '', new_title)
    if new_title and new_title != old_title and len(new_title) >= 8:
        _store_original(entry, 'title', old_title)
        entry['title'] = new_title
        changes.append(f"title: {old_title[:60]!r} -> {new_title[:60]!r}")
    if subtitle and subtitle != (entry.get('subtitle') or '') and _norm_text(subtitle) != _norm_text(entry['title']):
        entry['subtitle'] = subtitle
        changes.append('subtitle')

    # Intro: fix a mid-sentence fragment using the PDF lede, then de-duplicate.
    intro = entry.get('focus_intro') or ''
    if lede and intro:
        ni, nl = _norm_text(intro), _norm_text(lede)
        if ni != nl and (intro[:1].islower() or ni[:60] in nl or nl.endswith(ni[-80:])):
            if ni not in nl:
                _store_original(entry, 'focus_intro', intro)
            entry['focus_intro'] = lede
            changes.append('focus_intro from lede')
    elif lede and not intro:
        entry['focus_intro'] = lede
        changes.append('focus_intro from lede')
    if dedupe_intro(entry, lede):
        changes.append('intro de-duplicated')

    # Section headings: ALL CAPS -> title case.
    for s in entry.get('sections') or []:
        h = s.get('title') or ''
        nh = recase_heading(h, corpus)
        if nh != h:
            s['title'] = nh
            changes.append('heading recased')

    # Viral app: re-split a name that ran into its description.
    v = entry.get('viral_app')
    nv = normalize_viral(v)
    if nv and nv != v:
        entry['viral_app'] = nv
        changes.append('viral app re-split')

    # Sources / watch list / recap / themes / quiz from the PDF text.
    if pdf_path:
        try:
            flat = _flat_lines_for_repair(pdf_path)
        except Exception:
            flat = []
        if flat:
            if not entry.get('sources'):
                src = extract_sources(flat)
                if src:
                    entry['sources'] = src
                    changes.append('sources')
            tm = extract_tomorrow_block(flat)
            old_tm = entry.get('tomorrow_preview') or ''
            if tm and (not old_tm or (len(tm) > len(old_tm) and _norm_text(old_tm)[:40] in _norm_text(tm))):
                if old_tm and _norm_text(old_tm) not in _norm_text(tm):
                    _store_original(entry, 'tomorrow_preview', old_tm)
                entry['tomorrow_preview'] = tm
                changes.append('watch list')
            if not entry.get('recap'):
                rc = extract_recap(flat)
                if rc:
                    entry['recap'] = rc
                    changes.append('recap')
            if not entry.get('themes'):
                th = extract_themes(flat)
                if th:
                    entry['themes'] = th
                    changes.append('themes')
            if not entry.get('quiz'):
                qz = extract_quiz(flat)
                if qz:
                    entry['quiz'] = qz
                    changes.append('quiz')
    entry['schema'] = SCHEMA_VERSION
    return changes


def _flat_lines_for_repair(pdf_path) -> list[str]:
    """Plain text lines of every page (no table exclusion) for the block extractors."""
    lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ''
            lines.extend(clean(l) for l in txt.split('\n') if clean(l) and len(clean(l)) > 1)
    return lines


def pdf_lookup(root: Path | None = None) -> dict[str, Path]:
    """date -> PDF path for every daily PDF on disk (repo root + workspace)."""
    found: dict[str, Path] = {}
    roots = [root or SCRIPT_DIR]
    if WORKSPACE_DIR.exists() and WORKSPACE_DIR != (root or SCRIPT_DIR):
        roots.append(WORKSPACE_DIR)
    for base in roots:
        try:
            paths = sorted(base.glob('**/*.pdf'))
        except OSError:
            continue
        for p in paths:
            stem = p.stem.lower()
            if sum(1 for k in ('daily', 'learning', 'ai', 'trends') if k in stem) < 2:
                continue
            dt = extract_date_from_filename(p.stem)
            if dt:
                found.setdefault(dt.strftime('%Y-%m-%d'), p)
    return found


def repair_all(data: dict, root: Path | None = None, force: bool = False, verbose: bool = True) -> list[tuple[str, list[str]]]:
    """Run repair_entry over every stored entry that has not been repaired at
    the current SCHEMA_VERSION. Cheap when everything is already current."""
    entries = [e for e in data.get('learnings', []) if e.get('title')]
    todo = [e for e in entries if force or int(e.get('schema') or 0) < SCHEMA_VERSION]
    if not todo:
        return []
    pdfs = pdf_lookup(root)
    global_corpus = build_corpus(entries=entries)
    report: list[tuple[str, list[str]]] = []
    for e in todo:
        changes = repair_entry(e, pdfs.get(e['date']), global_corpus)
        if changes:
            report.append((e['date'], changes))
            if verbose:
                print(f"   🔧 {e['date']}: {', '.join(changes)[:160]}")
    return report



def parse_pdf(pdf_path: Path) -> dict:
    """Parse a daily AI learning PDF into a rich structured dict.

    v4 — complete rewrite fixing:
      1. 2-column layout: uses left-column word extraction for bullets, not flat text
      2. Stat boxes: correctly splits number+label from multi-line cells
      3. Viral app: scans all tables for 'VIRAL APP OF THE DAY' header
      4. Takeaways: extracts from last-page 2-column table, not just section headings
      5. Tables: assigned by proximity (same page, after section heading) not greedy pop
      6. focus_intro: falls back to PDF subtitle / first section paragraph
      7. Issue number: extracted from 'Day N' pattern as well as 'Issue #N'
    """
    print(f"   📄 Parsing: {pdf_path.name}")

    # ── Per-page data collection ───────────────────────────────────────────────
    # page_data[i] = {'lines': [...], 'tables': [...], 'left_lines': [...]}
    page_data: list[dict] = []
    all_flat_lines: list[str] = []   # full-page text lines (for fallback patterns)

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tbls = _page_tables_with_bbox(page)

            # Build table bounding boxes for exclusion
            table_bboxes = [t['bbox'] for t in tbls]

            def _not_in_table(obj):
                ox0, ot = obj.get('x0', 9999), obj.get('top', 9999)
                ox1, ob = obj.get('x1', 0), obj.get('bottom', 0)
                for (tx0, tt, tx1, tb) in table_bboxes:
                    if ox0 >= tx0 - 2 and ox1 <= tx1 + 2 and ot >= tt - 2 and ob <= tb + 2:
                        return False
                return True

            # Detect orphan box-headers: a table row whose entire cell content
            # (no attached body text) is just a known section header. Usually
            # the actual title/body lives in the plain text that follows,
            # outside the table, so we reinsert the header at its true
            # y-position. But sometimes pdfplumber groups the header AND the
            # title/body into the SAME table (header alone in row 0, title +
            # paragraph glued into one multi-line cell in row 1+) — in that
            # case the body never appears in the plain page text at all, so
            # we must also reinsert those other rows (split back into their
            # original lines) or their content is silently lost.
            orphan_markers: list[tuple[float, str]] = []
            for t in tbls:
                row_bboxes = t.get('row_bboxes') or []
                header_rows = {
                    ri for ri, row in enumerate(t['data'])
                    if _SPECIAL_HEADER_RE.match(clean(' '.join(str(c) for c in row if c)).strip())
                }
                if not header_rows:
                    continue
                for ri, row in enumerate(t['data']):
                    if ri >= len(row_bboxes) or not row_bboxes[ri]:
                        continue
                    y0 = row_bboxes[ri][1]
                    if ri in header_rows:
                        cell_text = clean(' '.join(str(c) for c in row if c))
                        orphan_markers.append((y0, cell_text.upper()))
                    else:
                        raw_cell = ' '.join(str(c) for c in row if c)
                        for j, sub in enumerate(raw_cell.split('\n')):
                            sub_c = clean(sub)
                            if sub_c:
                                orphan_markers.append((y0 + j * 0.01, sub_c))

            # Full-page text outside tables
            if orphan_markers:
                word_lines = _text_lines_with_y(page, _not_in_table)
                merged = sorted(word_lines + orphan_markers, key=lambda x: x[0])
                lines = [clean(t) for (_, t) in merged if clean(t) and len(clean(t)) > 1]
            elif table_bboxes:
                page_text = page.filter(_not_in_table).extract_text(x_tolerance=1.5, y_tolerance=3) or ""
                lines = [clean(ln) for ln in page_text.split('\n') if clean(ln) and len(clean(ln)) > 1]
            else:
                page_text = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
                lines = [clean(ln) for ln in page_text.split('\n') if clean(ln) and len(clean(ln)) > 1]
            all_flat_lines.extend(lines)

            # Left-column lines for bullet extraction (skip top 15% = header region)
            top_skip = page.height * 0.15
            left_lines = _left_col_lines(page, top_skip=top_skip)

            page_data.append({'lines': lines, 'tables': tbls, 'left_lines': left_lines})

    if not all_flat_lines:
        print(f"   ⚠️  No text extracted from {pdf_path.name}")
        return {}

    full_text = " ".join(all_flat_lines)
    # Strip the per-page running footer ("Varun Singla · Daily AI Learning ·
    # Day N · varunsingla.com Page M"), which survives the space-join and
    # lands mid-sentence whenever a box's text spans a page break.
    full_text = re.sub(r'\bvarun singla\b.*?\bpage\s*\d+\b', ' ', full_text, flags=re.I)

    # Collect all raw table data (for fallback searches)
    all_tables: list[list[list]] = [t['data'] for pd in page_data for t in pd['tables']]

    # ── Date & issue ───────────────────────────────────────────────────────────
    header_text = " ".join(all_flat_lines[:10])
    date_str, display_date, issue = parse_date_from_text(header_text)
    if not date_str:
        date_str, display_date, issue = parse_date_from_text(full_text[:800])

    # Also extract issue from "Day N" pattern (e.g. "Day 20")
    if not issue:
        m = re.search(r'\bDay\s+(\d+)\b', full_text[:600], re.I)
        if m:
            issue = int(m.group(1))

    # ── Title ─────────────────────────────────────────────────────────────────
    _title_skip = re.compile(
        r"(ai daily|daily ai|daily brief|varun singla|issue|edition|your daily dose|curated|"
        r"page \d|what.s inside|what.s shaping|breakthroughs & trends|"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)[,\s])",
        re.I,
    )

    def _strip_trailing_date(s: str) -> str:
        return re.sub(
            r"[.·,\s]+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
            r"\s+\d{4}\s*$", "", s, flags=re.I
        ).strip()

    title = ""
    subtitle = ""
    # Strategy 0 (v5): read the headline / deck straight off page 1 by font
    # size. This is layout-independent and is what fixes the "AI Learning --
    # Day N" and "three stories about…" titles of the older text heuristics.
    fm = extract_front_matter(pdf_path)
    fm_lede = fm.get('lede', '')
    fm_used = False
    if fm.get('headline'):
        title = fm['headline']
        subtitle = fm.get('deck', '') or (fm.get('kicker', '') if 0 < len(fm.get('kicker', '')) < 90 else '')
        fm_used = True
    elif fm.get('generic') and (fm.get('deck') or fm_lede):
        base = fm.get('deck') or re.split(r'(?<=[.!?])\s', fm_lede)[0]
        title = headline_from_deck(base)
        subtitle = fm.get('deck', '')
        fm_used = bool(title)
    # Strategy 1a: "TODAY'S DEEP DIVE: X" or "Today's Focus: X" — scan wider (up to 30 lines)
    for line in ([] if title else all_flat_lines[:30]):
        low = line.lower()
        if re.search(r"today.s (focus|topic|deep dive)\s*:", low):
            m = re.match(r"today.s (?:focus|topic|deep dive)\s*:\s*(.+)", line, re.I)
            if m:
                raw = m[1].strip()
                if raw[:1].islower():
                    # "Today's focus: three stories about…" is the lede, not a title
                    continue
                parts = re.split(r'\s*\+\s*', raw)
                first = parts[0].strip()
                if len(first) < 12 and len(parts) > 1:
                    first = raw
                candidate = _strip_trailing_date(first[:120])
                if len(candidate) > 15:
                    title = candidate
                    break
        if re.search(r"what.s inside", low):
            break

    # Strategy 1b: first substantial non-header line on page 1
    if not title:
        prev_was_stats = False
        for line in all_flat_lines[:30]:
            low = line.lower()
            if re.search(r"what.s inside", low):
                break
            if len(line) > 20 and not _title_skip.search(line):
                # Skip pure numeric lines
                if re.match(r'^[\d\s\$£€%+KMBTx,\.]+$', line):
                    prev_was_stats = True
                    continue
                # Skip stat box rows (3+ numbers in a short line)
                if len(re.findall(r'\d+[KMB%+]?', line)) >= 3 and len(line) < 70:
                    prev_was_stats = True
                    continue
                # Skip stat label rows: lines that are ONLY stat labels without verbs/prepositions
                # e.g. "Days Learning Mem0 GitHub Stars MCP Installs Gemma 4 Dense Params"
                if re.search(r'(github stars|mcp installs|dense params|days learning|weekly users|monthly users)', line, re.I):
                    prev_was_stats = False
                    continue
                # Skip the label row that follows a stat row (e.g. "Days Learning Mem0 GitHub Stars...")
                if prev_was_stats and re.search(r'(stars|installs|params|days|users|downloads)', line, re.I):
                    prev_was_stats = False
                    continue
                prev_was_stats = False
                candidate = re.sub(r'^[n•]+\s+', '', line).strip()
                candidate = _strip_trailing_date(candidate)
                if len(candidate) > 15:
                    title = candidate
                    break

    # Strip leading bullet/number artifacts from title
    if title:
        title = re.sub(r'^[n•·\-]+\s*', '', title).strip()
        # Remove "Day N · DD Month YYYY" style date suffixes at end
        title = re.sub(r'\s*·?\s*\d{1,2}\s+(January|February|March|April|May|June|July|August|'
                       r'September|October|November|December)\s+\d{4}.*$', '', title, flags=re.I).strip()
        # If title still looks like a header artifact (all-caps, very short, or contains day/date pattern)
        if re.match(r'^(AGENTIC AI|AI DAILY|DAILY AI|DAY \d)', title, re.I) and len(title) < 40:
            title = ''  # will fall through to subtitle strategy

    # Strategy 1c: append the deck/subtitle line that follows the title on
    # page 1 (Day ~100+ layout: "Self-Improving Agents 2.0" newline
    # "Getting better without retraining the base model").
    if title and not fm_used and ' -- ' not in title and '—' not in title:
        p1 = page_data[0]['lines']
        for k, ln in enumerate(p1):
            if ln.strip().startswith(title[:40]):
                if k + 1 < len(p1):
                    sub = re.sub(r'^[n•]+\s+', '', p1[k + 1]).strip()
                    # A deck line is short, unpunctuated, and not the lede
                    if (15 < len(sub) < 80
                            and not _title_skip.search(sub)
                            and not is_section_heading(sub)
                            and not _ends_sentence(sub)
                            and not re.search(r'\d{4}', sub)
                            and len(title) + len(sub) < 150):
                        title = f"{title} -- {_smart_title_case(sub)}"
                break

    # Strategy 2: PDF subtitle (line 2 of page 1, if concise and title-cased)
    if not title and len(page_data[0]['lines']) >= 2:
        for ln in page_data[0]['lines'][1:5]:
            ln_clean = re.sub(r'^[n•]+\s+', '', ln).strip()
            if (20 < len(ln_clean) < 120
                    and not _title_skip.search(ln_clean)
                    and not re.search(r'\d{4}', ln_clean)):
                title = _strip_trailing_date(ln_clean)
                break

    # ── Today's Focus intro paragraph ─────────────────────────────────────────
    focus_intro = ""
    for i, line in enumerate(all_flat_lines):
        low = line.lower()
        if re.search(r"today.s (focus|topic)", low):
            inline_m = re.match(r"today.s (?:focus|topic)\s*:\s*(.+)", line, re.I)
            if inline_m:
                intro_parts = [inline_m[1].strip()] if len(inline_m[1].strip()) > 20 else []
                in_yesterday = False
                for j in range(i + 1, min(i + 14, len(all_flat_lines))):
                    l = all_flat_lines[j]
                    if is_section_heading(l) or re.search(r"what.s inside", l, re.I):
                        break
                    if re.search(r"yesterday.s recap", l, re.I):
                        in_yesterday = True
                    if re.match(r"^\+\s*(viral app|industry|also)", l, re.I):
                        continue
                    if re.match(r'^[•*]\s+[A-Z][A-Z\s]{4,}(?:--|—|-|\Z)', l):
                        break
                    if in_yesterday:
                        today_m = re.search(r'(?:^|\.)\s*(Today\s+we\s+.{15,})', l, re.I)
                        if today_m:
                            intro_parts.append(today_m[1].strip())
                            in_yesterday = False
                        continue
                    if len(l) > 40:
                        intro_parts.append(l)
                    if len(intro_parts) >= 3:
                        break
                if intro_parts:
                    focus_intro = " ".join(intro_parts)
                else:
                    focus_intro = inline_m[1].strip()
            else:
                intro_parts = []
                for j in range(i + 1, min(i + 6, len(all_flat_lines))):
                    l = all_flat_lines[j]
                    if is_section_heading(l) or re.search(r"what.s inside", l, re.I):
                        break
                    if len(l) > 30:
                        intro_parts.append(l)
                focus_intro = " ".join(intro_parts)
            break

    # Fallback: use the PDF lede paragraph (lines after the title). The lede
    # wraps across several PDF lines, so keep appending continuation lines
    # until the text reads as complete sentences or a heading interrupts.
    if not focus_intro:
        p1_lines = page_data[0]['lines']
        for k in range(1, min(6, len(p1_lines))):
            ln = re.sub(r'^[n•]+\s+', '', p1_lines[k]).strip()
            if len(ln) > 60 and not _title_skip.search(ln) and not re.search(r'\d{4}', ln):
                parts = [ln]
                for nxt in p1_lines[k + 1:k + 12]:
                    nxt = nxt.strip()
                    if (is_section_heading(nxt) or re.search(r"what.s inside", nxt, re.I)
                            or len(nxt) < 25):
                        break
                    parts.append(nxt)
                    if _ends_sentence(nxt):
                        break
                focus_intro = " ".join(parts)
                break

    # Fallback: use first section paragraph (same continuation handling)
    if not focus_intro:
        for idx in range(5, min(30, len(all_flat_lines))):
            l = all_flat_lines[idx]
            if len(l) > 80 and not is_section_heading(l) and not _title_skip.search(l):
                parts = [l]
                for nxt in all_flat_lines[idx + 1:idx + 12]:
                    nxt = nxt.strip()
                    if is_section_heading(nxt) or len(nxt) < 25:
                        break
                    parts.append(nxt)
                    if _ends_sentence(nxt):
                        break
                focus_intro = " ".join(parts)
                break

    # ── Stats box ─────────────────────────────────────────────────────────────
    # Find the 4-cell stat box on page 1 — it's always a single-row, 4-column table
    stats: list[dict] = []
    for tbl in page_data[0]['tables']:
        if _is_stat_box(tbl['data']):
            for cell in tbl['data'][0]:
                s = _clean_stat_cell(str(cell) if cell else '')
                if s:
                    stats.append(s)
            if stats:
                break

    # ── Numbered takeaways (Day ~100+ layout) ─────────────────────────────────
    # Extract BEFORE sections so the numbered takeaway items ("1. Improve …")
    # are not misread as content sections.
    numbered_takeaways, takeaway_region = _extract_numbered_takeaways(all_flat_lines)

    # ── Build sections: per-page, using left-column bullets ───────────────────
    # Strategy: scan all_flat_lines for section headings, but get bullets from
    # left-column word extraction on the matching page.
    #
    # Map each heading line to its page number by scanning page_data.
    def _heading_page(heading: str) -> int | None:
        for pi, pd in enumerate(page_data):
            if any(heading in ln for ln in pd['lines']):
                return pi
        return None

    sections: list[dict] = []
    used_tables: set[int] = set()   # id()s of tables already attached to a section
    skip_headings = re.compile(
        r"^\s*(?:n\s+)?(today.s (focus|topic)|what.s inside|ai daily learning|daily ai learning|"
        r"your daily dose|daily brief|sources|further reading|page \d|varun singla"
        r"|yesterday.s recap|generated by|tomorrow.s? preview)", re.I
    )

    # Collect all section headings with their positions in all_flat_lines.
    # A long heading can wrap onto a second PDF line (e.g. "...Without Reading
    # Your" / "Prompts"); extract_text() splits these into two flat lines with
    # no marker tying them together, so a heading ending on a dangling
    # preposition/article/etc. almost always means the title got cut off —
    # pull the short continuation line back in rather than losing the word.
    _dangling_last_word = re.compile(
        r"\b(?:a|an|the|of|to|for|and|or|but|nor|so|with|without|in|on|at|by|"
        r"from|into|onto|over|under|after|before|between|through|your|our|"
        r"their|its|his|her|is|are|was|were|be|as|that|this|these|those|not|"
        r"no|if|than|then|which|who|whom|how|why|what)$", re.I
    )
    heading_positions: list[tuple[int, str]] = []
    for idx, line in enumerate(all_flat_lines):
        # Skip anything inside the practical-takeaways block
        if takeaway_region and takeaway_region[0] <= idx < takeaway_region[1]:
            continue
        if is_section_heading(line) and not skip_headings.search(line):
            if _dangling_last_word.search(line.strip()) and idx + 1 < len(all_flat_lines):
                nxt = all_flat_lines[idx + 1].strip()
                if (nxt and len(nxt) <= 25 and not is_bullet(nxt)
                        and not is_section_heading(nxt) and not skip_headings.search(nxt)):
                    line = clean(line + " " + nxt)
            heading_positions.append((idx, line))

    for hi, (pos, heading) in enumerate(heading_positions):
        # Determine the end of this section (start of next heading or EOF)
        end_pos = heading_positions[hi + 1][0] if hi + 1 < len(heading_positions) else len(all_flat_lines)
        # Never let a section run into the practical-takeaways block
        if takeaway_region and pos < takeaway_region[0] < end_pos:
            end_pos = takeaway_region[0]

        # Get flat text lines for this section (for paragraphs)
        sec_lines = all_flat_lines[pos + 1: end_pos]

        # Paragraphs: non-bullet lines > 40 chars. A bullet's wrapped
        # continuation lines don't carry their own marker, so once a bullet
        # starts, skip lines until the next bullet/heading — otherwise the
        # continuation gets misread as the start of a new paragraph and the
        # same sentence ends up duplicated (truncated) in both places.
        paragraphs: list[str] = []
        current_para: list[str] = []
        in_bullet = False
        for ln in sec_lines:
            if skip_headings.search(ln):
                continue
            if is_bullet(ln):
                if current_para:
                    paragraphs.append(" ".join(current_para))
                    current_para = []
                in_bullet = True
                continue
            if in_bullet:
                if _is_list_break_heading(ln):
                    in_bullet = False
                else:
                    continue
            if len(ln) > 40:
                current_para.append(ln)
            elif current_para:
                # Short trailing/continuation line (e.g. a lone wrapped number
                # like "54.4." between two longer lines) — keep it rather than
                # silently dropping it, then close out the paragraph.
                current_para.append(ln)
                paragraphs.append(" ".join(current_para))
                current_para = []
        if current_para:
            paragraphs.append(" ".join(current_para))

        # Bullets: prefer full-width flat-text lines (sec_lines) — these come
        # from page.extract_text() with no column cropping, so multi-line
        # bullets on single-column layouts wrap correctly. The left-column
        # extraction (x0 < 55% page width) is a fallback for two-column
        # layouts, but silently truncates every wide single-column bullet
        # line at the crop boundary, so it must not run first (Day 136 lost
        # the second half of every bullet this way).
        page_idx = _heading_page(heading)
        bullets: list[str] = _bullets_from_lines(sec_lines)
        if not bullets and page_idx is not None:
            pd = page_data[page_idx]
            # Bullets from left column (skip heading itself)
            left_lines_after_heading = []
            found_heading = False
            for ll in pd['left_lines']:
                ll_clean = clean(ll)
                if not found_heading:
                    if heading[:30] in ll_clean or ll_clean in heading:
                        found_heading = True
                    continue
                left_lines_after_heading.append(ll_clean)
            if not found_heading:
                left_lines_after_heading = pd['left_lines']
            bullets = _bullets_from_lines(left_lines_after_heading)

        # Also try flat-text bullets as a fallback
        if not bullets:
            for ln in sec_lines:
                if is_bullet(ln):
                    bullets.append(extract_bullet_text(ln))

        # Find tables on the same page that come AFTER the heading's y-position
        sec_tables: list[dict] = []
        if page_idx is not None:
            # Find the heading's approximate y-position on the page
            heading_y = 0.0
            for w in page_data[page_idx].get('lines', []):
                pass  # We'll use table order as proxy — tables after first heading on page
            sec_tables = page_data[page_idx]['tables']

        # Attach tables: use tables on this page that aren't stat boxes or TOC tables
        table_for_sec = None
        for tbl in sec_tables:
            tdata = tbl['data']
            # Never attach the same table to more than one section
            if id(tbl) in used_tables:
                continue
            if _is_stat_box(tdata):
                continue
            if _is_toc_table(tdata):
                continue
            # Skip single-column tables (usually sidebars/callouts)
            if all(len(row) <= 1 for row in tdata):
                continue
            t = _extract_table_clean(tdata)
            if t and t.get('rows'):
                # Require a sane header row: ≥2 non-empty header cells.
                # pdfplumber sometimes merges the whole header into one cell
                # ("When to reach for it Use Guardrail", '', '') — attaching
                # that renders as a broken table, so skip it.
                if sum(1 for h in t.get('headers', []) if str(h).strip()) < 2:
                    continue
                table_for_sec = t
                used_tables.add(id(tbl))
                break

        sec: dict = {"title": heading}
        if paragraphs:
            sec["paragraphs"] = paragraphs
        if bullets:
            sec["bullets"] = bullets
        if table_for_sec:
            sec["table"] = table_for_sec

        if sec.get("paragraphs") or sec.get("bullets") or sec.get("table"):
            sections.append(sec)

    # ── Viral app ─────────────────────────────────────────────────────────────
    # Scan ALL tables across all pages for 'VIRAL APP OF THE DAY' header
    viral_app: dict | None = None

    # Anchored: only matches when the ENTIRE line/cell is the header itself,
    # not when the phrase merely appears inside a longer sentence (e.g. a
    # stat label like "Downloads of EcoGPT, the viral app built on ..."
    # would otherwise be mistaken for the section header on an earlier page).
    _viral_hdr_line = re.compile(
        r'^[n•]*\s*(viral app(\s+of\s+the\s+day)?|viral\s*/\s*open.source spotlight|'
        r'open.source spotlight|viral spotlight|oss spotlight)\s*[:\s]*$', re.I
    )

    for pi, pd in enumerate(page_data):
        # Check BOTH table cells AND page lines for a standalone "viral app"
        # header — never a substring match against a full line/sentence.
        _has_hdr_cell = any(
            _viral_hdr_line.match(str(cell).strip())
            for tbl in pd['tables']
            for row in tbl['data'] for cell in (row or []) if cell
        )
        _has_hdr_line = any(_viral_hdr_line.match(ln.strip()) for ln in pd['lines'])
        if not (_has_hdr_cell or _has_hdr_line):
            continue

        # ── Extract viral app from this page (once, not per-table) ──────────
        app_name = ''
        app_desc = ''
        app_stats: list[dict] = []
        name_parts: list[str] = []
        desc_parts: list[str] = []
        found_viral_header = False

        for ln in pd['lines']:
            ln_c = re.sub(r'^[n•]+\s+', '', ln).strip()
            if _viral_hdr_line.match(ln_c):
                found_viral_header = True
                continue
            if not found_viral_header:
                continue
            if re.match(r'^varun singla.*page\s*\d+\s*$', ln_c, re.I):
                # Page footer — never body text, always terminates the box.
                break
            if re.match(r'^([\$£€]?[\d,\.]+[a-zA-Z%]{0,3}\s*)+$', ln_c) or len(ln_c) < 5:
                # A stat-quad line ("10 $2K 96% 10.0", "0.70s 100K $0.14 $250M")
                # marks the end of the box's prose once we already have a name
                # and some description — everything after it is stat labels /
                # page footer, not body text.
                if app_name and desc_parts:
                    break
                continue
            if re.search(r'key takeaway|practical takeaway|market signal|tomorrow|generated by|agentic ai daily', ln_c, re.I):
                break
            if not app_name:
                # The first title line must look like a headline; once we're
                # already mid-title (continuing a wrapped line), the next
                # fragment can start lowercase (e.g. "solved problem").
                starts_ok = bool(name_parts) or re.match(r'^[A-Z0-9]', ln_c)
                if starts_ok and not re.search(r'agentic ai|daily (learning|brief)', ln_c, re.I):
                    name_parts.append(ln_c)
                    combined = ' '.join(name_parts)
                    # A title line ending on an article/preposition ("...for a",
                    # "...Default for") or a possessive ("...World's") is
                    # mid-phrase, not a complete title — keep collecting even
                    # though it ends in lowercase.
                    ends_midphrase = bool(re.search(
                        r"\b(a|an|the|for|of|to|and|or|in|on|with|by)$", ln_c, re.I
                    )) or ln_c.endswith("'s")
                    if (re.search(r'[a-z]$', ln_c) and not ends_midphrase) or len(combined) > 80:
                        app_name = combined
                continue
            # A short trailing continuation line (the last wrapped fragment of
            # a sentence, e.g. "on top of one.") is still real body text once
            # we're already mid-description — only require the >30 length
            # bar before we have any desc_parts yet, to avoid picking up
            # stray short labels as the start of the description.
            if len(ln_c) > 30 or (desc_parts and len(ln_c) > 3):
                desc_parts.append(ln_c)

        if desc_parts:
            app_desc = ' '.join(desc_parts)[:1400]
        if not app_name and name_parts:
            app_name = ' '.join(name_parts)

        # Boxed-table fallback: pdfplumber sometimes merges the whole spotlight box
        # (header + title in row 0, body text in row 1) into its own bordered table,
        # distinct from neighboring boxes like MARKET SIGNAL. That content never
        # reaches `lines` (it's inside a table bbox), so the loop above finds
        # nothing and the generic "longest cell wins" fallback below would
        # misattribute a neighboring box's text instead. Detect the shape directly.
        if not app_name:
            _viral_hdr_prefix = re.compile(
                r'^(viral app(\s+of\s+the\s+day)?|viral\s*/\s*open.source spotlight|'
                r'open.source spotlight|viral spotlight|oss spotlight)\b[:\s]*',
                re.I,
            )
            for tbl2 in pd['tables']:
                tdata = tbl2['data']
                if not tdata or not tdata[0] or not tdata[0][0]:
                    continue
                first_cell_raw = str(tdata[0][0])
                m_hdr = _viral_hdr_prefix.match(first_cell_raw.strip())
                if not m_hdr:
                    continue
                title_raw = first_cell_raw[m_hdr.end():].strip()
                if title_raw:
                    app_name = clean(title_raw)
                desc_cells = [clean(str(c)) for row in tdata[1:] for c in (row or []) if c]
                if desc_cells:
                    app_desc = ' '.join(desc_cells)[:1400]
                break

        # Stat box tables on this page
        for tbl2 in pd['tables']:
            if _is_stat_box(tbl2['data']):
                for cell in tbl2['data'][0]:
                    s = _clean_stat_cell(str(cell) if cell else '')
                    if s:
                        app_stats.append(s)

        # Prose description from tables if still empty
        if not app_desc:
            for tbl2 in pd['tables']:
                for row in tbl2['data']:
                    for cell in (row or []):
                        cell_c = clean_table_cell(cell)
                        if (len(cell_c) > 80
                                and not re.search(r'viral app of the day|zero.days found|partner network', cell_c, re.I)):
                            if len(cell_c) > len(app_desc):
                                app_desc = cell_c[:600]

        # If no stats found in tables, extract stat chips from consecutive short lines on this page
        # Format in text: "v1.1.5\nReleased Apr 29 2026\nMulti-platform\nWeChat/...\nMemory dream\n..."
        if not app_stats:
            page_lines = pd['lines']
            # Find viral app page position
            viral_line_idx = next(
                (i for i, ln in enumerate(page_lines) if re.search(r'viral app', ln, re.I)), None
            )
            if viral_line_idx is not None:
                # After the description, look for pairs of short lines: stat value + stat label
                remaining = page_lines[viral_line_idx:]
                i = 0
                while i < len(remaining) - 1 and len(app_stats) < 4:
                    line = remaining[i].strip()
                    next_line = remaining[i+1].strip() if i+1 < len(remaining) else ''
                    # A stat chip: short value (version, keyword) + short label
                    if (re.match(r'^(v[\d\.]+|Multi-\w+|Memory \w+|Tool \w+|Released \w+ \d+|Apache [\d\.]+|Blocks .{5,40}|Scheduled .{5,40})$', line, re.I)
                            and 3 < len(next_line) < 80):
                        app_stats.append({'stat': clean(line), 'label': clean(next_line)})
                        i += 2
                    else:
                        i += 1

        viral_app = {
            'name': app_name or '',
            'description': app_desc,
            'stats': app_stats,
        }
        break

    # Fallback: "Viral App: X" in Today's Focus header
    if not viral_app:
        m = re.search(r"\+\s*Viral\s+App[:\s]+([A-Z][^\s\+\n,]{2,50}(?:\s+\([^)]+\))?)", full_text, re.I)
        if m:
            vname = clean(m.group(1).strip())
            desc_m = re.search(re.escape(vname) + r'\s+(?:is|was|went|launched).{5,400}', full_text, re.I)
            viral_app = {
                'name': vname,
                'description': clean(desc_m.group(0)[:400]) if desc_m else '',
                'stats': [],
            }

    # Fallback: generic pattern
    if not viral_app:
        m = re.search(r"viral app[:\s]+([A-Z][^\n\.+]{5,60})", full_text, re.I)
        if m:
            viral_app = {'name': clean(m.group(1).strip()), 'description': '', 'stats': []}

    # ── Practical takeaways ───────────────────────────────────────────────────
    # Day ~100+ layout: numbered prose items under a "PRACTICAL TAKEAWAYS"
    # heading (extracted earlier). Older layouts: tables / section headings.
    practical_takeaway: list[dict] = list(numbered_takeaways)

    # Strategy 0: scan all tables for 1-col format "n Title Body" (title and body merged in single cell)
    if not practical_takeaway:
        for pi, pd in enumerate(page_data):
            for tbl in pd['tables']:
                tdata = tbl['data']
                if not tdata:
                    continue
                # 1-col table where cells start with "n " bullet marker
                if all(len(row) == 1 for row in tdata if row):
                    cells = [str(row[0]).strip() for row in tdata if row and row[0]]
                    if len(cells) >= 2 and all(re.match(r'^n\s+\S', c) for c in cells[:2]):
                        for cell in cells:
                            cell = re.sub(r'^n\s+', '', cell)
                            # These cells merge title + body: "Write specs first Before prompting..."
                            # Split strategy: find where a capitalized "action title" ends and body begins.
                            # Body starts at first occurrence of a verb/preposition after the short title.
                            # Heuristic: title is 2-6 words (Title Case), body is a full sentence.
                            # Use regex: short title-case phrase, then sentence starting with capital word.
                            m2 = re.match(
                                r'^([A-Z][a-zA-Z0-9\s\-\']{3,60}?)\s+((?:Before|For|At|If|T-\d|When|Use|After|To|This|The|It|You|By|In)\s+.+)$',
                                cell, re.S
                            )
                            if m2:
                                title_part = clean(m2.group(1))
                                body_part = clean(m2.group(2))
                            else:
                                # Fallback: split on newline
                                parts = cell.split('\n', 1)
                                title_part = clean(parts[0][:80])
                                body_part = clean(parts[1].strip()) if len(parts) > 1 else clean(cell)
                            if title_part and body_part and len(body_part) > 20:
                                practical_takeaway.append({'title': title_part, 'body': body_part})
                        if practical_takeaway:
                            break
            if practical_takeaway:
                break

    # Strategy 1: look for takeaway section in sections list
    for sec in sections[:]:
        if re.search(r"(practical takeaway|key takeaway)", sec.get("title", ""), re.I):
            parts = sec.get("paragraphs", []) + sec.get("bullets", [])
            if not practical_takeaway:
                practical_takeaway = [{'title': p[:60], 'body': p} for p in parts if p]
            sections.remove(sec)
            break

    # Strategy 2: scan last page tables for 2-column takeaway table
    if not practical_takeaway:
        last_page = page_data[-1]
        for tbl in last_page['tables']:
            tdata = tbl['data']
            # A takeaway table: ≥3 rows, 2 cols, first col is a bullet/icon marker
            if len(tdata) >= 2 and all(len(row) >= 2 for row in tdata if row):
                first_col_vals = [str(r[0]).strip() for r in tdata if r and r[0]]
                # Bullet markers in col 1 are 'n', 'nn', '•', etc.
                if all(re.match(r'^[n•]{1,3}$', v) or len(v) < 5 for v in first_col_vals if v):
                    for row in tdata:
                        if not row or len(row) < 2:
                            continue
                        cell = clean_table_cell(row[1])
                        if len(cell) > 20:
                            # Split title from body
                            parts = cell.split('\n', 1)
                            practical_takeaway.append({
                                'title': clean(parts[0])[:80],
                                'body': clean(parts[1]) if len(parts) > 1 else clean(parts[0])
                            })
                    if practical_takeaway:
                        break

    # Strategy 3: scan ALL tables for takeaway keywords
    if not practical_takeaway:
        for tdata in all_tables:
            if not tdata:
                continue
            flat = ' '.join(str(c) for r in tdata for c in (r or []) if c)
            if re.search(r'(key takeaway|practical takeaway|action point|your action)', flat, re.I):
                for row in tdata:
                    if not row:
                        continue
                    cell = clean_table_cell(row[-1] if len(row) > 1 else row[0])
                    if len(cell) > 30:
                        parts = cell.split('\n', 1)
                        practical_takeaway.append({
                            'title': clean(parts[0])[:80],
                            'body': clean(parts[1]) if len(parts) > 1 else cell
                        })
                if practical_takeaway:
                    break

    # ── Market signal ─────────────────────────────────────────────────────────
    market_signal = ""
    m = re.search(r"MARKET SIGNAL[:\s]+(.+?)(?=\s*\d+\.\s+[A-Z]|\s*PRACTICAL TAKEAWAY|Generated by|Tomorrow|$)",
                  full_text, re.S)
    if m:
        sentences = re.split(r'(?<=[.!?])\s+', m.group(1).strip())
        # Drop trailing heading fragments that aren't sentences (e.g. "PRACTICAL TAKEAWAYS")
        while sentences and not _ends_sentence(sentences[-1]):
            sentences.pop()
        market_signal = clean(" ".join(sentences[:6]))

    # ── Tomorrow preview ──────────────────────────────────────────────────────
    tomorrow_preview = ""
    m = re.search(r"tomorrow.s?(?:\s*—?\s*day\s*\d+\s*preview)?[:\s\—–]+(.{10,400}?)(?:\n\n|\Z)", full_text, re.I | re.S)
    if m:
        tomorrow_preview = clean(m.group(1))
    # Also try "n Tomorrow — Day N Preview" style (with 'n' bullet artifact)
    if not tomorrow_preview:
        m = re.search(r"n\s+Tomorrow[^.\n]{0,40}?(?:Day\s*\d+)?[^.\n]{0,20}\n(.{10,400}?)(?:\n\n|\Z)", full_text, re.I | re.S)
        if m:
            tomorrow_preview = clean(m.group(1))
    if not tomorrow_preview:
        m = re.search(r"Day\s+\d+\s+will\s+cover\s+(.{20,500}?)(?:Agentic AI Daily|Sources:|$)", full_text, re.I | re.S)
        if m:
            tomorrow_preview = clean(m.group(0).strip())
    if not tomorrow_preview:
        # Last page often has it as a table
        for tbl in page_data[-1]['tables']:
            flat = ' '.join(str(c) for r in tbl['data'] for c in (r or []) if c)
            if re.search(r'tomorrow|day \d+\s*preview', flat, re.I):
                # Strip the "TOMORROW" box-header so it doesn't duplicate
                # ("TOMORROW Tomorrow -- Day 103 …" → "Tomorrow -- Day 103 …")
                flat = re.sub(r'^\s*TOMORROW\b[\s:·—-]*', '', flat.strip(), flags=re.I)
                tomorrow_preview = clean(flat[:300])
                break

    # ── Remove boilerplate sections ───────────────────────────────────────────
    sections = [
        s for s in sections
        if not re.search(
            r"(sources|further reading|what.s inside|your agentic ai learning map|learning map"
            r"|viral\s*/|viral app|viral spotlight|open.source spotlight|oss spotlight"
            r"|market signal|practical takeaway|key takeaway|^tomorrow)",
            s.get("title", ""), re.I
        )
        and (s.get("paragraphs") or s.get("bullets") or s.get("table"))
        and not (re.match(r"^\d+\.", s.get("title", "")) and len(s.get("title", "")) > 60)
    ]

    # ── Deduplicate sections ──────────────────────────────────────────────────
    seen_titles: dict[str, int] = {}
    deduped: list[dict] = []
    for sec in sections:
        key = sec.get("title", "").strip().lower()
        score = (len(sec.get("paragraphs", [])) * 3
                 + len(sec.get("bullets", [])) * 2
                 + (1 if sec.get("table") else 0))
        if key in seen_titles:
            old_idx = seen_titles[key]
            old_score = (len(deduped[old_idx].get("paragraphs", [])) * 3
                         + len(deduped[old_idx].get("bullets", [])) * 2
                         + (1 if deduped[old_idx].get("table") else 0))
            if score > old_score:
                better = dict(sec)
                if not better.get("table") and deduped[old_idx].get("table"):
                    better["table"] = deduped[old_idx]["table"]
                deduped[old_idx] = better
        else:
            seen_titles[key] = len(deduped)
            deduped.append(sec)

    def _sec_sort_key(s: dict) -> tuple:
        m = re.match(r"^(\d+)", s.get("title", ""))
        return (int(m.group(1)), s.get("title", "")) if m else (999, s.get("title", ""))

    deduped.sort(key=_sec_sort_key)
    sections = deduped

    # ── focus_intro cleanup ───────────────────────────────────────────────────
    if focus_intro and (
        re.search(r'\+\s*(?:Viral App|Industry|Apple|Mistral|Samsung|OpenAI|Google)', focus_intro, re.I)
        or re.search(r'MAIN TOPIC|INDUSTRY FLASH', focus_intro)
    ):
        for sec in sections:
            if sec.get("paragraphs"):
                focus_intro = sec["paragraphs"][0]
                break

    # Never let a mid-sentence fragment through: trim back to the last
    # complete sentence, else fall back to the first section paragraph.
    if focus_intro and not _ends_sentence(focus_intro):
        trimmed = _trim_to_sentence(focus_intro)
        if not trimmed:
            for sec in sections:
                paras = sec.get("paragraphs") or []
                if paras and _ends_sentence(paras[0]):
                    trimmed = paras[0]
                    break
        focus_intro = trimmed

    # ── v5: casing, de-duplication, sources, watch list, recap, themes, quiz ──
    corpus = build_corpus({'focus_intro': focus_intro, 'sections': sections, 'market_signal': market_signal,
                           'viral_app': viral_app, 'practical_takeaway': practical_takeaway})
    if title:
        if is_shouting(title) or (fm.get('generic') and fm_used):
            title = to_title_case(title, corpus)
        title = re.sub(r'\s*--\s*--\s*', ' -- ', title)
        title = _DAY_PREFIX_RE.sub('', title).strip()
        title = re.sub(r"[\s,;:\-—–]+$", '', title)
    if subtitle:
        subtitle = tidy_deck(subtitle, corpus)
        if _norm_text(subtitle) == _norm_text(title):
            subtitle = ''
    for sec in sections:
        sec['title'] = recase_heading(sec.get('title', ''), corpus)
    viral_app = normalize_viral(viral_app)
    if fm_lede and (not focus_intro or focus_intro[:1].islower()
                    or _norm_text(focus_intro)[:60] in _norm_text(fm_lede)):
        focus_intro = fm_lede
    sources = extract_sources(all_flat_lines)
    tm_block = extract_tomorrow_block(all_flat_lines)
    if tm_block and (not tomorrow_preview or len(tm_block) > len(tomorrow_preview)):
        tomorrow_preview = tm_block
    recap = extract_recap(all_flat_lines)
    themes = extract_themes(all_flat_lines)
    quiz = extract_quiz(all_flat_lines)

    # ── Validation ────────────────────────────────────────────────────────────
    warnings = []
    if not issue:
        warnings.append("'issue' number not found")
    if not viral_app:
        warnings.append("'viral_app' not found")
    if not practical_takeaway:
        warnings.append("'practical_takeaway' not found")
    if not sections:
        warnings.append("No content sections found — PDF structure may have changed")
    if warnings:
        print(f"   ⚠️  Validation warnings for {pdf_path.name}:")
        for w in warnings:
            print(f"      • {w}")
    else:
        print(f"   ✅  Validation passed — all required fields present")

    entry = {
        "date":               date_str,
        "display_date":       display_date,
        **({"issue": issue} if issue else {}),
        "title":              title,
        **({"subtitle": subtitle} if subtitle else {}),
        "focus_intro":        focus_intro,
        **({"viral_app": viral_app} if viral_app else {}),
        "stats":              stats,
        "sections":           sections,
        **({"market_signal": market_signal} if market_signal else {}),
        "practical_takeaway": practical_takeaway,
        **({"tomorrow_preview": tomorrow_preview} if tomorrow_preview else {}),
        **({"sources": sources} if sources else {}),
        **({"recap": recap} if recap else {}),
        **({"themes": themes} if themes else {}),
        **({"quiz": quiz} if quiz else {}),
        "schema":             SCHEMA_VERSION,
    }
    dedupe_intro(entry, fm_lede)
    return entry


# ── learnings.json ────────────────────────────────────────────────────────────

def load_learnings() -> dict:
    if LEARNINGS_JSON.exists():
        return json.loads(LEARNINGS_JSON.read_text(encoding="utf-8"))
    return {
        "profile": {
            "name":     "Varun Singla",
            "tagline":  "Learning fast. Staying ahead.",
            "subtitle": "Daily AI breakthroughs, insights & trends — tracked one day at a time.",
        },
        "learnings": [],
    }


def _entry_richness(e: dict) -> int:
    """Rough completeness score for an entry. Used by the degradation guard:
    a re-parse must be meaningfully richer than the stored entry to replace it."""
    if not e:
        return 0
    score = 0
    score += min(len(e.get("title") or ""), 200)
    score += min(len(e.get("focus_intro") or ""), 1500)
    va = e.get("viral_app") or {}
    score += min(len(va.get("name") or "") + len(va.get("description") or ""), 1500)
    score += 100 * len(va.get("stats") or [])
    score += 60 * len(e.get("stats") or [])
    for s in e.get("sections") or []:
        score += min(sum(len(p) for p in s.get("paragraphs") or []), 1500)
        score += 40 * len(s.get("bullets") or [])
        score += 60 if s.get("table") else 0
    score += min(len(e.get("market_signal") or ""), 800)
    score += 250 * len(e.get("practical_takeaway") or [])
    score += min(len(e.get("tomorrow_preview") or ""), 300)
    score += min(len(e.get("subtitle") or ""), 200)
    score += min(len(e.get("sources") or ""), 300)
    score += 80 * len(e.get("quiz") or [])
    return score


def _is_empty_value(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _merge_preserving(existing: dict, new: dict) -> dict:
    """Merge a re-parsed entry with the stored one WITHOUT losing content.

    The richer entry becomes the base; the other only fills fields the base
    is missing. A re-parse must beat the stored entry by >10% richness to
    become the base — this is the degradation guard that stops a poorer
    parse (missing viral_app / takeaways, truncated title, mangled tables)
    from overwriting a good published entry, which previously required
    manual restores (see Day 100 / Day 101 fix commits).
    """
    if _entry_richness(new) > _entry_richness(existing) * 1.10:
        base, filler = dict(new), existing
    else:
        base, filler = dict(existing), new
    for k, v in filler.items():
        if _is_empty_value(base.get(k)) and not _is_empty_value(v):
            base[k] = v
    return base


def merge_entry(data: dict, entry: dict) -> tuple[dict, str]:
    """Add or update an entry in learnings.json. Returns (data, action)."""
    idx = next((i for i, l in enumerate(data["learnings"]) if l["date"] == entry["date"]), None)
    if idx is not None:
        existing = data["learnings"][idx]
        merged = _merge_preserving(existing, entry)
        if merged == existing:
            action = "unchanged — stored entry is as rich or richer (degradation guard)"
        elif _entry_richness(entry) <= _entry_richness(existing) * 1.10:
            action = "updated (kept richer stored entry as base, filled missing fields)"
        else:
            action = "updated"
        data["learnings"][idx] = merged
    else:
        data["learnings"].append(entry)
        action = "added"
    data["learnings"].sort(key=lambda x: x["date"], reverse=True)
    return data, action


# ── GitHub API push ───────────────────────────────────────────────────────────

def _push_file(api_base: str, headers: dict, filename: str, content_bytes: bytes, message: str) -> bool:
    """Push a single file to GitHub via REST API."""
    import urllib.error
    import urllib.request
    b64 = base64.b64encode(content_bytes).decode()
    api_url = f"{api_base}/{filename}"
    sha = None
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            sha = json.loads(resp.read())["sha"]
    except Exception:
        pass
    payload: dict = {"message": message, "content": b64}
    if sha:
        payload["sha"] = sha
    try:
        req = urllib.request.Request(
            api_url, data=json.dumps(payload).encode(), headers=headers, method="PUT"
        )
        with urllib.request.urlopen(req):
            return True
    except Exception as e:
        print(f"   ⚠️  Could not push {filename}: {e}")
        return False


def github_push(config: dict, data: dict, extra_files: list | None = None) -> bool:
    """Push learnings.json plus any changed generated GEO files via REST API."""
    import urllib.error
    import urllib.request

    token = config.get("github_token") or os.environ.get("GITHUB_TOKEN", "")
    user  = config.get("github_user", "")
    repo  = config.get("github_repo", "")

    if not all([token, user, repo]):
        print("   ⚠️  GitHub config incomplete — skipping push.")
        print("       Set github_token, github_user, github_repo in config.json")
        return False

    api_base = f"https://api.github.com/repos/{user}/{repo}/contents"
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
        "Content-Type":  "application/json",
    }
    today = datetime.now().strftime("%Y-%m-%d")

    # Push learnings.json
    content_str = json.dumps(data, indent=2, ensure_ascii=False)
    ok = _push_file(api_base, headers, "learnings.json",
                    content_str.encode(), f"Daily update: {today}")
    if ok:
        print(f"   ✅  Pushed to github.com/{user}/{repo}")
        print(f"       Live at: https://varunsingla.com")

    # Push regenerated GEO files (static entry pages, llms.txt, feed.xml,
    # sitemap.xml, index.html static block) — only the ones that changed.
    pushed = 0
    for rel in extra_files or []:
        fpath = SCRIPT_DIR / rel
        if fpath.exists():
            rel_posix = str(rel).replace(os.sep, "/")
            if _push_file(api_base, headers, rel_posix,
                          fpath.read_bytes(), f"GEO: update {rel_posix} ({today})"):
                pushed += 1
    if pushed:
        print(f"   ✅  {pushed} GEO file(s) updated (sitemap, llms.txt, entry pages …)")

    return ok


# ── Main ──────────────────────────────────────────────────────────────────────

def _regenerate_geo() -> list:
    try:
        import generate_geo
        changed = generate_geo.generate(SCRIPT_DIR)
        print(f"   ✅  {len(changed)} generated file(s) changed")
        return changed
    except Exception as e:
        print(f"   ⚠️  GEO generation failed (site still updates): {e}")
        return []


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n🤖  AI Learning Blog Updater — {now}")
    print("─" * 54)

    args = sys.argv[1:]
    if "--parse" in args:
        # Debug: parse one PDF and print the entry as JSON (no writes).
        pdf = Path(args[args.index("--parse") + 1])
        print(json.dumps(parse_pdf(pdf), indent=2, ensure_ascii=False))
        return

    config   = load_config()
    data     = load_learnings()
    learnings = data["learnings"]

    # ── Repair / backfill stored entries (idempotent; no-op once current) ─────
    # Fixes titles ("AI Learning -- Day N" → the deck line), adds subtitles,
    # sources, the TOMORROW watch list, recaps and themes from the PDFs on disk,
    # re-cases ALL-CAPS headings and de-duplicates intros. Originals are kept
    # under *_original fields, so nothing is lost.
    if "--repair" in args:
        report = repair_all(data, SCRIPT_DIR, force="--force" in args)
        print(f"🔧  Repair pass: {len(report)} entr{'y' if len(report) == 1 else 'ies'} changed")
        if "--dry-run" in args:
            print("   (dry run — nothing written)")
            return
        LEARNINGS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print("🌐  Regenerating GEO files …")
        _regenerate_geo()
        print("✅  Done (not pushed — commit and push the repo as usual).\n")
        return

    repaired = repair_all(data, SCRIPT_DIR, verbose=False)
    if repaired:
        LEARNINGS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"🔧  Repaired {len(repaired)} stored entr{'y' if len(repaired) == 1 else 'ies'} (schema v{SCHEMA_VERSION})")

    # ── Find new PDF ──────────────────────────────────────────────────────────
    print("🔍  Looking for new daily PDF …")
    result = find_unprocessed_pdf(learnings)

    if not result:
        print("   ℹ️  No new PDF found — checking for any updates to existing entries …")
        # Re-process today's PDF if it exists
        all_pdfs = find_daily_pdfs()
        if all_pdfs:
            result = all_pdfs[0]
            print(f"   Re-processing most recent: {result[1].name}")
        else:
            print("   No PDFs found in workspace. Nothing to update.")
            sys.exit(0)

    dt, pdf_path = result
    print(f"   Found: {pdf_path.name}  ({dt.strftime('%B %-d, %Y')})")

    # ── Parse PDF ─────────────────────────────────────────────────────────────
    print("📖  Extracting content from PDF …")
    entry = parse_pdf(pdf_path)

    # Always trust the filename date — it is authoritative.
    # parse_date_from_text() can pick up incidental dates in the PDF body
    # (e.g. "August 2" from an EU AI Act deadline) and corrupt the entry.
    entry["date"]         = dt.strftime("%Y-%m-%d")
    entry["display_date"] = dt.strftime("%B %-d, %Y")

    print(f"   Date:     {entry['display_date']}")
    print(f"   Issue:    #{entry.get('issue', '?')}")
    print(f"   Title:    {entry.get('title', '(untitled)')[:60]}")
    print(f"   Sections: {len(entry.get('sections', []))}")
    print(f"   Viral:    {entry.get('viral_app', {}).get('name', 'none')}")
    print(f"   Stats:    {len(entry.get('stats', []))} entries")
    print(f"   Takeaway: {'✅' if entry.get('practical_takeaway') else '❌ missing'}")

    # ── Merge into JSON ───────────────────────────────────────────────────────
    print("📝  Updating learnings.json …")
    data, action = merge_entry(data, entry)
    LEARNINGS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"   ✅  Entry {action} ({len(data['learnings'])} total days)")

    # ── Regenerate GEO artifacts ──────────────────────────────────────────────
    # Static entry pages, entries/index.html, llms.txt, llms-full.txt,
    # feed.xml, sitemap.xml and the static-fallback block in index.html —
    # this is what AI crawlers (GPTBot, ClaudeBot, PerplexityBot, …) and
    # search engines actually read, since they don't execute JavaScript.
    print("🌐  Regenerating GEO files (static entries, llms.txt, feed, sitemap) …")
    geo_changed: list = _regenerate_geo()

    # ── Push to GitHub ────────────────────────────────────────────────────────
    print("🚀  Pushing to GitHub …")
    github_push(config, data, geo_changed)

    print("─" * 54)
    print("✅  Done!\n")


if __name__ == "__main__":
    main()

