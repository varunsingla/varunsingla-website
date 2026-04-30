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
        # Handle 'n' bullet artifact prefix (e.g. "n Practical Takeaways for Varun", "n Market Signal")
        "n practical takeaway", "n market signal", "n viral app", "n breaking",
        "n today's focus", "n tomorrow",
    ]
    low = line.lower()
    for h in headings:
        if low.startswith(h):
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
        return page.extract_text(x_tolerance=3, y_tolerance=3) or ""

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

    return page.filter(_not_in_any_table).extract_text(x_tolerance=3, y_tolerance=3) or ""


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
    Each item: {'bbox': (x0,top,x1,bottom), 'data': [[cell, …], …]}"""
    results = []
    for ft in page.find_tables():
        extracted = ft.extract()
        if extracted:
            results.append({'bbox': ft.bbox, 'data': extracted})
    return results


def _left_col_lines(page, top_skip: float = 0.0) -> list[str]:
    """Extract lines from the LEFT column only (x0 < 55% page width),
    skipping the top N points (to avoid the header/title region).
    Words are grouped into visual lines by their vertical position."""
    pw = page.width
    col_limit = pw * 0.55
    rows: dict[int, list[tuple[float, str]]] = {}
    for w in page.extract_words(x_tolerance=3, y_tolerance=3):
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
        is_heading = bool(
            re.match(r'^\d+\.\s+[A-Z]', ln)
            or re.match(r'^[A-Z][A-Za-z ]{3,40}:?\s*$', ln)
            or re.match(r'^Stage \d', ln)
            or re.match(r'^Layer \d', ln)
            or re.match(r'^Step \d', ln)
        )
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

            # Full-page text outside tables
            if table_bboxes:
                page_text = page.filter(_not_in_table).extract_text(x_tolerance=3, y_tolerance=3) or ""
            else:
                page_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""

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
    # Strategy 1a: "TODAY'S DEEP DIVE: X" or "Today's Focus: X" — scan wider (up to 30 lines)
    for line in all_flat_lines[:30]:
        low = line.lower()
        if re.search(r"today.s (focus|topic|deep dive)\s*:", low):
            m = re.match(r"today.s (?:focus|topic|deep dive)\s*:\s*(.+)", line, re.I)
            if m:
                raw = m[1].strip()
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
                candidate = re.sub(r'^[n•]+\s*', '', line).strip()
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

    # Strategy 2: PDF subtitle (line 2 of page 1, if concise and title-cased)
    if not title and len(page_data[0]['lines']) >= 2:
        for ln in page_data[0]['lines'][1:5]:
            ln_clean = re.sub(r'^[n•]+\s*', '', ln).strip()
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
                intro_parts = []
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

    # Fallback: use PDF subtitle line as intro (line after title)
    if not focus_intro:
        p1_lines = page_data[0]['lines']
        for ln in p1_lines[1:6]:
            ln = re.sub(r'^[n•]+\s*', '', ln).strip()
            if len(ln) > 60 and not _title_skip.search(ln) and not re.search(r'\d{4}', ln):
                focus_intro = ln
                break

    # Fallback: use first section paragraph
    if not focus_intro:
        for l in all_flat_lines[5:30]:
            if len(l) > 80 and not is_section_heading(l) and not _title_skip.search(l):
                focus_intro = l
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
    skip_headings = re.compile(
        r"(today.s (focus|topic)|what.s inside|ai daily learning|daily ai learning|"
        r"your daily dose|daily brief|sources|further reading|page \d|varun singla"
        r"|yesterday.s recap|generated by|tomorrow.s? preview)", re.I
    )

    # Collect all section headings with their positions in all_flat_lines
    heading_positions: list[tuple[int, str]] = []
    for idx, line in enumerate(all_flat_lines):
        if is_section_heading(line) and not skip_headings.search(line):
            heading_positions.append((idx, line))

    for hi, (pos, heading) in enumerate(heading_positions):
        # Determine the end of this section (start of next heading or EOF)
        end_pos = heading_positions[hi + 1][0] if hi + 1 < len(heading_positions) else len(all_flat_lines)

        # Get flat text lines for this section (for paragraphs)
        sec_lines = all_flat_lines[pos + 1: end_pos]

        # Paragraphs: non-bullet lines > 40 chars
        paragraphs: list[str] = []
        current_para: list[str] = []
        for ln in sec_lines:
            if skip_headings.search(ln):
                continue
            if is_bullet(ln):
                if current_para:
                    paragraphs.append(" ".join(current_para))
                    current_para = []
            elif len(ln) > 40:
                current_para.append(ln)
            elif len(ln) > 10 and current_para:
                paragraphs.append(" ".join(current_para))
                current_para = []
        if current_para:
            paragraphs.append(" ".join(current_para))

        # Bullets: use left-column extraction on the page where the heading appears
        page_idx = _heading_page(heading)
        bullets: list[str] = []
        if page_idx is not None:
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
            if _is_stat_box(tdata):
                continue
            if _is_toc_table(tdata):
                continue
            # Skip single-column tables (usually sidebars/callouts)
            if all(len(row) <= 1 for row in tdata):
                continue
            t = _extract_table_clean(tdata)
            if t and t.get('rows'):
                table_for_sec = t
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

    for pi, pd in enumerate(page_data):
        # Check BOTH table cells AND page lines for "viral app" signal
        flat_cells = ' '.join(
            str(cell) for tbl in pd['tables']
            for row in tbl['data'] for cell in (row or []) if cell
        )
        flat_lines = ' '.join(pd['lines'])
        if not re.search(r'viral app', flat_cells + ' ' + flat_lines, re.I):
            continue

        # ── Extract viral app from this page (once, not per-table) ──────────
        app_name = ''
        app_desc = ''
        app_stats: list[dict] = []
        name_parts: list[str] = []
        desc_parts: list[str] = []
        found_viral_header = False

        for ln in pd['lines']:
            ln_c = re.sub(r'^[•n]+\s*', '', ln).strip()
            if re.search(r'viral app', ln_c, re.I):
                found_viral_header = True
                continue
            if not found_viral_header:
                continue
            if re.match(r'^[\d\$£€%+K,\.\s]+$', ln_c) or len(ln_c) < 5:
                continue
            if re.search(r'key takeaway|tomorrow|generated by|agentic ai daily', ln_c, re.I):
                break
            if not app_name:
                if re.match(r'^[A-Z]', ln_c) and not re.search(r'agentic ai|daily (learning|brief)', ln_c, re.I):
                    name_parts.append(ln_c)
                    combined = ' '.join(name_parts)
                    if re.search(r'[a-z]$', ln_c) or len(combined) > 80:
                        app_name = combined
                continue
            if len(ln_c) > 30:
                desc_parts.append(ln_c)

        if desc_parts:
            app_desc = ' '.join(desc_parts)[:700]
        if not app_name and name_parts:
            app_name = ' '.join(name_parts)

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
    # PDFs put takeaways in a 2-column table on the last page OR as a section heading
    practical_takeaway: list[dict] = []

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

    # Strategy 1: look for takeaway section in sections list    # Strategy 1: look for takeaway section in sections list
    for sec in sections[:]:
        if re.search(r"(practical takeaway|key takeaway)", sec.get("title", ""), re.I):
            parts = sec.get("paragraphs", []) + sec.get("bullets", [])
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
    m = re.search(r"Market Signal[:\s]+(.+?)(?=\s*\d+\.\s+[A-Z]|Generated by|Tomorrow|$)",
                  full_text, re.I | re.S)
    if m:
        sentences = re.split(r'(?<=[.!?])\s+', m.group(1).strip())
        market_signal = clean(" ".join(sentences[:3]))

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
                tomorrow_preview = clean(flat[:300])
                break

    # ── Remove boilerplate sections ───────────────────────────────────────────
    sections = [
        s for s in sections
        if not re.search(
            r"(sources|further reading|what.s inside|your agentic ai learning map|learning map)",
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

    return {
        "date":               date_str,
        "display_date":       display_date,
        **({"issue": issue} if issue else {}),
        "title":              title,
        "focus_intro":        focus_intro,
        **({"viral_app": viral_app} if viral_app else {}),
        "stats":              stats,
        "sections":           sections,
        **({"market_signal": market_signal} if market_signal else {}),
        "practical_takeaway": practical_takeaway,
        **({"tomorrow_preview": tomorrow_preview} if tomorrow_preview else {}),
    }


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


def merge_entry(data: dict, entry: dict) -> tuple[dict, str]:
    """Add or update an entry in learnings.json. Returns (data, action)."""
    idx = next((i for i, l in enumerate(data["learnings"]) if l["date"] == entry["date"]), None)
    if idx is not None:
        data["learnings"][idx] = entry
        action = "updated"
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


def github_push(config: dict, data: dict) -> bool:
    """Push learnings.json (and sitemap.xml if present) to GitHub via REST API."""
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

    # Push sitemap.xml (keeps lastmod fresh for Google)
    sitemap_path = SCRIPT_DIR / "sitemap.xml"
    if sitemap_path.exists():
        _push_file(api_base, headers, "sitemap.xml",
                   sitemap_path.read_bytes(), f"SEO: update sitemap lastmod {today}")
        print(f"   ✅  sitemap.xml updated")

    return ok


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n🤖  AI Learning Blog Updater — {now}")
    print("─" * 54)

    config   = load_config()
    data     = load_learnings()
    learnings = data["learnings"]

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
    entry["display_date"] = dt.strftime("%B %-d, %Y").upper()

    print(f"   Date:     {entry['display_date']}")
    print(f"   Issue:    #{entry.get('issue', '?')}")
    print(f"   Title:    {entry.get('title', '(untitled)')[:60]}")
    print(f"   Sections: {len(entry.get('sections', []))}")
    print(f"   Viral:    {entry.get('viral_app', {}).get('name', 'none')}")
    print(f"   Stats:    {len(entry.get('key_stats', []))} entries")
    print(f"   Takeaway: {'✅' if entry.get('practical_takeaway') else '❌ missing'}")

    # ── Merge into JSON ───────────────────────────────────────────────────────
    print("📝  Updating learnings.json …")
    data, action = merge_entry(data, entry)
    LEARNINGS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"   ✅  Entry {action} ({len(data['learnings'])} total days)")

    # ── Update sitemap.xml with today's date ──────────────────────────────────
    sitemap_path = SCRIPT_DIR / "sitemap.xml"
    if sitemap_path.exists():
        sitemap = sitemap_path.read_text(encoding="utf-8")
        today = datetime.now().strftime("%Y-%m-%d")
        sitemap = re.sub(r"<lastmod>[^<]+</lastmod>", f"<lastmod>{today}</lastmod>", sitemap)
        sitemap_path.write_text(sitemap, encoding="utf-8")

    # ── Push to GitHub ────────────────────────────────────────────────────────
    print("🚀  Pushing to GitHub …")
    github_push(config, data)

    print("─" * 54)
    print("✅  Done!\n")


if __name__ == "__main__":
    main()

