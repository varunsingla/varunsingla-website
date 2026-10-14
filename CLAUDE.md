# CLAUDE.md

## Daily AI Learning automation

This repo is updated by a daily autonomous "Daily AI Learning" routine that:
1. Researches the day's AI news and generates `AI_Learning_Day<NNN>_<YYYY-MM-DD>.pdf` in the repo root, following
   the established layout (title/subtitle, numbered `N)` sections, VIRAL/OPEN-SOURCE SPOTLIGHT bar, MARKET SIGNAL
   bar, numbered PRACTICAL TAKEAWAYS, TOMORROW preview, footer).
2. Commits and pushes that PDF.
3. A separate publish routine (`update_site.py`) picks up the new PDF, repairs/normalises the stored entries,
   updates `learnings.json`, and regenerates every static page via `generate_geo.py` (`entries/*.html`,
   `playbook/`, `concepts/`, `watching/`, `start/`, `weekly/`, `review/`, `index.json`, `search.json`,
   `sitemap.xml`, `feed.xml`, `llms.txt`, `llms-full.txt`, and the generated regions of `index.html`).

### What the PDF should contain (so the site can use it)

The parser reads the first page by font size: the largest text is the headline, the next block is the deck.
Please keep writing the PDF this way, and include these lines — each one feeds a page on the site:

- **A real headline on page 1.** "AI Learning -- Day N" is not a headline; the site shows it on the home card,
  the archive, the RSS feed and llms.txt. Put the day number in the running header/footer instead.
- **A deck line under the headline** (one or two lines naming the day's stories). It becomes the entry's
  `subtitle`, shown under the title on every card.
- **`Themes: <one or two of>` Foundations & Protocols · Industry Verticals · Enterprise & Strategy ·
  Infrastructure & Economics · Models & Frontier · Governance & Safety** — on its own line near the top.
  Without it the site guesses the themes from keywords.
- **"The concept, explained simply:" and "Why it matters:"** inside each numbered section. These paragraphs are
  extracted into the Concepts glossary and the Review flashcards, so keep the exact phrasing.
- **`PRACTICAL TAKEAWAYS`** as numbered items with a short bold-style title line followed by a one-sentence body.
  Each becomes a Playbook item and a flashcard.
- **`TOMORROW`** heading followed by "What We're Watching: …" sentences. Feeds the Watching tracker.
- **`SELF-TEST`** (optional, recommended): three to five pairs in the form `Q1. question` / `A1. answer`. These
  become self-test cards on the entry page and in Review.
- **`Sources:`** line at the end naming the outlets/pages used (URLs welcome; they are auto-linked).
- **`TOPICS COVERED SO FAR (RECAP)`** paragraph (as on Day 199/200) — the latest one is shown on Start Here.

Also note: the PDF's own day counter has drifted from the site's count (the site numbers entries by position
in `learnings.json`; the Day-200 PDF is site Day 206). Prefer `len(learnings.json["learnings"]) + 1` as the
day number when generating the PDF so the two stay aligned.

### Publishing and repair

- `python3 update_site.py` — normal daily run: repairs any stored entry that predates the current schema
  (idempotent, no-op once current), parses the newest unprocessed PDF, merges it (richer entry wins, nothing is
  overwritten with less), regenerates everything, pushes via the GitHub API.
- `python3 update_site.py --repair [--dry-run] [--force]` — only the repair + regenerate pass, no push.
- `python3 update_site.py --parse <pdf>` — print what the parser extracts from one PDF (debugging).
- `python3 generate_geo.py` — regenerate the static site from `learnings.json` without touching the data.

Repairs never delete text: a replaced title or intro is kept under `title_original` / `focus_intro_original`,
viral-app names are only re-split from their descriptions, headings are only re-cased.

### ALWAYS push the day's commit to `main`, not just a session feature branch

The site's publish pipeline and GitHub Pages both read from `main`. Some sessions are assigned a designated
feature branch to develop on (e.g. `claude/eager-allen-pwi0t3`) and reuse the *same* branch name across multiple
days rather than a fresh one each run. Committing only to that branch is not enough — if it never gets merged,
`main` stalls and the publish routine has nothing new to find.

Before ending the daily task:

```bash
git fetch origin main
git log origin/main..HEAD --oneline     # should show only this run's new commit(s)
git push origin HEAD:main               # fast-forward push straight onto main
git log origin/main --oneline -3        # verify the new PDF commit landed on main
```

Only do this when it's a clean fast-forward (`git merge-base --is-ancestor origin/main HEAD` succeeds). If `main`
has diverged (unrelated commits on both sides), stop and surface it instead of force-pushing or merging blindly.

This broke once already: Day 103–104 (2026-07-09/2026-07-10) landed only on the feature branch, `main` stalled at
Day 102, and the publish routine silently had nothing to process until a human noticed and it was merged manually.
Don't let it happen again — the fast-forward push above is the fix, every single day.

If a merge conflict ever appears in `learnings.json` or a generated file, keep the version with the newest entry,
then run `python3 update_site.py --repair` and `python3 generate_geo.py`; the generated files are fully derived
from `learnings.json` + the PDFs, so regenerating resolves them.
