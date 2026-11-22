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
- **`VIRAL / OPEN-SOURCE SPOTLIGHT`** on a line of its own, then the title on its own line(s) in bold, then the
  text in body type. The parser goes by the type: the bold line(s) under the header are the spotlight's name,
  everything in body type after them is its description -- across a page break, past the footer -- and the next
  bold line (`MARKET SIGNAL`, a numbered section, a stat strip) ends the box. So: no bold line inside the text
  (bold lead-ins such as "Why it is taking off:" within a line are fine), nothing in small or large type, and do
  not put the title on the header line (`VIRAL / OPEN-SOURCE SPOTLIGHT: FlickReels`) or the box in a bordered
  table -- the parser reads neither, and that day gets no spotlight.
- **`PRACTICAL TAKEAWAYS`** as numbered items with a short bold-style title line followed by a one-sentence body.
  Each becomes a Playbook item and a flashcard.
- **`TOMORROW`** heading followed by "What We're Watching: …" sentences. Feeds the Watching tracker.
- **`SELF-TEST`** (optional, recommended): three to five pairs in the form `Q1. question` / `A1. answer`. These
  become self-test cards on the entry page and in Review. Keep the heading alone on its line and starting
  with a capital: when the self-test comes straight after the takeaways, that line is where the parser ends
  the last takeaway. (`TOPICS COVERED SO FAR` and `Sources:` end the takeaways too, in their heading forms
  only: the recap heading with nothing after it but a bracket, a colon or a dash, and `Sources` with its
  colon. A new kind of block placed after the takeaways needs its heading added to `_starts_end_matter` in
  `update_site.py` first, or it is read as part of the last takeaway.)
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
  (idempotent, no-op once current), removes page furniture, a self-test that ran on into a takeaway and the
  second copy of a market signal or watch list from the stored text (see below), parses the newest unprocessed
  PDF, takes the same page furniture and second copies out of the fresh entry, merges it (richer entry wins,
  nothing is overwritten with less), regenerates everything, pushes via the GitHub API.
- `python3 update_site.py --repair [--dry-run] [--force]` — only the repair + regenerate pass, no push.
  `--dry-run` prints what would change, one line per change, and writes nothing. `--force` re-runs every repair step
  on entries that are already at the current schema (about a minute and a half: it opens every PDF). Every step
  is idempotent, so on repaired data `--repair --dry-run --force` reports 0 entries; if it ever reports more, a
  repair step is changing its own output, which is a bug -- `check_learnings.py` fails on it. A step that reads
  from the PDF has to compare what it read as it would be stored (after `scrub_text` / `scrub_entry`); otherwise
  it puts back a footer that the scrub pass removes again, and reports the same change on every forced run.
- `python3 update_site.py --parse <pdf>` — print what the parser extracts from one PDF (debugging).
- `python3 generate_geo.py` — regenerate the static site from `learnings.json` without touching the data.
- `python3 check_seo.py` — checks what search engines are told about every page (titles, descriptions,
  canonical links, structured data, sitemap, internal links). Run it after `generate_geo.py`; see
  "Search metadata (SEO)" below.
- `python3 check_learnings.py` — regression check, a few seconds. Exits 1 if
  - page furniture (the current header/footer or a wording of the older layouts), a mangled ampersand (`D&O;`)
    or a `&gt;` / `&lt;` printed as text is found in `learnings.json`, in the generated pages, or in a fresh
    parse of the newest PDF;
  - a takeaway, stored or freshly parsed, carries self-test text (the `SELF-TEST` heading in capitals, or a
    `Q1.` … `A1.` pair) or repeats its entry's `recap` or `sources` word for word, or `SELF-TEST Q1.` turns up
    in a generated page;
  - a spotlight description stops mid-sentence, in `learnings.json` (three known exceptions are listed in the
    script, with the reason for each) or in a fresh parse;
  - a section (heading, paragraph or bullet), a takeaway or the spotlight description repeats the entry's
    `market_signal` or `tomorrow_preview`, in `learnings.json` or in a fresh parse as it would be stored: one
    text holds the other, runs on into its beginning or continues from its end, word for word over 40 characters
    or more. The script states the test in full (`block_repeat`). A phrase the author uses twice in the middle
    of two sentences is not a repeat, and neither is one short sentence of the box repeated as a bullet;
  - a forced repair would change stored data: `normalize_viral` over every stored spotlight, and the whole
    repair (the three text-only passes below included) over the five newest entries.

  `--all-pdfs` re-parses every PDF on disk and runs the forced repair over every entry (about four minutes).
  Run it after a publish or a repair.

