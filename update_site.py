#!/usr/bin/env python3
"""
update_site.py — Auto-update varunsingla.com AI learning blog

Reads your ai-learnings.md, updates learnings.json, commits & pushes to GitHub.
Run daily via scheduled task or manually: python3 update_site.py
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR      = Path(__file__).parent.resolve()
LEARNINGS_JSON  = SCRIPT_DIR / "learnings.json"
AI_LEARNINGS_MD = SCRIPT_DIR.parent / "memory" / "context" / "ai-learnings.md"
CONFIG_FILE     = SCRIPT_DIR / "config.json"
# ───────────────────────────────────────────────────────────────────────────────


def load_config() -> dict:
    """Load GitHub config from config.json"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"⚠️  config.json is malformed: {e}")
    return {}


def fmt_display_date(date_str: str) -> str:
    """Convert '2026-03-22' → 'March 22, 2026'"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day = dt.day
        return dt.strftime(f"%B {day}, %Y")
    except ValueError:
        return date_str


def clean_md(text: str) -> str:
    """Strip markdown bold/italic markers"""
    return re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text).strip()


def parse_section(raw: str) -> dict | None:
    """Parse a single ## date section from ai-learnings.md"""
    lines = raw.strip().splitlines()
    if not lines:
        return None

    # Header: ## 2026-03-22 — Title
    header = re.match(r"^##\s+(\d{4}-\d{2}-\d{2})\s+[—\-–]+\s+(.+)$", lines[0])
    if not header:
        return None

    date_str     = header.group(1)
    title        = header.group(2).strip()
    display_date = fmt_display_date(date_str)

    topics:          list[str] = []
    key_stats:       list[str] = []
    tomorrow_preview: str      = ""
    viral_app:       dict | None = None
    current_section: str | None  = None

    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue

        # Section headers
        low = line.lower()
        if "**topics covered:**" in low:
            current_section = "topics"; continue
        if "**key stats shared:**" in low or "**key stats:**" in low:
            current_section = "stats"; continue
        if "**tomorrow" in low and "preview" in low:
            # Inline: **Tomorrow's Preview:** text here
            preview_match = re.search(r"\*\*.+?:\*\*\s*(.+)", line)
            if preview_match:
                tomorrow_preview = clean_md(preview_match.group(1))
            current_section = None; continue
        if re.match(r"^\*\*.+\*\*$", line):          # Bold-only header line
            current_section = None; continue

        # List items
        if line.startswith("- "):
            item = line[2:].strip()

            # Viral App pattern: **Viral App:** Name — description
            va = re.match(
                r"\*\*Viral App:\*\*\s+(.+?)\s+(?:—|–|-{2,})\s+(.+)", item
            )
            if va:
                viral_app = {
                    "name": va.group(1).strip(),
                    "description": va.group(2).strip(),
                }
                continue

            # Also catch bold inline label like "**Viral App:** OpenAI..."
            va2 = re.match(r"\*\*Viral App:\*\*\s+(.+)", item)
            if va2:
                parts = re.split(r"\s+(?:—|–|-{2,})\s+", va2.group(1), maxsplit=1)
                viral_app = {
                    "name": parts[0].strip(),
                    "description": parts[1].strip() if len(parts) > 1 else "",
                }
                continue

            cleaned = clean_md(item)
            if current_section == "topics":
                topics.append(cleaned)
            elif current_section == "stats":
                key_stats.append(cleaned)

    return {
        "date":             date_str,
        "display_date":     display_date,
        "title":            title,
        "viral_app":        viral_app,
        "topics":           topics,
        "key_stats":        key_stats,
        "tomorrow_preview": tomorrow_preview,
    }


