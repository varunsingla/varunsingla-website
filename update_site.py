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
    # MonthDD_YYYY or MonthDD-YYYY or Month-DD-YYYY
    m = re.search(r"([a-z]+)[- ]?(\d{1,2})[,_-]?\s*(\d{4})", name)
    if m:
        month = MONTHS.get(m[1][:3])
        if month:
            try:
                return datetime(int(m[3]), month, int(m[2]))
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


def parse_pdf(pdf_path: Path) -> dict:
    """Parse a daily AI learning PDF into a rich structured dict.

    Key improvements over v1:
      1. Table content is EXCLUDED from text extraction to prevent garbling.
      2. comprehensive clean() handles all known PDF encoding artifacts.
      3. Issue number also matched from 'Edition #N' header format.
      4. Title handles 'Today's Focus: ...' inline format.
      5. Viral app name extracted from section content when not in title.
      6. Stat-box tables are parsed for key_stats.
      7. Validation warns on missing required fields.
    """
    print(f"   📄 Parsing: {pdf_path.name}")

    all_lines: list[str] = []
    raw_tables: list[list] = []     # all tables (raw, for stat extraction)
    section_tables: list[list] = [] # tables suitable for section attachment

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # ── Extract tables (raw, before cleaning) ────────────────────────
            page_found = page.find_tables()
            for ft in page_found:
                extracted = ft.extract()
                if extracted:
                    raw_tables.append(extracted)
                    # Only attach to sections if it has ≥ 2 rows (header + data)
                    # and is NOT a TOC/navigation table
                    if len(extracted) >= 2 and not _is_toc_table(extracted):
                        section_tables.append(extracted)

            # ── Extract text OUTSIDE table bounding boxes ─────────────────────
            text = _extract_text_outside_tables(page)
            for line in text.split("\n"):
                line = clean(line)
                if line and len(line) > 1:   # skip single-char stray artifacts
                    all_lines.append(line)

    if not all_lines:
        print(f"   ⚠️  No text extracted from {pdf_path.name}")
        return {}

    full_text = " ".join(all_lines)

    # ── Date & issue ──────────────────────────────────────────────────────────
    header_text = " ".join(all_lines[:10])
    date_str, display_date, issue = parse_date_from_text(header_text)
    if not date_str:
        date_str, display_date, issue = parse_date_from_text(full_text[:600])

    # ── Helpers ───────────────────────────────────────────────────────────────
    _title_skip = re.compile(
        r"(ai daily|daily ai|daily brief|varun singla|issue|edition|your daily dose|curated|"
        r"page \d|what.s inside|what.s shaping|breakthroughs & trends|"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)[,\s])",
        re.I,
    )

    def _strip_trailing_date(s: str) -> str:
        """Remove trailing '. March 2026' or '· March 2026' date artifacts."""
        return re.sub(
            r"[.·,\s]+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
            r"\s+\d{4}\s*$", "", s, flags=re.I
        ).strip()

    # ── Title ─────────────────────────────────────────────────────────────────
    # Strategy 1: "Today's Focus: <title> [+ secondary topics]" inline
    # Strategy 2: The line AFTER "Today's Focus/Topic"
    # Fallback A: first numbered item from TOC table
    # Fallback B: first item from "What's Inside" text TOC
    # Fallback C: first sentence of focus_intro
    title = ""
    for i, line in enumerate(all_lines[:25]):
        low = line.lower()

        # "Today's Focus: Deep Dive: A2A Protocol + Apple's AI Siri …"
        # Take only the FIRST topic (before the first " + ")
        if re.search(r"today.s (focus|topic)\s*:", low):
            m = re.match(r"today.s (?:focus|topic)\s*:\s*(.+)", line, re.I)
            if m:
                raw = m[1].strip()
                # Split on " + " — the primary topic is the first segment
                parts = re.split(r'\s*\+\s*', raw)
                first = parts[0].strip()
                # If very short (e.g. just "AI") fall back to the full string
                if len(first) < 12 and len(parts) > 1:
                    first = raw
                candidate = _strip_trailing_date(first[:120])
                if len(candidate) > 15:
                    title = candidate
            break

        # "Today's Focus" on its own line — title is on following lines
        if re.search(r"today.s (focus|topic)$", low):
            for j in range(i + 1, min(i + 8, len(all_lines))):
                cand = all_lines[j]
                # Stop at numbered section headings — avoid picking up body text
                if re.match(r"^\d+\.\s", cand):
                    break
                if re.match(r"^[a-z]|^(becoming|that|which|where|and |or |but )", cand):
                    continue
                if (20 < len(cand) < 130
                        and not _title_skip.search(cand)
                        and not re.search(r"^(today we|this edition|in this|if you)", cand, re.I)):
                    title = _strip_trailing_date(cand)
                    break
            break

        if re.search(r"what.s inside", low):
            break
        if len(line) > 20 and not _title_skip.search(line):
            title = _strip_trailing_date(line)
            break

    # Fallback A: look for TOC in single-column raw tables (e.g. "What's Inside" table)
    if not title and raw_tables:
        for tbl in raw_tables[:4]:
            if tbl and all(len(row) <= 1 for row in tbl):
                for row in tbl:
                    if row and row[0]:
                        cell = clean_table_cell(row[0])
                        m = re.match(r'^\d+\.\s+(.{10,80})', cell)
                        if m:
                            title = _strip_trailing_date(m[1].strip())
                            break
                if title:
                    break

    # Fallback B: first item from "What's Inside" text TOC
    if not title:
        for i, line in enumerate(all_lines[:25]):
            if re.search(r"what.s inside|in this edition", line, re.I):
                for j in range(i + 1, min(i + 10, len(all_lines))):
                    cand = all_lines[j]
                    m = re.match(r"^\d+[.:\s]+(.+)", cand)
                    if m and len(m[1]) > 10:
                        title = _strip_trailing_date(m[1].strip()[:90])
                        break
                break

    # ── Today's Focus / Topic intro paragraph ─────────────────────────────────
    focus_intro = ""
    for i, line in enumerate(all_lines):
        low = line.lower()
        if re.search(r"today.s (focus|topic)", low):
            inline_m = re.match(r"today.s (?:focus|topic)\s*:\s*(.+)", line, re.I)
            if inline_m:
                # For inline "Today's Focus: ..." format, build the intro by:
                # 1. Looking for a "Today we [go deeper into / deep dive into] X" sentence
                #    that may be buried inside a "Yesterday's Recap" continued line
                # 2. Otherwise collecting the next standalone narrative lines
                intro_parts = []
                in_yesterday = False
                for j in range(i + 1, min(i + 14, len(all_lines))):
                    l = all_lines[j]
                    if is_section_heading(l) or re.search(r"what.s inside", l, re.I):
                        break
                    if re.search(r"yesterday.s recap", l, re.I):
                        in_yesterday = True
                    if re.match(r"^\+\s*(viral app|industry|also)", l, re.I):
                        continue
                    # Stop at ALL-CAPS bullet section markers: "• MAIN TOPIC --" or "• INDUSTRY FLASH"
                    if re.match(r'^[•*]\s+[A-Z][A-Z\s]{4,}(?:--|—|-|\Z)', l):
                        break
                    if in_yesterday:
                        # Extract "Today we …" sentence from within recap continuation
                        # (may not end with sentence terminator on the same line — that's OK)
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
                    # Fall back to the topic title as the intro hint
                    focus_intro = inline_m[1].strip()
            else:
                # Standalone "Today's Focus" — collect next substantial lines
                intro_parts = []
                for j in range(i + 1, min(i + 6, len(all_lines))):
                    l = all_lines[j]
                    if is_section_heading(l) or re.search(r"what.s inside", l, re.I):
                        break
                    if len(l) > 30:
                        intro_parts.append(l)
                focus_intro = " ".join(intro_parts)
            break

    # Title fallback 2: first sentence of focus_intro — skip "Today we…" lead-ins
    if not title and focus_intro:
        fi = re.sub(r"^(Today we[^.!?]+[.!?]\s*|This edition[^.!?]+[.!?]\s*)", "", focus_intro, flags=re.I).strip()
        m = re.match(r"(.{20,90}?[.!?])\s", fi)
        if m:
            title = m[1]
        elif fi:
            title = fi[:90].rstrip()

    # ── Sections ──────────────────────────────────────────────────────────────
    sections: list[dict] = []
    skip_headings = re.compile(
        r"(today.s (focus|topic)|what.s inside|ai daily learning|daily ai learning|"
        r"your daily dose|daily brief|sources|further reading|page \d|varun singla"
        r"|yesterday.s recap|generated by)", re.I
    )

    i = 0
    while i < len(all_lines):
        line = all_lines[i]

        if is_section_heading(line) and not skip_headings.search(line):
            sec_title = line
            paragraphs: list[str] = []
            bullets: list[str] = []
            current_para: list[str] = []

            j = i + 1
            while j < len(all_lines):
                next_line = all_lines[j]

                # Stop at the next numbered top-level section heading
                if (is_section_heading(next_line)
                        and not skip_headings.search(next_line)
                        and (re.match(r"^\d+\.\s", next_line) or re.match(r"^\d{1,2}\s*[-—–]{1,2}\s+\S", next_line))
                        and j != i + 1):
                    break

                # Also stop at "Tomorrow's Preview" and footer boilerplate
                if re.match(r"(tomorrow.s? preview|ai daily learning|generated by)", next_line, re.I):
                    j += 1
                    continue

                if skip_headings.search(next_line):
                    j += 1
                    continue

                if is_bullet(next_line):
                    if current_para:
                        paragraphs.append(" ".join(current_para))
                        current_para = []
                    bullets.append(extract_bullet_text(next_line))
                elif len(next_line) > 40:
                    # If this line is a lowercase continuation of the previous bullet,
                    # append it to the last bullet instead of starting a new paragraph
                    if (bullets and not current_para
                            and (next_line[0].islower()
                                 or re.match(r'^(and|but|or|to|of|for|that|which|however|road)\b',
                                             next_line, re.I))):
                        bullets[-1] = bullets[-1] + " " + next_line
                    else:
                        current_para.append(next_line)
                elif len(next_line) > 10:
                    if current_para:
                        paragraphs.append(" ".join(current_para))
                        current_para = []

                j += 1

            if current_para:
                paragraphs.append(" ".join(current_para))

            sec: dict = {"title": sec_title}
            if paragraphs:
                sec["paragraphs"] = paragraphs
            if bullets:
                sec["bullets"] = bullets

            # Attach the next available section table (greedy — ordered by document position)
            if section_tables:
                raw_t = section_tables.pop(0)
                clean_t = [[clean_table_cell(cell) for cell in row] for row in raw_t]
                # Filter out fully-empty rows
                clean_t = [row for row in clean_t if any(c for c in row)]
                if len(clean_t) >= 2:
                    headers = clean_t[0]
                    rows = clean_t[1:]
                    sec["table"] = {"headers": headers, "rows": rows}

            sections.append(sec)
            i = j
        else:
            i += 1

    # ── Viral app ──────────────────────────────────────────────────────────────
    viral_app = None
    for sec in sections[:]:
        if re.search(r"viral app", sec.get("title", ""), re.I):
            # Try to get app name from section title (e.g. "5. Viral App Spotlight — Moltbot")
            name = re.sub(
                r"^[\d\.\s]*viral app spotlight\s*[:\-—–]*\s*", "",
                sec["title"], flags=re.I
            ).strip()

            paras = sec.get("paragraphs", [])
            buls  = sec.get("bullets", [])

            # If name not in title, the first paragraph line is usually the app name
            if not name and paras:
                first_para = paras[0]
                # App name: typically a short capitalised line at the very start
                # (before "Status:", "Why It's", etc.)
                name_m = re.match(r'^([A-Z][^\.\n]{5,70})(?:\s+(?:Status|Why|What|How)|$)', first_para)
                if name_m:
                    name = name_m[1].strip()
                    # Remove the extracted name from the first paragraph
                    rest = first_para[len(name):].strip()
                    paras = ([rest] if rest else []) + paras[1:]

            # Also look at section table (e.g. a 1-column table with the app name)
            if not name and sec.get("table"):
                first_header = sec["table"]["headers"][0] if sec["table"].get("headers") else ""
                if first_header and re.match(r'^[A-Z]', first_header) and len(first_header) < 80:
                    name = first_header

            desc = " ".join(paras[:3] + buls[:4])
            viral_app = {
                "name": name or "See details below",
                "description": desc[:500],
            }
            sections.remove(sec)
            break

    # Fallback 1: "Viral App: X" in Today's Focus header line (e.g. Mar 23 style)
    if not viral_app:
        m = re.search(r"\+\s*Viral\s+App[:\s]+([A-Z][^\s\+\n,]{2,50}(?:\s+\([^)]+\))?)", full_text, re.I)
        if m:
            vname = clean(m[1].strip())
            # Prefer a description from body text ("Moltbot is the consumer face of…")
            desc_m = re.search(
                re.escape(vname) + r'\s+(?:is|was|went|launched|racked).{5,400}', full_text, re.I
            )
            if not desc_m:
                # Look for "Why It Matters" or "What Makes" sentence
                desc_m = re.search(r'Why It Matters.{5,300}', full_text, re.I)
            viral_app = {
                "name": vname,
                "description": clean(desc_m[0][:400]) if desc_m else "",
            }

    # Fallback 2: update name-only if viral_app was set but name is "See details below"
    # — look in single-column raw tables for the actual app name
    if viral_app and viral_app.get("name") == "See details below":
        for tbl in raw_tables:
            if not tbl:
                continue
            first_cell = clean_table_cell(tbl[0][0] if tbl[0] else "")
            if (len(tbl[0]) == 1
                    and re.match(r'^[A-Z]', first_cell)
                    and 5 < len(first_cell) < 80
                    and not re.search(
                        r"(what.s inside|issue|edition|today|component|model|dimension|"
                        r"organisation|organisation|date|topic|what is|how it)", first_cell, re.I
                    )):
                viral_app["name"] = first_cell
                break

    # Fallback 3: generic full-text pattern
    if not viral_app:
        m = re.search(r"viral app[:\s]+([A-Z][^\n\.+]{5,60})", full_text, re.I)
        if m:
            viral_app = {"name": clean(m[1].strip()), "description": ""}

    # ── Market signal ──────────────────────────────────────────────────────────
    market_signal = ""
    # Match everything from "Market Signal:" to end-of-paragraph / next section
    m = re.search(
        r"Market Signal[:\s]+(.+?)(?=\s*\d+\.\s+[A-Z]|Generated by|Tomorrow|$)",
        full_text, re.I | re.S
    )
    if m:
        ms_raw = m[1].strip()
        # Trim to at most 2 sentences for readability
        sentences = re.split(r'(?<=[.!?])\s+', ms_raw)
        market_signal = clean(" ".join(sentences[:3]))

    # ── Practical takeaway ─────────────────────────────────────────────────────
    practical_takeaway = ""
    for sec in sections[:]:
        if re.search(r"(practical takeaway|key takeaway)", sec.get("title", ""), re.I):
            parts = sec.get("paragraphs", []) + sec.get("bullets", [])
            practical_takeaway = " ".join(parts)
            sections.remove(sec)
            break

    # Fallback: look for "Key Takeaways" / "Your Action" in raw tables
    if not practical_takeaway:
        for tbl in raw_tables:
            if not tbl:
                continue
            first_cell = clean_table_cell(tbl[0][0] if tbl[0] else "")
            if re.search(r"(key takeaway|practical takeaway|your action|action point)", first_cell, re.I):
                # 2-column table where first col = topic, second = content
                parts = []
                for row in tbl[1:]:
                    if row and len(row) >= 2:
                        parts.append(clean_table_cell(row[1]) or clean_table_cell(row[0]))
                    elif row:
                        parts.append(clean_table_cell(row[0]))
                practical_takeaway = " ".join(p for p in parts if p)
                if practical_takeaway:
                    break

    # Fallback: extract from the last section if it looks like a summary
    if not practical_takeaway and sections:
        last = sections[-1]
        if re.search(r"(takeaway|summary|conclusion|what.s next|final)", last.get("title", ""), re.I):
            parts = last.get("paragraphs", []) + last.get("bullets", [])
            practical_takeaway = " ".join(parts)
            sections.remove(last)

    # ── Key stats ──────────────────────────────────────────────────────────────
    key_stats: list[str] = []

    # Priority 1: dedicated "Numbers Worth Knowing" section
    for sec in sections[:]:
        if re.search(r"numbers worth|key stats|key figures", sec.get("title", ""), re.I):
            if sec.get("table"):
                for row in sec["table"]["rows"]:
                    if len(row) >= 2:
                        key_stats.append(f"{row[0]}: {row[1]}")
            key_stats += sec.get("bullets", [])
            sections.remove(sec)
            break

    # Priority 2: stat-box tables (single/double row with big numbers)
    if not key_stats:
        key_stats = _extract_stat_box_tables(raw_tables)

    # Priority 3: pull numeric references from full text
    if not key_stats:
        nums = re.findall(
            r'[\$£€]?\d[\d,]*(?:\.\d+)?[%KMBTx+]*\b[^.]{0,60}'
            r'(?:billion|million|trillion|%|K\+|stars|organisations|organizations|companies|countries)',
            full_text, re.I
        )
        key_stats = [clean(n.strip()) for n in nums[:6] if len(n.strip()) > 8]

    # ── Tomorrow preview ───────────────────────────────────────────────────────
    tomorrow_preview = ""
    m = re.search(r"tomorrow.s? preview[:\s]+(.{10,300}?)(?:\.|$)", full_text, re.I)
    if m:
        tomorrow_preview = clean(m[1])

    # ── Remove boilerplate + sub-step sections ─────────────────────────────────
    sections = [
        s for s in sections
        if not re.search(r"(sources|further reading|what.s inside|your agentic ai learning map|learning map)", s.get("title", ""), re.I)
        and (s.get("paragraphs") or s.get("bullets") or s.get("table"))
        # Sub-steps: numbered + colon + long description → real headings are concise (< 56 chars)
        and not (re.match(r"^\d+\.", s.get("title", "")) and len(s.get("title", "")) > 55)
    ]

    # ── Deduplicate sections (TOC entries vs actual body content) ──────────────
    # Keep the version with the most narrative content.
    # Scoring: paragraphs 3×, bullets 2×, table 1 point
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
                # Preserve table from whichever had it
                if not better.get("table") and deduped[old_idx].get("table"):
                    better["table"] = deduped[old_idx]["table"]
                deduped[old_idx] = better
        else:
            seen_titles[key] = len(deduped)
            deduped.append(sec)

    # ── Sort sections by numeric prefix (document order) ──────────────────────
    def _sec_sort_key(s: dict) -> tuple:
        m = re.match(r"^(\d+)", s.get("title", ""))
        return (int(m[1]), s.get("title", "")) if m else (999, s.get("title", ""))

    deduped.sort(key=_sec_sort_key)
    sections = deduped

    # ── focus_intro post-processing ───────────────────────────────────────────
    # If focus_intro still looks like a topic title list (has " + " secondary topics),
    # has a dangling section header, or is an incomplete sentence (no terminal punctuation),
    # fall back to the first paragraph of the first section as a proper narrative intro.
    _intro_needs_replacement = (
        focus_intro and (
            re.search(r'\+\s*(?:Viral App|Industry|Apple|Mistral|Samsung|OpenAI|Google)', focus_intro, re.I)
            or re.search(r'MAIN TOPIC|INDUSTRY FLASH', focus_intro)
            or not re.search(r'[.!?]$', focus_intro.rstrip())
        )
    )
    if _intro_needs_replacement:
        for sec in sections:
            if sec.get("paragraphs"):
                focus_intro = sec["paragraphs"][0]
                break

    # ── Validation ────────────────────────────────────────────────────────────
    warnings = []
    if not issue:
        warnings.append("'issue' number not found — check PDF header for 'Issue #N' or 'Edition #N'")
    if not viral_app:
        warnings.append("'viral_app' not found — check for a 'Viral App Spotlight' section")
    if not practical_takeaway:
        warnings.append("'practical_takeaway' not found — check for 'Key Takeaways' or 'Practical Takeaway' section")
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
        "sections":           sections,
        "key_stats":          key_stats,
        **({"market_signal": market_signal} if market_signal else {}),
        **({"practical_takeaway": practical_takeaway} if practical_takeaway else {}),
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

    if not entry.get("date"):
        entry["date"]         = dt.strftime("%Y-%m-%d")
        entry["display_date"] = dt.strftime("%B %-d, %Y")

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
