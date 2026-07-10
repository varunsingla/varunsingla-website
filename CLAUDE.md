# CLAUDE.md

## Daily AI Learning automation

This repo is updated by a daily autonomous "Daily AI Learning" routine that:
1. Researches the day's AI news and generates `AI_Learning_Day<NNN>_<YYYY-MM-DD>.pdf` in the repo root, following
   the established layout (title/subtitle, numbered `N)` sections, VIRAL/OPEN-SOURCE SPOTLIGHT bar, MARKET SIGNAL
   bar, numbered PRACTICAL TAKEAWAYS, TOMORROW preview, footer).
2. Commits and pushes that PDF.
3. A separate publish routine (`update_site.py`) picks up the new PDF and generates/updates `learnings.json`,
   `entries/*.html`, `sitemap.xml`, `feed.xml`, `llms.txt`, `llms-full.txt`, `index.html`.

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
