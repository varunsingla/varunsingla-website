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
    """Strip extra whitespace and common PDF artifacts."""
    text = re.sub(r"\s+", " ", text).strip()
    # Fix common PDF encoding issues
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u2014", "--").replace("\u2013", "-").replace("\u2022", "*")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text


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
    ]
    low = line.lower()
    for h in headings:
        if low.startswith(h):
            return True
    return False


def is_bullet(line: str) -> bool:
    # Standard bullets + the 'n ' / ')n ' / 'nn ' PDF artifact bullets
    return bool(
        re.match(r"^[•\-\*▸▶◆●▪]\s", line)
        or re.match(r"^\d+\.\s", line)
        or re.match(r"^[n\)]+n?\s+[A-Z]", line)   # PDF artifact: 'n Title', ')n Title', 'nn Title'
    )


def extract_bullet_text(line: str) -> str:
    # Remove leading bullet chars, PDF artifact 'n'/'nn'/etc.
    line = re.sub(r"^[•\-\*▸▶◆●▪\d\.]+\s+", "", line)
    line = re.sub(r"^[n\)]+n?\s+", "", line)
    return line.strip()


def parse_date_from_text(text: str) -> tuple[str, str, int | None]:
    """Extract date_str, display_date, issue_number from PDF header text."""
    # Issue number
    issue = None
    m = re.search(r"issue\s*#?(\d+)", text, re.IGNORECASE)
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


