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
  become self-test cards on the entry page and in Review. Keep the heading alone on its line: when the
  self-test comes straight after the takeaways, that line is where the parser ends the last takeaway. (The
  same goes for `TOPICS COVERED SO FAR` and `Sources:`. A new kind of block placed after the takeaways needs
  its heading added to `_starts_end_matter` in `update_site.py` first, or it is read as part of the last
  takeaway.)
- **`Sources:`** line at the end naming the outlets/pages used (URLs welcome; they are auto-linked).
- **`TOPICS COVERED SO FAR (RECAP)`** paragraph (as on Day 199/200) — the latest one is shown on Start Here.
- **Running header/footer: small print, in the page margin, the same on every page.** The current header is
  `AI Learning -- Day N | YYYY-MM-DD | Page N`. The parser takes these lines off each page before it reads the
  text, so a sentence that continues on the next page joins up instead of having the header stuck in the middle
  of it. It recognises the wordings used so far, and any small-print line in the top or bottom margin that
  repeats on another page — so keep the header/footer smaller than body text, out of the body area, and never
  put content there.
- **Write `&` as `&amp;` in ReportLab `Paragraph` text.** A bare `D&O` or `R&D` is printed as `D&O;` / `R&D;`
  (ReportLab closes what it takes for an entity). The parser undoes that shape, but it is better not to produce it.

Also note: the PDF's own day counter has drifted from the site's count (the site numbers entries by position
in `learnings.json`; the Day-200 PDF is site Day 206). Prefer `len(learnings.json["learnings"]) + 1` as the
day number when generating the PDF so the two stay aligned.

### Publishing and repair

- `python3 update_site.py` — normal daily run: repairs any stored entry that predates the current schema
  (idempotent, no-op once current), removes page furniture and a self-test that ran on into a takeaway from the
  stored text (see below), parses the newest unprocessed PDF, merges it (richer entry wins, nothing is
  overwritten with less), regenerates everything, pushes via the GitHub API.
- `python3 update_site.py --repair [--dry-run] [--force]` — only the repair + regenerate pass, no push.
  `--dry-run` prints what would change, entry by entry, and writes nothing. `--force` also re-runs the older
  repair steps on entries that are already current; those are not all idempotent (it re-splits viral-app names
  that are fine), so use it only when that is what you want.
- `python3 update_site.py --parse <pdf>` — print what the parser extracts from one PDF (debugging).
- `python3 generate_geo.py` — regenerate the static site from `learnings.json` without touching the data.
- `python3 check_learnings.py` — regression check, a few seconds. Exits 1 if a PDF page header/footer, a
  mangled ampersand (`D&O;`) or self-test text inside a takeaway (the `SELF-TEST` heading, or a `Q1.` … `A1.`
  pair) is found in `learnings.json`, in the generated pages, or in a fresh parse of the newest PDF; also if a
  takeaway repeats its entry's `recap` paragraph. `--all-pdfs` re-parses every PDF on disk (about two minutes).
  Run it after a publish or a repair.

Repairs never delete entry text: a replaced title or intro is kept under `title_original` /
`focus_intro_original`, viral-app names are only re-split from their descriptions, headings are only re-cased.
There are two exceptions. Both are text-only passes that read nothing but the stored entry, so they run over
every entry on every run, whatever the schema version (`SCHEMA_VERSION` is not bumped for them: a bump sends
every entry back through the older repair steps, which are not all idempotent).

1. **Page furniture, which was never entry content** (`scrub_entry`): the PDF's running header/footer where it
   got joined into the text (`AI Learning -- Day N | YYYY-MM-DD | Page N`, `Daily AI Learning for Varun`) and
   the stray `;` of a mangled ampersand (`D&O;` → `D&O`) are removed outright, with no `*_original` copy,
   because a copy would keep the artefact in `learnings.json`. Exactly those strings go and the words on either
   side are joined; a paragraph that was nothing but a footer is dropped.
2. **A self-test that ran on into the last takeaway** (`trim_takeaways`). Until 2026-11-22 the parser did not
   end the takeaways at the `SELF-TEST` heading, so the entries from 2026-10-15 on stored the whole quiz twice:
   in `quiz`, and as `… SELF-TEST Q1. … A1. …` at the end of the last takeaway's body. That copy is cut out,
   again with no `*_original`, and only where nothing is lost: everything after the heading has to be, question
   by question and answer by answer, the text stored in the same entry's `quiz` (the `Q1.` / `A1.` labels
   aside). If anything else follows the heading, the takeaway is left exactly as it is, `--repair` prints a
   warning for it, and `check_learnings.py` fails until someone has looked at it. The recap did the same once
   (2026-08-22, `… Topics Covered So Far 146 days in, …`) and is handled the same way: it is cut only where
   what follows the heading is exactly that entry's `recap`.

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

## Hand-maintained pages (not touched by the daily routine)

These carry model line-ups, prices and benchmark scores, so they go stale unless someone refreshes them by hand
(roughly monthly so far). The daily routine must leave them alone.

- `tools/model-team-evaluator.html` — the line-up lives in the inline `sources`, `models` and `watchModels`
  arrays. The quick-pick map (`recommendQuickPick`), `pickModelForStep`, the evaluator's synthesiser text and the
  dated copy (title, meta description, header pill, "what's new" cards, footer "Last sync") name models too and
  must change with them.
- `ai-tokenomics/index.html` — the price table (`#pricingTable`), the four scenario cards and the calculator
  `<select id="calcModel">` must agree with each other; recompute the scenario totals whenever a price changes.
- `tokenizer.html` — never edit its sections by hand. After changing the tokenomics page run
  `python3 sync_tokenizer.py` (`--check` reports whether it is out of date without writing). It copies everything
  between the `01 FUNDAMENTALS` and `FOOTER` markers and re-stamps the month; the page's own head, hero, footer
  and `style-tokenizer.css` stay as they are. A provider badge new to the table needs a `.provider.<name>` rule in
  both `ai-tokenomics/style.css` and `style-tokenizer.css`.
- `about/index.html` — hand-written, except the entry count between the `<!--GEO:ENTRY-COUNT-->` markers, which
  `generate_geo.py` rewrites on every run. Keep the markers.
- `model-team-evaluator.html` in the site root is only a redirect to the `/tools/` page.

When refreshing prices and scores: take list prices from each vendor's own pricing page and scores from the
benchmark publisher's page, name the index version next to any score, and say on the page which numbers could
only be cross-checked on aggregator listings.
