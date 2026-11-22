#!/usr/bin/env python3
"""
check_learnings.py — regression check: no page furniture in the published text,
and no self-test inside a takeaway.

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

The PDF also prints a SELF-TEST straight after the practical takeaways. When
the parser does not end the takeaways at that heading, the last takeaway runs
on through the whole quiz, which is then published twice (the same questions
are in the entry's `quiz` field):

    ...it is faster, cheaper and easier to audit. SELF-TEST Q1. What is a
    canary token, and what did Dragos use it for? A1. A fake secret that ...

So the script also fails when a practical takeaway contains

    SELF-TEST             the heading as printed (also QUIZ, TEST YOURSELF,
                          CHECK YOUR UNDERSTANDING)
    Q1. ... A1. ...       a numbered question with its answer

or repeats, word for word, the entry's own recap paragraph or sources line
(the "Topics covered so far" block did the same thing once, in the 2026-08-22
entry; the parser now ends the takeaways at a "Sources:" line as well).

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

# The SELF-TEST block inside a practical takeaway: its heading as the PDF
# prints it (capitals — "run a self-test" in a sentence is fine), or a
# "Q1. … A1. …" pair. "Q1." alone is not enough: it also means first quarter.
QUIZ_HEADING_RE = re.compile(r'\b(?:SELF[- ]TEST|TEST YOURSELF|CHECK YOUR UNDERSTANDING|QUIZ)\b')
QA_PAIR_RE = re.compile(r'\bQ1[.):]\s.*?\bA1[.):]\s', re.S)
# The same run-on as it reaches the generated pages: in running text
# ("…easier to audit. SELF-TEST Q1. What is…") and in the Playbook's lower-cased
# filter text ("…easier to audit self test q1 what is…"). An entry page's own
# self-test section prints the questions without the heading or the "Q1." label.
RUNON_RE = re.compile(r'SELF[- ]TEST\s+Q1[.):]|\bself test q1\b')

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


def quiz_in_takeaways(entry: dict, label: str) -> list[str]:
    """Every takeaway of the entry that carries the SELF-TEST block. Looks at
    each string under practical_takeaway: the title and body of an item, or
    the single string older entries store."""
    found = []
    for path, text in walk(entry.get('practical_takeaway'), ('practical_takeaway',)):
        m = QUIZ_HEADING_RE.search(text) or QA_PAIR_RE.search(text)
        if m:
            before = text[max(0, m.start() - 40):m.start()]
            found.append(f"{label} {'/'.join(map(str, path))}: self-test text {m.group(0)[:24]!r} "
                         f"inside a takeaway, after {before!r}")
    return found


def repeated_in_takeaways(entry: dict, label: str) -> list[str]:
    """Every takeaway of the entry that repeats its recap paragraph or its
    sources line (the text stored in `recap` / `sources`): that block ran on
    into it. Unlike the self-test these have no shape of their own inside a
    sentence, so this finds a word-for-word copy and nothing less."""
    found = []
    for field, name in (('recap', 'recap paragraph'), ('sources', 'sources line')):
        block = ' '.join(str(entry.get(field) or '').split())
        if len(block) < 40:
            continue
        for path, text in walk(entry.get('practical_takeaway'), ('practical_takeaway',)):
            if block in ' '.join(text.split()):
                found.append(f"{label} {'/'.join(map(str, path))}: the {name} "
                             f"({block[:40]!r} …) is repeated inside a takeaway")
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
        problems.extend(quiz_in_takeaways(entry, entry.get('date', '?')))
        problems.extend(repeated_in_takeaways(entry, entry.get('date', '?')))
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
            runons = RUNON_RE.findall(text)
            if runons:
                problems.append(f"{rel}: self-test text inside a takeaway, {len(runons)} time(s) ({runons[0]!r} …)")
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


def check_takeaway_units(U) -> list[str]:
    """Small fixed cases: the takeaway block ends where the SELF-TEST (or the
    recap, or the sources line) begins, and a stored takeaway that already
    carries the self-test is cut back only when that text is in `quiz`."""
    problems = []

    def expect(what, got, want):
        if got != want:
            problems.append(f"{what}: got {got!r}, expected {want!r}")

    # ── Parser ────────────────────────────────────────────────────────────────
    # Lines as the Day 239 PDF gives them: the self-test follows the last
    # takeaway directly, a page header falls inside it, TOMORROW comes after.
    lines = ['PRACTICAL TAKEAWAYS',
             '1) Keep secrets out of prompts.',
             'Never paste API keys or passwords into an AI tool; use a secrets manager and',
             'short-lived tokens that agents fetch when needed.',
             '2) Prefer structured tools over screen-clicking.',
             'Where an app has a CLI or API, give agents that instead of computer-use control; it is faster, cheaper',
             'and easier to audit.',
             'SELF-TEST',
             'Q1. What is a canary token, and what did Dragos use it for?',
             'A1. A fake secret that no honest process would use, so any use proves exposure; the study ran until',
             '2026. The providers were not named.',
             'Varun Singla · Daily AI Learning for Varun · AI Learning -- Day 239 · 2026-11-22 | Page 4',
             'Q2. Why is a CLI often better for agents than screen-based computer use?',
             'A2. Commands are exact, fast and cheap in tokens; in one test the gap was a factor of',
             '10. Clicking on screens breaks when the layout changes.',
             'TOMORROW',
             "What We're Watching: Whether ANT holds above its $83 IPO price."]
    items, region = U._extract_numbered_takeaways(lines)
    expect('takeaways followed by SELF-TEST', items,
           [{'title': 'Keep secrets out of prompts.',
             'body': 'Never paste API keys or passwords into an AI tool; use a secrets manager and '
                     'short-lived tokens that agents fetch when needed.'},
            {'title': 'Prefer structured tools over screen-clicking.',
             'body': 'Where an app has a CLI or API, give agents that instead of computer-use control; '
                     'it is faster, cheaper and easier to audit.'}])
    # The self-test lines still belong to the block section building skips: one
    # of them ("2026. The providers …") would otherwise be read as a section heading.
    expect('region of takeaways followed by SELF-TEST', region, (0, 15))

    # The 2026-08-22 PDF: the recap follows the last takeaway directly.
    items, _ = U._extract_numbered_takeaways([
        'PRACTICAL TAKEAWAYS',
        "1. Weigh a vendor's AI claim by who verified it, not just what it says",
        'When a company claims an AI breakthrough, the first question worth asking is: who checked this?',
        'Topics Covered So Far',
        '146 days in, the recurring threads have been the chip race, model releases and agentic tools.',
        'Tomorrow:',
        "We'll watch whether Anthropic's IPO paperwork actually lands."])
    expect('takeaways followed by the recap', items,
           [{'title': "Weigh a vendor's AI claim by who verified it, not just what it says",
             'body': 'When a company claims an AI breakthrough, the first question worth asking is: who checked this?'}])

    items, _ = U._extract_numbered_takeaways([
        'PRACTICAL TAKEAWAYS',
        '1) Map your fourth parties.',
        'Ask each AI vendor which routers, resellers and inference providers process your prompts.',
        'Sources: dragos.com/blog/ai-supply-chain-security-canary-tokens, labs.cloudsecurityalliance.org and',
        'unit42.paloaltonetworks.com (prompt leaks, inference-provider risk).'])
    expect('takeaways followed by the sources line', items,
           [{'title': 'Map your fourth parties.',
             'body': 'Ask each AI vendor which routers, resellers and inference providers process your prompts.'}])

    # A sentence that wraps onto a line beginning with one of those words is
    # body text: nothing is cut, and the takeaways after it are still collected.
    items, _ = U._extract_numbered_takeaways([
        'PRACTICAL TAKEAWAYS',
        '1) Check primary material.',
        'Cross-check every number against primary',
        'sources: filings, vendor pages and regulator notices, and close each study session with a short',
        'quiz.',
        '2) Review weekly.',
        'Before starting a new subject, skim the',
        'topics covered so far and note what you could not explain.',
        'TOMORROW'])
    expect('wrapped sentences that begin with "sources:", "quiz." and "topics covered so far"', items,
           [{'title': 'Check primary material.',
             'body': 'Cross-check every number against primary sources: filings, vendor pages and regulator '
                     'notices, and close each study session with a short quiz.'},
            {'title': 'Review weekly.',
             'body': 'Before starting a new subject, skim the topics covered so far and note what you could not explain.'}])

    # Nor is a sentence that starts on its own line with a capital: a body's
    # first line always does. Only the heading forms end the block — "Topics
    # covered so far" followed by nothing, a bracket, a colon or a dash, and
    # "Sources:" with its colon.
    items, _ = U._extract_numbered_takeaways([
        'PRACTICAL TAKEAWAYS',
        '1) Read the licence before you build.',
        'Open weights do not always mean open terms; check commercial-use and redistribution clauses.',
        'Source-available licences are not open source; read the terms before you build on a model.',
        '2) Pin the model version.',
        'Topics covered so far tell you where the gaps are; revisit the oldest one each week.',
        '3) Keep the receipts.',
        'Source: the vendor pricing page is the reference; save a dated copy of it.',
        'TOMORROW'])
    expect('sentences that begin "Source-available", "Topics covered so far tell" and "Source:"', items,
           [{'title': 'Read the licence before you build.',
             'body': 'Open weights do not always mean open terms; check commercial-use and redistribution clauses. '
                     'Source-available licences are not open source; read the terms before you build on a model.'},
            {'title': 'Pin the model version.',
             'body': 'Topics covered so far tell you where the gaps are; revisit the oldest one each week.'},
            {'title': 'Keep the receipts.',
             'body': 'Source: the vendor pricing page is the reference; save a dated copy of it.'}])
    # Every wording of the recap heading the PDFs have used still ends the block.
    for heading in ('TOPICS COVERED SO FAR (RECAP)', 'TOPICS COVERED SO FAR', 'Topics Covered So Far',
                    'Topics covered so far', 'Topics covered so far (recent days)',
                    'Topics covered so far: 141 days in, the recurring threads have been the chip race and agents.'):
        items, _ = U._extract_numbered_takeaways([
            'PRACTICAL TAKEAWAYS',
            '1) Map your fourth parties.',
            'Ask each AI vendor which routers, resellers and inference providers process your prompts.',
            heading,
            'Recent days covered canary tokens, export licences and agent shopping with spending limits.'])
        expect(f'takeaways followed by {heading[:36]!r}', items,
               [{'title': 'Map your fourth parties.',
                 'body': 'Ask each AI vendor which routers, resellers and inference providers process your prompts.'}])

    # ── Stored entries ────────────────────────────────────────────────────────
    if not hasattr(U, 'trim_takeaways'):
        return problems + ['update_site.py has no trim_takeaways']

    def stored(last_body: str, quiz, recap=None) -> dict:
        entry = {'date': '2026-11-22',
                 'practical_takeaway': [
                     {'title': 'Keep secrets out of prompts.', 'body': 'Use a secrets manager and short-lived tokens.'},
                     {'title': 'Prefer structured tools over screen-clicking.', 'body': last_body}]}
        if quiz is not None:
            entry['quiz'] = quiz
        if recap is not None:
            entry['recap'] = recap
        return entry

    run_on = ('Give agents a CLI or API; it is faster, cheaper and easier to audit. SELF-TEST '
              'Q1. What is a canary token? A1. A fake secret; any use of it proves exposure. '
              'Q2. Why is a CLI often better for agents? A2. Commands are exact, fast and cheap in tokens.')
    quiz = [{'q': 'What is a canary token?', 'a': 'A fake secret; any use of it proves exposure.'},
            {'q': 'Why is a CLI often better for agents?', 'a': 'Commands are exact, fast and cheap in tokens.'}]

    entry = stored(run_on, [dict(q) for q in quiz])
    changes = U.trim_takeaways(entry)
    expect('trim_takeaways: the self-test that is also in quiz', entry,
           stored('Give agents a CLI or API; it is faster, cheaper and easier to audit.', quiz))
    expect('trim_takeaways reports the cut', bool(changes), True)
    expect('trim_takeaways a second time reports', list(U.trim_takeaways(entry)), [])

    # Left exactly as it is whenever a removed question or answer would not be in quiz.
    left_alone = [
        ('a question that quiz does not have', run_on, quiz[:1]),
        ('an answer that differs from quiz', run_on,
         [quiz[0], {'q': quiz[1]['q'], 'a': 'Commands are exact, slow and cheap in tokens.'}]),
        ('an entry without quiz', run_on, None),
        ('text after the last answer', run_on + ' Run the canary drill on Monday.', quiz),
        ('"self-test" and "Q1." in a sentence',
         'Run a self-test before the audit in Q1. The vendor was rated A1. Keep the logs.', quiz),
    ]
    for what, body, qz in left_alone:
        entry = stored(body, [dict(q) for q in qz] if qz is not None else None)
        unverified = []
        changes = U.trim_takeaways(entry, None, unverified)
        expect(f'trim_takeaways leaves {what}', entry, stored(body, qz))
        expect(f'trim_takeaways reports no change for {what}', list(changes), [])
        # … and says so when it is a self-test it would not cut, but not about an ordinary sentence
        expect(f'trim_takeaways notes about {what}', len(unverified), 1 if 'SELF-TEST' in body else 0)

    # The recap that ran on into the last takeaway (the 2026-08-22 entry) goes
    # the same way, when what follows its heading is exactly the stored recap.
    own = 'Ask who checked the result, and whether they had any reason to make it look good?'
    recap = '146 days in, the recurring threads have been the chip race, model releases and agentic tools.'
    entry = stored(f'{own} Topics Covered So Far {recap}', None, recap)
    changes = U.trim_takeaways(entry)
    expect('trim_takeaways: the recap that is also in recap', entry, stored(own, None, recap))
    expect('trim_takeaways reports the recap it cut', bool(changes), True)
    expect('trim_takeaways a second time reports (recap)', list(U.trim_takeaways(entry)), [])
    for what, body, rc in [
        ('a recap that reads differently from the stored one', f'{own} Topics Covered So Far {recap}',
         '146 days in, the recurring threads have been the chip race and model releases.'),
        ('a recap followed by more text', f'{own} Topics Covered So Far {recap} Start with the chip race.', recap),
        ('a recap in an entry that stores none', f'{own} Topics Covered So Far {recap}', None),
        ('a sentence that begins "Topics covered so far"',
         'Review before moving on. Topics covered so far are a map of what to revisit.', recap),
    ]:
        entry = stored(body, None, rc)
        expect(f'trim_takeaways leaves {what}', entry if not U.trim_takeaways(entry) else 'changed', stored(body, None, rc))

    # Both blocks in one body, in either order: one call cuts both, a second finds nothing.
    self_test = run_on[run_on.index('SELF-TEST'):]
    for what, body in [('a self-test followed by the recap', f'{own} {self_test} Topics Covered So Far {recap}'),
                       ('the recap followed by a self-test', f'{own} Topics Covered So Far {recap} {self_test}')]:
        entry = stored(body, [dict(q) for q in quiz], recap)
        U.trim_takeaways(entry)
        expect(f'trim_takeaways: {what}', entry, stored(own, quiz, recap))
        expect(f'trim_takeaways a second time reports ({what})', list(U.trim_takeaways(entry)), [])

    # This pass runs over every stored entry before each daily publish, so an
    # entry it cannot work with must come through untouched, not stop the run.
    odd_entries = [
        {'date': '2026-03-15'},
        {'date': '2026-03-15', 'practical_takeaway': f'One paragraph, as the oldest entries store it. {self_test}', 'quiz': quiz},
        {'date': '2026-03-15', 'practical_takeaway': ['a string', None, {'title': 'No body'}, {'title': 'T', 'body': None}]},
        {'date': '2026-03-15', 'practical_takeaway': [{'title': 'T', 'body': run_on}], 'quiz': 'not a list'},
        {'date': '2026-03-15', 'practical_takeaway': [{'title': 'T', 'body': run_on}],
         'quiz': ['not a dict', None, {'q': 'What is a canary token?'}]},
        {'date': '2026-03-15', 'practical_takeaway': [{'title': 'T', 'body': f'{own} Topics Covered So Far {recap}'}],
         'recap': ['not', 'a', 'string']},
    ]
    for entry in odd_entries:
        untouched = json.loads(json.dumps(entry))
        try:
            changes = list(U.trim_takeaways(entry, {}, []))
        except Exception as exc:                      # noqa: BLE001 - any crash here would stop the daily run
            problems.append(f"trim_takeaways raised {exc!r} on {untouched!r}")
            continue
        expect('trim_takeaways on an entry it cannot work with', (entry, changes), (untouched, []))

    # The repair pass applies it to every stored entry, and has nothing left to do the second time.
    data = {'learnings': [dict(stored(run_on, [dict(q) for q in quiz]), title='A title', schema=U.SCHEMA_VERSION)]}
    with contextlib.redirect_stdout(io.StringIO()):
        first = U.repair_all(data, ROOT, verbose=False)
        second = U.repair_all(data, ROOT, verbose=False)
    expect('repair_all: the last takeaway', data['learnings'][0]['practical_takeaway'][1]['body'],
           'Give agents a CLI or API; it is faster, cheaper and easier to audit.')
    expect('repair_all: quiz', data['learnings'][0]['quiz'], quiz)
    expect('repair_all reports the entry it changed', [date for date, _ in first], ['2026-11-22'])
    expect('repair_all a second time reports', list(second), [])
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
    problems += quiz_in_takeaways(entry, f"parse of {pdf.name}:") + repeated_in_takeaways(entry, f"parse of {pdf.name}:")
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
    print("Checking for leaked page headers/footers, mangled ampersands and self-test text in takeaways …")
    ok = report('learnings.json', check_stored())
    ok = report('generated pages', check_generated()) and ok

    sys.path.insert(0, str(ROOT))
    with contextlib.redirect_stdout(io.StringIO()):
        import update_site as U
    ok = report('parser and repair pass (fixed cases)', check_units(U)) and ok
    ok = report('where the takeaways end (fixed cases)', check_takeaway_units(U)) and ok

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
