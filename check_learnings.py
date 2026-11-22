#!/usr/bin/env python3
"""
check_learnings.py — regression check: no page furniture in the published text.

The daily PDF prints a running header/footer on every page. When the parser
does not recognise one, it gets joined into whatever paragraph, takeaway, quiz
answer or sources line spans the page break and is published mid-sentence:

    ...is the agent version of a corporate card AI Learning -- Day 239 |
    2026-11-22 | Page 3 with a manager sign-off.

This script fails (exit code 1) when any of these is found:

    AI Learning -- Day N | YYYY-MM-DD | Page N
    Daily AI Learning for Varun AI Learning -- Day N | YYYY-MM-DD | Page N
    Daily AI Learning for Varun
    D&O;  R&D;  S&P;      an ampersand the PDF generator turned into a broken
                          HTML entity (should read D&O, R&D, S&P)

It looks in three places:
  1. every string stored in learnings.json;
  2. the generated pages (entries/*.html and the other derived files);
  3. a fresh parse of the newest PDF, which must also be free of every line
     the PDF itself prints in its page margins, whatever that line says.

Run:
    python3 check_learnings.py              the three checks above (a few seconds)
    python3 check_learnings.py --all-pdfs   re-parse every PDF on disk (about two minutes)
    python3 check_learnings.py A.pdf B.pdf  re-parse these PDFs as well

The shapes are written out here on purpose rather than imported from
update_site.py: the check states what must never be published, independently
of how the parser and the repair pass go about removing it.
"""

import contextlib
import html.entities
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

# The three footer shapes. The second is the first two back to back (the footer
# of one page followed by the header of the next), so two patterns cover all three.
FOOTER_RE = re.compile(
    r'AI Learning -- Day \d+ \| \d{4}-\d{2}-\d{2} \| Page \d+'
    r'|Daily AI Learning for Varun')

# "D&O;" — a letter or digit, an ampersand, a name and a semicolon. This is
# what ReportLab prints for a bare "&" ("D&O insurance" -> "D&O; insurance",
# "Q&A." -> "Q&A.;", "R&D-heavy" -> "R&D-heavy;"). Real HTML entities (&amp;
# &gt; &Pi; …) are not this artefact. In the generated HTML/XML the same
# artefact arrives escaped, as "D&amp;O;".
_AMP_RE = re.compile(r'(?<=[A-Za-z0-9])&([A-Za-z][-.A-Za-z0-9]{0,23});')
_AMP_ESCAPED_RE = re.compile(r'(?<=[A-Za-z0-9])&amp;([A-Za-z][-.A-Za-z0-9]{0,23});')

GENERATED = ['entries/*.html', 'weekly/*.html', 'index.html', 'playbook/index.html',
             'concepts/index.html', 'watching/index.html', 'start/index.html',
             'review/index.html', 'index.json', 'search.json', 'feed.xml',
             'llms.txt', 'llms-full.txt']


def mangled_amps(text: str, escaped: bool = False) -> list[str]:
    return [m.group(0) for m in (_AMP_ESCAPED_RE if escaped else _AMP_RE).finditer(text)
            if m.group(1) + ';' not in html.entities.html5]