Repairs never delete entry text: a replaced title, intro or spotlight is kept under `title_original` /
`focus_intro_original` / `viral_app_original`, and headings are only re-cased.
There are three exceptions. All three are text-only passes that read nothing but the stored entry, so they run
over every entry on every run, whatever the schema version (they need no `SCHEMA_VERSION` bump; that is for
repair steps that open the entry's PDF). They run in this order: the scrub first, because the other two compare
one stored text with another and both must have lost their page footers by then.

**Exception 1: page furniture, which was never entry content** (`scrub_entry`). It is removed outright with no
`*_original` copy, because a copy would keep the artefact in `learnings.json`:

- the PDF's running header/footer where it got joined into the text (`AI Learning -- Day N | YYYY-MM-DD | Page N`,
  `Daily AI Learning for Varun`);
- the footers, sign-off lines and page-1 mastheads of the layouts before 2026-10-16, found in March–August
  entries: `Varun Singla · Daily AI Learning Page N`, `Generated by Varun Singla · varunsingla.com · Day N · <date>`,
  `Varun's Daily AI Brief Day N · <date> · Issue #N`, `Generated for <e-mail address> · Issue #N · varunsingla.com`
  and about twenty more. The list is `_OLD_FURNITURE` in `update_site.py`, one exact pattern per wording;
- the stray `;` of a mangled ampersand (`D&O;` → `D&O`) and the entity around a `<` or `>` that was printed as
  text (`&gt;threshold` → `>threshold`).

Exactly those strings go and the words on either side are joined. A paragraph or bullet that was nothing but a
footer is dropped, and so is a takeaway whose body was nothing but a footer when its title is only the cut-off
start of that body; a takeaway with a title of its own keeps the title, and a table cell keeps its place. The
pass walks `*_original` fields too; the patterns are written so that an old page-1 title kept there
(`AI Daily Learning -- Day 98`) does not match.

Left alone on purpose, because removing them is a decision about content rather than furniture: the page-1
dateline inside ten July/August intros (`Day 122 · July 28, 2026 · 6 min read · AI Safety & Governance / Enterprise
AI`), whose category names are the only theme label those entries have, and a `Topics: …` list that stands without
its footer (2026-04-28). A sentence that mentions the author, the site or the series is never furniture.

To add a wording: an exact, case-sensitive pattern in `_OLD_FURNITURE`, a fixed case in `check_units`, and — if the
loose shapes in `check_learnings.py` (`OLD_FURNITURE_RE`) do not already cover it — a shape there. The parser for
the older layouts (`_PAGE_HEADER_RE`, `_FOOTER_RE`) is unchanged, so a fresh parse of a pre-October PDF still
carries a footer in a few fields; `scrub_entry` runs before anything is stored.

**Exception 2: a self-test that ran on into the last takeaway** (`trim_takeaways`). Until 2026-11-22 the parser
did not end the takeaways at the `SELF-TEST` heading, so the entries from 2026-10-15 on stored the whole quiz
twice: in `quiz`, and as `… SELF-TEST Q1. … A1. …` at the end of the last takeaway's body. That copy is cut out,
again with no `*_original`, and only where nothing is lost: everything after the heading has to be, question by
question and answer by answer, the text stored in the same entry's `quiz` (the `Q1.` / `A1.` labels aside). If
anything else follows the heading, the takeaway is left exactly as it is, `--repair` prints a warning for it,
and `check_learnings.py` fails until someone has looked at it.

The recap did the same once (2026-08-22, `… Topics Covered So Far 146 days in, …`) and is cut under the same
condition: what follows the heading has to be exactly that entry's `recap`. There is no warning for a recap that
reads differently — it is simply left alone, and the check only catches a word-for-word copy. Note what this
means on the site: the quiz is still shown (as cards), but an entry page never shows its recap; only Start Here
shows the newest one. The 2026-08-22 recap is therefore in `learnings.json` only, like every other day's.

**Exception 3: a market signal or watch list that is stored twice** (`dedupe_blocks`). The MARKET SIGNAL box and
the TOMORROW line have fields of their own (`market_signal`, `tomorrow_preview`). The parsers of the layouts
before 2026-07-08 also left the text where they came across it, so 37 entries from 2026-03-23 to 2026-07-07
stored it twice and their page printed it twice:

- as a section headed `MARKET SIGNAL` (2026-04-21, 05-13, 05-17 … 05-23, 07-04, 07-07): in most of them the
  paragraph is the whole box and the field its first three sentences, which is all the old parser kept;
- under a heading that is the box's own first line, `Market signal: For an agency, the relevance is … Insist`,
  with the rest as that section's paragraph (2026-05-11, eleven entries from 06-02 to 06-13, 07-06);
- as a paragraph, bullet or "takeaway" of whatever stood next to the box (2026-03-23, 04-03, 04-13, 04-19,
  04-24, 04-26, 04-27, 04-28, 05-01, 07-04);
