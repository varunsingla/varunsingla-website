#!/usr/bin/env python3
"""Keep tokenizer.html in step with the AI Tokenomics page.

tokenizer.html (linked site-wide as "Tokenizer" / "LLM Tokenizer & Cost Calculator") is an older
fork of ai-tokenomics/index.html. It keeps its own <head>, nav, hero, footer and dark theme, but
everything between the "01 FUNDAMENTALS" and "FOOTER" markers — the price table, cost scenarios,
levers and calculator — is copied from the tokenomics page, so the two URLs can never show
different prices again (the fork sat on April 2026 prices until November 2026).

Run it after every refresh of ai-tokenomics/index.html:

    python3 sync_tokenizer.py            # rewrite tokenizer.html if it is out of date
    python3 sync_tokenizer.py --check    # exit 1 if it is out of date; writes nothing

Hand edits to tokenizer.html belong outside the two markers; anything between them is overwritten.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'ai-tokenomics' / 'index.html'
TARGET = ROOT / 'tokenizer.html'

BEGIN = '  <!-- 01 FUNDAMENTALS -->'
END = '  <!-- FOOTER -->'

# In-page nav labels, in the order the sections appear on the tokenomics page.
NAV_LABELS = {
    'fundamentals': 'Fundamentals', 'pricing': 'Pricing', 'levers': 'Optimise', 'agentic': 'Agentic',
    'advanced': 'Advanced', 'hosting': 'Hosting', 'finops': 'FinOps', 'playbook': 'Playbook',
    'calculator': 'Calculator',
}


def _one(text: str, marker: str, name: str) -> int:
    if text.count(marker) != 1:
        raise SystemExit(f"sync_tokenizer: expected exactly one {marker.strip()!r} marker in {name}, found {text.count(marker)}")
    return text.index(marker)


def build(source: str, target: str) -> str:
    """Return tokenizer.html with its body sections replaced by the tokenomics page's."""
    body = source[_one(source, BEGIN, SOURCE.name):_one(source, END, SOURCE.name)]
    out = target[:_one(target, BEGIN, TARGET.name)] + body + target[_one(target, END, TARGET.name):]

    # Nav: one anchor per section that now exists on the page.
    sections = [s for s in re.findall(r'<section[^>]*\bid="([^"]+)"', body) if s in NAV_LABELS]
    links = '\n'.join(f'        <a href="#{s}">{NAV_LABELS[s]}</a>' for s in sections)
    out, n = re.subn(r'(<div class="nav-links">\n).*?(\n      </div>)', lambda m: m.group(1) + links + m.group(2), out, count=1, flags=re.S)
    if n != 1:
        raise SystemExit('sync_tokenizer: nav-links block not found in tokenizer.html')

    # Date stamp: reuse the month the tokenomics page declares in its hero badge.
    m = re.search(r'<div class="hero-badge">[^<]*·\s*([A-Z][a-z]+ \d{4}) Update</div>', source)
    if not m:
        raise SystemExit('sync_tokenizer: could not read the "<Month YYYY> Update" badge from the tokenomics page')
    month = m.group(1)
    out, n1 = re.subn(r'(<div class="hero-badge">AI FinOps · Precision Economics · )[^<]*(</div>)', rf'\g<1>{month} Data\g<2>', out, count=1)
    out, n2 = re.subn(r'(<meta name="description" content="A practical guide to AI token cost models, )[^"]*(" />)',
                      rf'\g<1>{month} pricing across major providers, and the key levers to cut your token spend by 70–85%.\g<2>', out, count=1)
    if n1 != 1 or n2 != 1:
        raise SystemExit('sync_tokenizer: hero badge or meta description not found in tokenizer.html')
    return out


def main(argv: list[str]) -> int:
    check = '--check' in argv
    source = SOURCE.read_text(encoding='utf-8')
    current = TARGET.read_text(encoding='utf-8')
    updated = build(source, current)
    if updated == current:
        print('tokenizer.html is already in step with ai-tokenomics/index.html')
        return 0
    if check:
        print('tokenizer.html is OUT OF DATE — run: python3 sync_tokenizer.py')
        return 1
    TARGET.write_text(updated, encoding='utf-8')
    print(f'tokenizer.html updated from ai-tokenomics/index.html ({len(current):,} -> {len(updated):,} chars)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
