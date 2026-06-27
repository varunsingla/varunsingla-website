# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`varunsingla.com` is a **static website** served by **GitHub Pages** from the repository root on the `main` branch. There is **no build step, no bundler, no package.json, and no test suite** — every page is hand-written HTML/CSS/JS that the browser loads directly. The custom domain is configured by `CNAME` (`varunsingla.com`); deploying is simply pushing to `main`, which GitHub Pages serves in ~1 minute.

The site is an AI learning journal: a daily-updated blog of agentic-AI breakthroughs, plus a few standalone interactive tool pages.

## Commands

There is nothing to compile. Useful commands:

```bash
# Preview the site locally (open http://localhost:8000)
python3 -m http.server 8000

# Run the daily content updater (parses the newest learning PDF → learnings.json → pushes to GitHub)
python3 update_site.py
```

`update_site.py` auto-installs its only dependency (`pdfplumber`) on first run via pip. It reads credentials from `config.json` (gitignored — copy `config.json.template` and fill in a GitHub fine-grained PAT with Contents: read/write). See `SETUP.md` for the full one-time GitHub Pages + DNS setup.

## Architecture

### The journal (homepage)

`index.html` is a **self-contained client-rendered single-page app** — all CSS and JS are inline, no framework, no external script files. At runtime it does `fetch('learnings.json')` and renders everything from that data:

- A hash-router (`#/`, `#/entry/<id>`) switches between the home/archive list and a single-article view (`route()` → `renderHome()` / `renderArticle()`).
- It injects SEO JSON-LD `BlogPosting` schema into the page from the loaded entries (`injectBlogPostingSchema`).
- A calendar archive lets readers browse entries by date.

**`learnings.json` is the single source of truth for the journal** — do not hand-edit the rendered HTML to change content; change the data (or the PDF the data is generated from). It is a large generated file (~1MB, 100+ entries). Its shape:

```jsonc
{
  "profile":  { "name", "tagline", "subtitle" },
  "learnings": [ {
    "date": "YYYY-MM-DD",        // authoritative key; entries sorted desc, deduped by date
    "display_date", "issue", "title", "focus_intro",
    "stats":   [ { "stat", "label" } ],
    "viral_app": { "name", "description", "stats" },
    "sections": [ { "title", "paragraphs"?, "bullets"?, "table"? } ],
    "market_signal", "practical_takeaway": [ { "title", "body" } ], "tomorrow_preview"
  } ],
  "last_updated", "total_days"
}
```

### The content pipeline (`update_site.py`)

This is the most complex part of the repo and the bulk of its logic. Each day a new `AI_Learning_DayNN_YYYY-MM-DD.pdf` is added; the script:

1. **Discovers** the newest unprocessed PDF by scanning the parent workspace folder for files whose names contain ≥2 of the learning keywords and whose date isn't already in `learnings.json` (`find_unprocessed_pdf`). The **filename date is authoritative** and overrides any date parsed from the PDF body (PDF bodies contain incidental dates that would corrupt the entry).
2. **Parses** the PDF with `pdfplumber` into the rich entry schema above (`parse_pdf`). This is heuristic, layout-aware extraction — it separates table regions from flowing text, reads bullets from the left column of 2-column layouts, detects stat boxes, the "Viral App of the Day", and "Practical Takeaways" via multiple fallback strategies. The `clean()` function fixes a long catalog of `pdfplumber` font-decoding artifacts (mis-decoded UTF-8 bullets, `(cid:N)` glyph IDs, OpenType ligatures used as arrows/slashes). When editing the parser, expect to add another fallback strategy or artifact rule rather than rewrite — the PDF layouts drift over time and `parse_pdf` prints validation warnings for missing fields.
3. **Merges** the entry into `learnings.json` (`merge_entry`: update-in-place by date else append, re-sort).
4. **Pushes** `learnings.json` and `sitemap.xml` straight to GitHub via the **REST Contents API** (`github_push` / `_push_file`) — it does NOT use `git`. This is why the daily updater can run headless in Cowork without a working tree.

### Standalone tool pages

These are independent, self-contained HTML pages (each with its own inline or sibling CSS/JS) linked from the journal masthead. The **canonical, current versions** live in subdirectories and match the links in `index.html`'s `masthead()`:

- `about/index.html` → `/about/`
- `ai-tokenomics/index.html` (+ `app.js`, `style.css`) → `/ai-tokenomics/` — token-cost explainer/calculator
- `tools/model-team-evaluator.html` → `/tools/model-team-evaluator.html` — frontier-model comparison

**Legacy duplicates exist in the repo root** (`tokenizer.html`, `model-team-evaluator.html`, `app-tokenizer.js`, `style-tokenizer.css`). These are older redesign-superseded versions; `tokenizer.html` is still referenced by `sitemap.xml`. Edit the subdirectory versions for current pages; treat the root copies as legacy and confirm before changing them.

## Conventions

- **Editorial "paper" design system.** Recent redesigns (see git log) share a warm-paper aesthetic: background `#F7F4ED`, ink `#1B1A17`, and the font stack Newsreader (serif body) / Hanken Grotesk (sans) / JetBrains Mono (labels & nav). Match these tokens when adding or restyling pages.
- **Styles and scripts are inline per page** (especially `index.html`). There is no shared stylesheet across pages — each page carries its own design tokens. Keep a page self-contained.
- **SEO is maintained by hand and by script:** `robots.txt`, `sitemap.xml` (its `<lastmod>` is bumped by `update_site.py`), per-page canonical tags, and JSON-LD. Update `sitemap.xml` when adding a new page.
- **Secrets:** `config.json` holds the GitHub PAT and is gitignored. Never commit it; `config.json.template` is the safe checked-in stub.
- The daily PDFs (`AI_Learning_Day*.pdf`) are committed as the raw source for each journal entry.