def walk(obj, path=()):
    """Yield (path, string) for every string inside a JSON value."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from walk(value, path + (key,))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from walk(value, path + (i,))


def offences(obj, label: str) -> list[str]:
    """Human-readable list of every footer / mangled ampersand inside obj."""
    found = []
    for path, text in walk(obj):
        where = f"{label} {'/'.join(map(str, path))}".strip()
        for m in FOOTER_RE.finditer(text):
            before = text[max(0, m.start() - 30):m.start()]
            found.append(f"{where}: footer {m.group(0)!r} after {before!r}")
        for amp in mangled_amps(text):
            found.append(f"{where}: mangled ampersand {amp!r}")
    return found


def report(name: str, problems: list[str]) -> bool:
    if not problems:
        print(f"  ok    {name}")
        return True
    print(f"  FAIL  {name}: {len(problems)} problem(s)")
    for p in problems[:12]:
        print(f"          {p}")
    if len(problems) > 12:
        print(f"          … and {len(problems) - 12} more")
    return False


# ── 1. Stored entries ─────────────────────────────────────────────────────────

def check_stored() -> list[str]:
    data = json.loads((ROOT / 'learnings.json').read_text(encoding='utf-8'))
    problems = []
    for entry in data.get('learnings', []):
        problems.extend(offences(entry, entry.get('date', '?')))
    return problems


# ── 2. Generated pages ────────────────────────────────────────────────────────

def check_generated() -> list[str]:
    problems = []
    for pattern in GENERATED:
        for path in sorted(ROOT.glob(pattern)):
            text = path.read_text(encoding='utf-8', errors='replace')
            rel = path.relative_to(ROOT)
            n = len(FOOTER_RE.findall(text))
            if n:
                problems.append(f"{rel}: {n} footer string(s), e.g. {FOOTER_RE.search(text).group(0)!r}")
            amps = mangled_amps(text, escaped=path.suffix not in ('.txt', '.json'))
            if amps:
                problems.append(f"{rel}: {len(amps)} mangled ampersand(s), e.g. {amps[0]!r}")
    return problems


# ── 3. Parser and repair pass ─────────────────────────────────────────────────

def check_units(U) -> list[str]:
    """Small fixed cases: what is page furniture, what is not, and how a
    sentence that spans a page break is put back together."""
    problems = []
    needed = ('is_running_line', 'scrub_text', 'scrub_entry', 'clean')
    missing = [n for n in needed if not hasattr(U, n)]
    if missing:
        return [f"update_site.py has no {', '.join(missing)}"]

    def expect(what, got, want):
        if got != want:
            problems.append(f"{what}: got {got!r}, expected {want!r}")

    for line in ('AI Learning -- Day 239 | 2026-11-22 | Page 3',
                 'AI Learning -- Day 202 | 2026-10-16 | Page 12',
                 'Daily AI Learning for Varun'):
        expect(f"is_running_line({line!r})", bool(U.is_running_line(line)), True)
    for line in ('AI Learning -- Day 200',                              # an old page-1 title, not a footer
                 'Daily AI Learning for Varun keeps a running recap.',   # a sentence, not the footer line
                 'Day 239 covered export licences and agent shopping on page 3 of the filing.',
                 # older wordings stay with the older patterns, which also use them as end-of-block markers
                 'Varun Singla · Daily AI Learning · Day 150 · varunsingla.com Page 3',
                 'Varun Singla - Daily AI Learning - Day 200 - Page 2',
                 'Generated by Varun Singla · varunsingla.com · Day 135 · August 10, 2026'):
        expect(f"is_running_line({line!r})", bool(U.is_running_line(line)), False)
    for line in ('Varun Singla · Daily AI Learning · Day 150 · varunsingla.com Page 3',
                 'Varun Singla - Daily AI Learning - Day 200 - Page 2',
                 'Varun Singla · Daily AI Learning for Varun · AI Learning -- Day 239 · 2026-11-22 | Page 2'):
        expect(f"_PAGE_HEADER_RE still matches {line!r}", bool(U._PAGE_HEADER_RE.match(line)), True)

    cases = [
        # mid-sentence: the two halves join into one sentence
        ('is the agent version of a corporate card AI Learning -- Day 239 | 2026-11-22 | Page 3 with a manager sign-off.',
         'is the agent version of a corporate card with a manager sign-off.'),
        # footer of one page + header of the next
        ('governance, succession and financing Daily AI Learning for Varun AI Learning -- Day 230 | 2026-11-13 | Page 3 '
         'structures now move AI valuations.',
         'governance, succession and financing structures now move AI valuations.'),
        ('AI Learning -- Day 232 | 2026-11-15 | Page 3 Money is flowing to the control layer.',
         'Money is flowing to the control layer.'),
        ('Figures are secondary reports and unverified. Daily AI Learning for Varun',
         'Figures are secondary reports and unverified.'),
        ('AI Learning -- Day 236 | 2026-11-19 | Page 3', ''),
        ("What does 'Side C' D&O; insurance cover? (D&O;) S&P; Capital IQ, W&B; Weave, all R&D; to",
         "What does 'Side C' D&O insurance cover? (D&O) S&P Capital IQ, W&B Weave, all R&D to"),
        # the other forms ReportLab produces: sentence-final, hyphenated, possessive, a query string
        ("ends with Q&A.; Next: R&D-heavy; firms, AT&T;'s network, S&P500; and x.com/?a=1&b;=2",
         "ends with Q&A. Next: R&D-heavy firms, AT&T's network, S&P500 and x.com/?a=1&b=2"),
        # untouched: plain ampersands, real entities, a spaced "&", an old title
        ('AT&T, P&L and FP&A stay; x &gt;threshold; AT&amp;T; 2&Pi;r; R &D; AI Learning -- Day 200',
         'AT&T, P&L and FP&A stay; x &gt;threshold; AT&amp;T; 2&Pi;r; R &D; AI Learning -- Day 200'),
    ]
    for before, after in cases:
        expect(f"scrub_text({before[:50]!r}…)", U.scrub_text(before)[0], after)
    expect("clean('D&O; insurance')", U.clean('D&O; insurance'), 'D&O insurance')

    entry = {'date': '2026-11-19', 'title_original': 'AI Learning -- Day 200',
             'sections': [{'title': '2) X', 'paragraphs': ['One. AI Learning -- Day 236 | 2026-11-19 | Page 2 Two.',
                                                          'AI Learning -- Day 236 | 2026-11-19 | Page 3', 'Three.']}],
             'quiz': [{'q': 'Why? AI Learning -- Day 236 | 2026-11-19 | Page 4', 'a': 'D&O; cover.'}]}
    U.scrub_entry(entry)
    expect('scrub_entry', entry,
           {'date': '2026-11-19', 'title_original': 'AI Learning -- Day 200',
            'sections': [{'title': '2) X', 'paragraphs': ['One. Two.', 'Three.']}],
            'quiz': [{'q': 'Why?', 'a': 'D&O cover.'}]})
    again = U.scrub_entry(entry)
    expect('scrub_entry a second time reports', list(again), [])
    return problems


def check_pdf(U, pdf: Path) -> list[str]:
    """A fresh parse of one PDF: none of the known shapes, and none of the
    lines the parser itself classifies as running header/footer."""
    with contextlib.redirect_stdout(io.StringIO()):
        entry = U.parse_pdf(pdf)
        flat = U._flat_lines_for_repair(pdf)
        repair = {'sources': U.extract_sources(flat), 'tomorrow_preview': U.extract_tomorrow_block(flat),
                  'recap': U.extract_recap(flat), 'quiz': U.extract_quiz(flat)}
    problems = offences(entry, f"parse of {pdf.name}:") + offences(repair, f"repair extractors on {pdf.name}:")
    if not hasattr(U, 'running_lines'):
        return problems + ['update_site.py has no running_lines']
    for line in sorted(set(U.running_lines(pdf))):
        hits = [f"{'/'.join(map(str, path))}" for path, text in walk({'parse': entry, 'repair': repair}) if line in text]
        if hits:
            problems.append(f"{pdf.name}: margin line {line!r} is in {', '.join(hits[:4])}")
    if not entry.get('title'):
        problems.append(f"{pdf.name}: the parse came back empty")
    return problems


def main() -> int:
    args = sys.argv[1:]
    print("Checking for leaked page headers/footers and mangled ampersands …")
    ok = report('learnings.json', check_stored())
    ok = report('generated pages', check_generated()) and ok

    sys.path.insert(0, str(ROOT))
    with contextlib.redirect_stdout(io.StringIO()):
        import update_site as U
    ok = report('parser and repair pass (fixed cases)', check_units(U)) and ok

    pdfs = sorted(U.pdf_lookup(ROOT).items())
    if '--all-pdfs' in args:
        chosen = [p for _, p in pdfs]
    else:
        chosen = [Path(a).resolve() for a in args if not a.startswith('--')]
        if pdfs and pdfs[-1][1].resolve() not in chosen:
            chosen.append(pdfs[-1][1])
    problems = []
    for pdf in chosen:
        problems.extend(check_pdf(U, pdf))
    ok = report(f"fresh parse of {len(chosen)} PDF(s)" + (f" ({chosen[0].name})" if len(chosen) == 1 else ''), problems) and ok

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