def parse_learnings_md() -> list[dict]:
    """Parse all date sections from ai-learnings.md"""
    md_path = AI_LEARNINGS_MD.resolve()
    if not md_path.exists():
        print(f"❌  ai-learnings.md not found at:\n   {md_path}")
        print("    Make sure the path is correct in update_site.py (AI_LEARNINGS_MD)")
        return []

    content = md_path.read_text(encoding="utf-8")
    # Split on ## YYYY-MM-DD headers
    raw_sections = re.split(r"\n(?=## \d{4}-\d{2}-\d{2})", content)
    entries = [e for e in (parse_section(s) for s in raw_sections) if e]
    entries.sort(key=lambda x: x["date"], reverse=True)   # newest first
    return entries


def update_learnings_json(new_entries: list[dict]) -> dict:
    """Merge new entries into learnings.json and save"""
    if LEARNINGS_JSON.exists():
        with open(LEARNINGS_JSON, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {
            "profile": {
                "name":     "Varun Singla",
                "tagline":  "Learning fast. Staying ahead.",
                "subtitle": "Daily AI breakthroughs, insights & trends — tracked one day at a time.",
            },
            "learnings": [],
        }

    index_by_date = {l["date"]: i for i, l in enumerate(data["learnings"])}

    added = updated = 0
    for entry in new_entries:
        if entry["date"] in index_by_date:
            data["learnings"][index_by_date[entry["date"]]] = entry
            updated += 1
        else:
            data["learnings"].append(entry)
            added += 1

    data["learnings"].sort(key=lambda x: x["date"], reverse=True)

    with open(LEARNINGS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"   ✅  learnings.json — {len(data['learnings'])} total entries "
          f"(+{added} new, {updated} updated)")
    return data


def git_push(config: dict) -> bool:
    """Stage, commit, and push learnings.json to GitHub Pages"""
    token = config.get("github_token") or os.environ.get("GITHUB_TOKEN", "")
    user  = config.get("github_user", "")
    repo  = config.get("github_repo", "")
    branch = config.get("github_branch", "main")

    if not all([token, user, repo]):
        print("⚠️   GitHub config incomplete — skipping push.")
        print("    Set github_token, github_user, github_repo in config.json")
        return False

    os.chdir(SCRIPT_DIR)
    today = datetime.now().strftime("%Y-%m-%d")
    remote_url = f"https://{token}@github.com/{user}/{repo}.git"

    try:
        # Point origin at authenticated URL
        subprocess.run(
            ["git", "remote", "set-url", "origin", remote_url],
            capture_output=True, check=True,
        )

        # Stage learnings.json
        subprocess.run(
            ["git", "add", "learnings.json"],
            capture_output=True, check=True,
        )

        # Check if there's anything staged
        diff_check = subprocess.run(
            ["git", "diff", "--staged", "--quiet"], capture_output=True
        )
        if diff_check.returncode == 0:
            print("   ℹ️   No changes to commit — site is already up to date.")
            return True

        # Commit
        subprocess.run(
            ["git", "commit", "-m", f"Daily update: {today}",
             "--author", "AI Bot <bot@varunsingla.com>"],
            capture_output=True, check=True,
        )

        # Push
        subprocess.run(
            ["git", "push", "origin", branch],
            capture_output=True, check=True,
        )

        print(f"   ✅  Pushed to github.com/{user}/{repo} (branch: {branch})")
        print(f"       Live at: https://varunsingla.com")
        return True

    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace").strip() if e.stderr else ""
        print(f"   ❌  Git error: {e}")
        if stderr:
            print(f"       stderr: {stderr}")
        return False


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n🤖  AI Learning Blog Updater — {now}")
    print("─" * 52)

    print("📖  Parsing ai-learnings.md …")
    entries = parse_learnings_md()
    if not entries:
        print("⚠️   No entries parsed — nothing to update.")
        sys.exit(1)
    print(f"   Found {len(entries)} learning entries")

    print("📝  Updating learnings.json …")
    update_learnings_json(entries)

    print("🚀  Pushing to GitHub …")
    config = load_config()
    git_push(config)

    print("─" * 52)
    print("✅  Done!\n")


if __name__ == "__main__":
    main()