- at the end of a takeaway, a bullet, a paragraph or the spotlight that ran on into it, `… not per framework.
  Tomorrow: Day 49 -- Agent Reliability Engineering: …` (2026-05-01, 05-10, 05-16, 07-02).

The pass brings each back to one copy, the field, with no `*_original`, on the condition of exception 2: only
text that is still stored in the same entry goes. Two texts are one text when they meet edge to edge, word for
word (a parser copies whole lines):

- a text that is, from its first character to its last, a part of the field -- its beginning (40 characters or
  more), a later part (100 or more), or any part behind the box's own heading (`Market Signal: The AI
  healthcare …`) -- is removed;
- a text that begins with the whole field and goes on, or begins with the end of a field that was cut off (40
  characters or more, and at least half of the field) and goes on, is the fuller reading of the box: the field
  takes what it lacks, then the text is removed. Nothing is taken past the heading of the next box (`… to
  commoditise. Tomorrow -- Day 40: …`, 2026-05-01); what follows that heading stays where it is;
- a text that ends with the field, or with its first 40 characters or more, ran on into the box: it is cut back
  to its own words, and the box's heading in front of the copy (`Tomorrow:`) goes with it;
- a field that ends with the heading of a section and the beginning of that section's first paragraph ran on
  itself (six June entries: `… in the loop. 8 · Viral AI app of the day OpenClaw -- …`) and is cut back.

Two readings that differ by a word are matched by their words, the way the spotlight repair does it (the July
entries were written apart from their PDF: `Buildots imagery corpus` / `Buildots' imagery corpus`): they begin
with the same 60 characters and one has every word of the other, in order. That one stays as the field
(2026-07-04). A text that ends with every word of the field in other punctuation (2026-07-02) is a run-on like
any other.

In two entries the field is the copy that goes, because the other copy is where the text belongs:
`tomorrow_preview` of 2026-05-07 was no watch list but the first 300 characters of the takeaways, heading
included (`PRACTICAL TAKEAWAYS Add trajectory evals …`); and `market_signal` of 2026-05-13, whose only section
is headed `Market signal` and is the whole article (no heading after the box was recognised) -- moving its
first paragraph into the field would have taken the article apart, so that section stays as it is.

What the pass leaves behind it:

- A section with nothing left but the box's heading is dropped (18 of them). One that holds anything else stays
  under its heading (cut back to `Market signal` where the heading carried the first line), which says no more
  about what is under it than it did before: 2026-05-11 and 06-07 (other parts of the page that the old parser
  put there), 05-18 (the spotlight and the watch list), 05-22 (a table), 07-07 (the BREAKING THIS WEEK paragraph).
- A takeaway that was nothing but the copy goes when its title is only the cut-off beginning of the same line,
  as in `scrub_entry` (2026-04-27, 05-16; the 2026-05-16 entry has no takeaways left).
- A spotlight description that breaks off once the copy is gone is trimmed to its last full sentence by the
  rule that trims every other cut-off description, so that a forced repair has nothing left to do. The
  spotlight as it was (less the copy) is kept under `viral_app_original`, unless an earlier repair already put
  one there: the only case so far, 2026-05-01, kept the original it had from the spotlight repair.
- The only words that are no longer stored anywhere in their entry are the box headings that stood in front of
  a copy (`MARKET SIGNAL`, `Market signal:`, `Tomorrow:`, `Tomorrow's Preview`): 29 of them.

Left alone on purpose:

- Every `*_original` field. `viral_app_original.description` of 2026-04-20 and 2026-05-01 still ends with the
  first 108 / 121 characters of the market signal: that field is the record of what the spotlight repair
  replaced, and no page prints it. These two are all that a scan of every string (the first 80 characters of
  `market_signal`, `tomorrow_preview`, `recap` or `sources` found in another field of the same entry) still
  reports; before the repair it reported 29 (28 when only fields of 80 characters or more are looked at).