def parse_pdf(pdf_path: Path) -> dict:
    """Parse a daily AI learning PDF into a rich structured dict."""
    print(f"   📄 Parsing: {pdf_path.name}")

    all_lines = []
    page_tables = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Extract tables
            tables = page.extract_tables() or []
            for t in tables:
                if t and len(t) > 1:
                    page_tables.append(t)
            # Extract text
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            for line in text.split("\n"):
                line = clean(line)
                if line:
                    all_lines.append(line)

    if not all_lines:
        print(f"   ⚠️  No text extracted from {pdf_path.name}")
        return {}

    full_text = " ".join(all_lines)

    # ── Date & issue ──────────────────────────────────────────────────────────
    header_text = " ".join(all_lines[:10])
    date_str, display_date, issue = parse_date_from_text(header_text)
    if not date_str:
        date_str, display_date, issue = parse_date_from_text(full_text[:500])

    # ── Title ─────────────────────────────────────────────────────────────────
    # Strategy: look for the topic title, which is often the line right AFTER
    # "Today's Focus/Topic", or the first substantive non-metadata line.
    _title_skip = re.compile(
        r"(ai daily|daily ai|varun singla|issue|your daily dose|curated|"
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

    title = ""
    for i, line in enumerate(all_lines[:20]):
        low = line.lower()
        # "Today's Focus/Topic" line — look at the NEXT lines for the actual topic title
        if re.search(r"today.s (focus|topic)", low):
            for j in range(i + 1, min(i + 8, len(all_lines))):
                cand = all_lines[j]
                # Skip mid-sentence continuations
                if re.match(r"^[a-z]|^(becoming|that|which|where|and |or |but )", cand):
                    continue
                if (20 < len(cand) < 130
                        and not _title_skip.search(cand)
                        and not re.search(r"^(today we|this edition|in this|if you)", cand, re.I)
                        and not re.match(r"^\d+\.", cand)):
                    title = _strip_trailing_date(cand)
                    break
            break
        if re.search(r"what.s inside", low):
            break
        if len(line) > 20 and not _title_skip.search(line):
            title = _strip_trailing_date(line)
            break
    # Fallback 1: first item from "What's Inside" TOC
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
    # Fallback 2: derive a short title from focus_intro first sentence
    # (will be set after focus_intro is parsed below — see the block after it)

    # ── Today's Focus / Topic ─────────────────────────────────────────────────
    focus_intro = ""
    for i, line in enumerate(all_lines):
        if re.search(r"today.s (focus|topic)", line, re.I):
            # Collect the next 1-3 lines as the intro paragraph
            intro_parts = []
            for j in range(i + 1, min(i + 6, len(all_lines))):
                l = all_lines[j]
                if is_section_heading(l) or re.search(r"what.s inside", l, re.I):
                    break
                if len(l) > 30:
                    intro_parts.append(l)
            focus_intro = " ".join(intro_parts)
            break

    # Title fallback 3: first sentence of focus_intro — but skip "Today we..." lead-ins
    if not title and focus_intro:
        fi = re.sub(r"^(Today we[^.!?]+[.!?]\s*|This edition[^.!?]+[.!?]\s*)", "", focus_intro, flags=re.I).strip()
        m = re.match(r"(.{20,90}?[.!?])\s", fi)
        if m:
            title = m[1]
        elif fi:
            title = fi[:90].rstrip()

    # ── Sections ──────────────────────────────────────────────────────────────
    sections = []
    skip_headings = re.compile(
        r"(today.s (focus|topic)|what.s inside|ai daily learning|your daily dose"
        r"|sources|further reading|page \d|varun singla)", re.I
    )

    i = 0
    while i < len(all_lines):
        line = all_lines[i]

        if is_section_heading(line) and not skip_headings.search(line):
            sec_title = line
            paragraphs = []
            bullets = []
            current_para = []

            j = i + 1
            while j < len(all_lines):
                next_line = all_lines[j]

                # Stop at next major section heading (numbered = new top section)
                if (is_section_heading(next_line)
                        and not skip_headings.search(next_line)
                        and (re.match(r"^\d+\.\s", next_line) or re.match(r"^\d{1,2}\s*[-—–]{1,2}\s+\S", next_line))
                        and j != i + 1):
                    break

                if skip_headings.search(next_line):
                    j += 1
                    continue

                if is_bullet(next_line):
                    if current_para:
                        paragraphs.append(" ".join(current_para))
                        current_para = []
                    bullets.append(extract_bullet_text(next_line))
                elif len(next_line) > 40:
                    current_para.append(next_line)
                elif len(next_line) > 10:
                    # Could be a sub-heading — flush para and treat as next heading
                    if current_para:
                        paragraphs.append(" ".join(current_para))
                        current_para = []

                j += 1

            if current_para:
                paragraphs.append(" ".join(current_para))

            sec = {"title": sec_title}
            if paragraphs:
                sec["paragraphs"] = paragraphs
            if bullets:
                sec["bullets"] = bullets

            # Attach any table that seems to belong to this section
            # (simple heuristic: use tables in order of occurrence)
            if page_tables:
                t = page_tables.pop(0)
                clean_t = [[clean(str(cell or "")) for cell in row] for row in t]
                if len(clean_t) > 1 and any(any(c for c in row) for row in clean_t):
                    headers = clean_t[0]
                    rows = clean_t[1:]
                    sec["table"] = {"headers": headers, "rows": rows}

            sections.append(sec)
            i = j
        else:
            i += 1

    # ── Viral app ──────────────────────────────────────────────────────────────
    viral_app = None
    for sec in sections:
        if re.search(r"viral app", sec.get("title", ""), re.I):
            name = re.sub(r"^[\d\.\s]*viral app spotlight[:\s]*", "", sec["title"], flags=re.I).strip()
            desc = " ".join(sec.get("paragraphs", []) + sec.get("bullets", []))
            viral_app = {"name": name or "See details below", "description": desc[:400]}
            sections.remove(sec)
            break

    if not viral_app:
        m = re.search(
            r"viral app[:\s]+([^\n\.]{5,60})[.\n]([^\n]{10,200})", full_text, re.I
        )
        if m:
            viral_app = {"name": clean(m[1]), "description": clean(m[2])}

    # ── Market signal ──────────────────────────────────────────────────────────
    market_signal = ""
    m = re.search(r"market signal[:\s]+(.{30,400}?)(?:\n\n|\Z)", full_text, re.I | re.S)
    if m:
        market_signal = clean(m[1])

    # ── Practical takeaway ─────────────────────────────────────────────────────
    practical_takeaway = ""
    for sec in sections[:]:
        if re.search(r"(practical takeaway|key takeaway)", sec.get("title", ""), re.I):
            practical_takeaway = " ".join(
                sec.get("paragraphs", []) + sec.get("bullets", [])
            )
            sections.remove(sec)
            break

    # ── Key stats ──────────────────────────────────────────────────────────────
    key_stats = []
    for sec in sections[:]:
        if re.search(r"numbers worth|key stats|key figures", sec.get("title", ""), re.I):
            if sec.get("table"):
                for row in sec["table"]["rows"]:
                    if len(row) >= 2:
                        key_stats.append(f"{row[0]}: {row[1]}")
            key_stats += sec.get("bullets", [])
            sections.remove(sec)
            break

    if not key_stats:
        # Pull numbers from full text as fallback
        nums = re.findall(r"[\$\d][^\n\.]{5,60}(?:billion|million|%|K\+|stars)[^\n\.]{0,40}", full_text)
        key_stats = [clean(n) for n in nums[:6]]

    # ── Tomorrow preview ───────────────────────────────────────────────────────
    tomorrow_preview = ""
    m = re.search(r"tomorrow.s? preview[:\s]+(.{10,200}?)(?:\n|\Z)", full_text, re.I)
    if m:
        tomorrow_preview = clean(m[1])

    # ── Remove boilerplate sections ────────────────────────────────────────────
    sections = [
        s for s in sections
        if not re.search(r"(sources|further reading|what.s inside)", s.get("title", ""), re.I)
        and (s.get("paragraphs") or s.get("bullets") or s.get("table"))
    ]

    # ── Deduplicate sections (TOC entries vs actual content) ───────────────────
    # When a PDF has a "What's Inside" table of contents, those items get parsed
    # as sections too. Deduplicate by title, keeping the most content-rich copy.
    seen: dict[str, tuple[int, int]] = {}   # title → (index_in_deduped, score)
    deduped: list[dict] = []
    for sec in sections:
        key = sec.get("title", "").strip().lower()
        score = len(sec.get("paragraphs", [])) + len(sec.get("bullets", [])) + (2 if sec.get("table") else 0)
        if key in seen:
            old_idx, old_score = seen[key]
            if score > old_score:
                deduped[old_idx] = sec
                seen[key] = (old_idx, score)
            # else keep the existing (more content-rich) copy
        else:
            seen[key] = (len(deduped), score)
            deduped.append(sec)
    sections = deduped

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

def github_push(config: dict, data: dict) -> bool:
    """Push learnings.json to GitHub via REST API — no git required."""
    import urllib.error
    import urllib.request

    token = config.get("github_token") or os.environ.get("GITHUB_TOKEN", "")
    user  = config.get("github_user", "")
    repo  = config.get("github_repo", "")

    if not all([token, user, repo]):
        print("   ⚠️  GitHub config incomplete — skipping push.")
        print("       Set github_token, github_user, github_repo in config.json")
        return False

    api_url = f"https://api.github.com/repos/{user}/{repo}/contents/learnings.json"
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
        "Content-Type":  "application/json",
    }

    # Get current SHA (required for update)
    sha = None
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            sha = json.loads(resp.read())["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"   ⚠️  Could not fetch current file SHA: {e}")

    # Encode content
    content_str  = json.dumps(data, indent=2, ensure_ascii=False)
    content_b64  = base64.b64encode(content_str.encode()).decode()
    today        = datetime.now().strftime("%Y-%m-%d")

    payload = {"message": f"Daily update: {today}", "content": content_b64}
    if sha:
        payload["sha"] = sha

    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="PUT",
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            html_url = result.get("content", {}).get("html_url", "")
            print(f"   ✅  Pushed to github.com/{user}/{repo}")
            print(f"       Live at: https://varunsingla.com")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"   ❌  GitHub API error {e.code}: {body[:200]}")
        return False
    except Exception as e:
        print(f"   ❌  Push failed: {e}")
        return False


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
    print(f"   Title:    {entry.get('title', '(untitled)')[:60]}")
    print(f"   Sections: {len(entry.get('sections', []))}")
    print(f"   Viral:    {entry.get('viral_app', {}).get('name', 'none')}")

    # ── Merge into JSON ───────────────────────────────────────────────────────
    print("📝  Updating learnings.json …")
    data, action = merge_entry(data, entry)
    LEARNINGS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"   ✅  Entry {action} ({len(data['learnings'])} total days)")

    # ── Push to GitHub ────────────────────────────────────────────────────────
    print("🚀  Pushing to GitHub …")
    github_push(config, data)

    print("─" * 54)
    print("✅  Done!\n")


if __name__ == "__main__":
    main()