- The same watch list in two wordings, where neither has every word of the other, so that removing either copy
  would lose words: 2026-05-16 (the end of the spotlight section's paragraph, cut off), 2026-07-06 (takeaway 1)
  and 2026-07-07 (the end of the first section's paragraph). The check does not object to these.
- 2026-03-30: a bullet that ends, after a sentence of its own, with the later lines of the watch list (187
  characters). The copy starts at an edge of neither text, so no rule places it; the check does not object.
- A phrase the author uses twice (in the middle of the market signal and in the middle of a takeaway:
  2026-06-17, 06-26), one short sentence of the box repeated as a bullet, and the intro.
- A watch list that is filed as a takeaway (`Tomorrow (Day 46): …`; eighteen entries from 2026-04-12 to
  2026-07-06, sixteen of them without a `tomorrow_preview`). Nothing is stored twice there, so this pass does
  not touch it; moving that text to `tomorrow_preview` is a different repair, and has not been done.

A copy the rules cannot place -- the whole field in the middle of a paragraph with other text on both sides, or
a field that ends with the opening of a section without that section's heading in between -- is left as it is,
`--repair` prints a warning for it, and `check_learnings.py` fails until someone has looked at it. `parse_pdf`
has dropped sections headed "market signal" for some time; the pass also runs over a fresh entry before it is
merged, because a fresh parse of the 2026-07-03 layout still runs `Tomorrow's Preview: …` into the last takeaway.

The spotlight (`viral_app`), in the parser and in the repair:

- `name` + `sep` + `description` is the text of the box, exactly. `sep` is what stood between the two when it
  was more than a space (`". "`, `", "`, `": "`, `" -- "` -- boxes with no title line, "Today's pick: X. Text")
  and is left out otherwise. Pages print `name` and `description`; `sep` is there so that tidying a name never
  drops a character. `normalize_viral` does that tidying and may be applied any number of times.
- A name that ran into its description is cut once, when the PDF is parsed, and only for a box without a bold
  title line. A stored name is never cut again -- that is what used to move on every forced repair.
- Where the PDF is on disk, the repair (`repair_spotlight`) holds the stored spotlight against the box in the
  PDF: if the box contains everything stored, the box is taken (a cut-off description is completed, the title
  and the dropped comma/colon/full stop come back); if the stored text is cut off and runs past the end of the
  box into the next section, the box is taken and the stored spotlight goes to `viral_app_original`; anything
  else is left alone. With no box to complete it from, a description that breaks off is trimmed to its last full
  sentence and the spotlight as it was goes to `viral_app_original`.

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
- `tokenizer.html` is only a redirect to `/ai-tokenomics/` (the two pages were duplicates; Tokenomics is the one kept).
- `about/index.html` — hand-written, except the entry count between the `<!--GEO:ENTRY-COUNT-->` markers, which
  `generate_geo.py` rewrites on every run. Keep the markers.
- All of these (and the home page) also carry a `<!-- GEO:SCHEMA:BEGIN -->` … `<!-- GEO:SCHEMA:END -->` block in
  the `<head>`: their structured data, rewritten by `generate_geo.py` from the page's own `<title>`, meta
  description and `<meta name="last-modified" content="YYYY-MM-DD">`. **Bump that `last-modified` date whenever
  you change one of these pages** — the sitemap and the structured data both take the page's date from it.
- `model-team-evaluator.html` in the site root is only a redirect to the `/tools/` page.

When refreshing prices and scores: take list prices from each vendor's own pricing page and scores from the
benchmark publisher's page, name the index version next to any score, and say on the page which numbers could
only be cross-checked on aggregator listings.

## Search metadata (SEO)

Everything search engines and link previews read is produced in one place, `generate_geo.py`, and verified by
`python3 check_seo.py` (exit code 1 on a problem; `--verbose` lists warnings). Run the check after any change to
the generator or to a hand-written page; the daily routine can run it after `update_site.py` too.

- **Identity.** The block at the top of `generate_geo.py` (`SITE_NAME`, `JOB_TITLE`, `PERSON_BIO`, `KNOWS_ABOUT`,
  `SAME_AS`) is the single description of the author and the site. Every page's structured data is built from it,
  so change it there, never in a page. `SAME_AS` holds the author's public profile URLs (LinkedIn, GitHub, X …);
  it is empty until Varun says which profiles to claim — do not add one on your own.
- **Site name vs journal name.** The site is "Varun Singla" (`SITE_NAME`: what Google shows as the site name);
  the journal is "Varun Singla · AI Learning Journal" (`BLOG_NAME`). Page titles end in `| Varun Singla`.
- **Entry pages.** Title = the day's headline + `| Varun Singla`; the description is built by
  `meta_description()` (deck, then the opening of the entry, about 155 characters). Entries under `THIN_WORDS`
  words are published but `noindex` and left out of the sitemap; an entry whose text repeats an earlier one
  points its canonical link at the earlier page. Both rules lift on their own once the data is repaired.
- **Topics.** Each of the six themes has a page under `/topics/<slug>/` (`THEME_INFO`). The theme tags on entry
  pages link there. Adding a theme means adding it to `THEMES`, `RULES` and `THEME_INFO`.
- **Icons.** `favicon.ico`, `favicon.svg`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png` and
  `site.webmanifest` are real files in the site root (search engines will not show a `data:` favicon).
- **robots.txt** keeps crawlers off the PDFs and the raw data files, which only repeat the pages. Never block
  `/index.json` — the home page renders from it, and Google renders the page the same way.
- **404.html** is generated, and is what GitHub Pages serves for any address that does not exist.
