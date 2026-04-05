/* ─── THEME TOGGLE ─── */
(function () {
  const html = document.documentElement;
  // Use localStorage so preference persists across pages on varunsingla.com
  let stored = null;
  try { stored = localStorage.getItem('vs-theme'); } catch(e) {}
  let theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  html.setAttribute('data-theme', theme);

  const MOON = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
  const SUN  = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>`;

  function updateBtn(btn, t) {
    if (!btn) return;
    btn.setAttribute('aria-label', t === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
    btn.innerHTML = t === 'dark' ? SUN : MOON;
    btn.title = t === 'dark' ? 'Light mode' : 'Dark mode';
  }

  document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
    updateBtn(btn, theme);
    btn.addEventListener('click', () => {
      theme = theme === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-theme', theme);
      try { localStorage.setItem('vs-theme', theme); } catch(e) {}
      document.querySelectorAll('[data-theme-toggle]').forEach(b => updateBtn(b, theme));
    });
  });
})();

/* ─── NAV SCROLL ─── */
const nav = document.getElementById('nav');
window.addEventListener('scroll', () => {
  nav.classList.toggle('scrolled', window.scrollY > 40);
}, { passive: true });

/* ─── TOKENISER (approximate) ─── */
function approximateTokens(text) {
  if (!text) return [];
  // Split on rough token boundaries — spaces, punctuation boundaries, subword units
  const raw = text.split(/(\s+|[^\w\s]|(?<=[a-z])(?=[A-Z])|(?<=[a-z]{3})(?=[aeiou]{1}[^aeiou]))/g)
    .filter(t => t && t.trim().length > 0);

  // Approximate: every ~4 chars = 1 token, but preserve word groupings visually
  const tokens = [];
  let buffer = '';
  for (const word of raw) {
    buffer += word;
    if (buffer.replace(/\s/g, '').length >= 3) {
      tokens.push(buffer.trimStart());
      buffer = '';
    }
  }
  if (buffer.trim()) tokens.push(buffer.trim());
  return tokens;
}

const tokenInput = document.getElementById('tokenInput');
const tokenOutput = document.getElementById('tokenOutput');
const tokenCount = document.getElementById('tokenCount');
const charCount = document.getElementById('charCount');
const tokenRatio = document.getElementById('tokenRatio');

function updateTokenDemo() {
  const text = tokenInput?.value || '';
  const toks = approximateTokens(text);
  if (tokenOutput) {
    tokenOutput.innerHTML = toks.map(t =>
      `<span class="token-chip">${t.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</span>`
    ).join('');
  }
  if (tokenCount) tokenCount.textContent = toks.length;
  if (charCount) charCount.textContent = text.length;
  if (tokenRatio) tokenRatio.textContent = toks.length > 0 ? (text.length / toks.length).toFixed(1) : '0';
}

if (tokenInput) {
  tokenInput.addEventListener('input', updateTokenDemo);
  updateTokenDemo(); // initial
}

/* ─── PRICING TABLE FILTER ─── */
const filterBtns = document.querySelectorAll('.filter-btn');
const tableRows = document.querySelectorAll('#pricingTable tbody tr');

filterBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    filterBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const filter = btn.dataset.filter;
    tableRows.forEach(row => {
      row.classList.toggle('hidden', filter !== 'all' && row.dataset.tier !== filter);
    });
  });
});

/* ─── CALCULATOR ─── */
function fmt(n) {
  if (n >= 1000000) return '$' + (n / 1000000).toFixed(2) + 'M';
  if (n >= 1000) return '$' + (n / 1000).toFixed(1) + 'K';
  return '$' + n.toFixed(2);
}

function fmtTokens(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K';
  return n.toLocaleString();
}

function calcCost() {
  const modelEl = document.getElementById('calcModel');
  const opt = modelEl?.options[modelEl.selectedIndex];
  const inRate = parseFloat(opt?.dataset.in || 1.25);   // $ per MTok
  const outRate = parseFloat(opt?.dataset.out || 10.00); // $ per MTok

  const calls = parseFloat(document.getElementById('calcCalls')?.value || 1000);
  const inTok = parseFloat(document.getElementById('calcInputTokens')?.value || 2000);
  const outTok = parseFloat(document.getElementById('calcOutputTokens')?.value || 500);

  const dailyIn = calls * inTok;
  const dailyOut = calls * outTok;
  const monthlyIn = dailyIn * 30;
  const monthlyOut = dailyOut * 30;

  const baseInputCost = (monthlyIn / 1e6) * inRate;
  const baseOutputCost = (monthlyOut / 1e6) * outRate;
  const baseCost = baseInputCost + baseOutputCost;

  // Apply optimisations
  let optInRate = inRate, optOutRate = outRate;
  let optInMult = 1.0, optOutMult = 1.0, callsMult = 1.0, totalMult = 1.0;
  let appliedFactors = [];

  const cache = document.getElementById('optCache')?.checked;
  const semantic = document.getElementById('optSemantic')?.checked;
  const modelRoute = document.getElementById('optModelSwitch')?.checked;
  const truncate = document.getElementById('optTruncate')?.checked;
  const prompt = document.getElementById('optPrompt')?.checked;
  const output = document.getElementById('optOutput')?.checked;
  const batch = document.getElementById('optBatch')?.checked;

  if (cache) {
    // 90% off input for ~80% of calls (system prompt typically 40-60% of input)
    optInMult *= (1 - 0.70); // ~70% effective input reduction
    appliedFactors.push('Prompt caching: −70% input');
  }

  if (semantic) {
    // 60% of calls return cached response — eliminating both input and output
    callsMult *= (1 - 0.60);
    appliedFactors.push('Semantic caching: 60% call elimination');
  }

  if (modelRoute) {
    // 70% of calls routed to a model that's ~60% cheaper
    const cheapFactor = 0.70 * 0.40; // 70% of traffic * 60% saving = 42% saving
    optInMult *= (1 - cheapFactor);
    optOutMult *= (1 - cheapFactor);
    appliedFactors.push('Model routing: −42% blended cost');
  }

  if (truncate) {
    optInMult *= (1 - 0.40); // 40% input reduction from history truncation
    appliedFactors.push('History truncation: −40% input');
  }

  if (prompt) {
    optInMult *= (1 - 0.30); // 30% input reduction
    appliedFactors.push('Concise prompts: −30% input');
  }

  if (output) {
    optOutMult *= (1 - 0.30); // 30% output reduction
    appliedFactors.push('Output constraints: −30% output');
  }

  if (batch) {
    // Apply batch after all other reductions
    totalMult *= 0.50; // 50% off remaining cost
    appliedFactors.push('Batch processing: −50% total');
  }

  const effMonthlyIn = monthlyIn * optInMult * callsMult;
  const effMonthlyOut = monthlyOut * optOutMult * callsMult;
  const optInputCost = (effMonthlyIn / 1e6) * inRate;
  const optOutputCost = (effMonthlyOut / 1e6) * outRate;
  const optCost = (optInputCost + optOutputCost) * totalMult;

  const saving = baseCost - optCost;
  const savingPct = baseCost > 0 ? (saving / baseCost * 100) : 0;

  // Update DOM
  document.getElementById('costBefore').textContent = fmt(baseCost);
  document.getElementById('costAfter').textContent = fmt(optCost);
  document.getElementById('savingsPct').textContent = savingPct.toFixed(0) + '%';
  document.getElementById('savingsAmt').textContent = saving > 0 ? `(${fmt(saving)} saved/month)` : '';

  document.getElementById('brkDailyInput').textContent = fmtTokens(dailyIn);
  document.getElementById('brkDailyOutput').textContent = fmtTokens(dailyOut);
  document.getElementById('brkMonthlyTotal').textContent = fmtTokens(monthlyIn + monthlyOut);
  document.getElementById('brkInputCost').textContent = fmt(baseInputCost);
  document.getElementById('brkOutputCost').textContent = fmt(baseOutputCost);
  document.getElementById('brkAnnual').textContent = fmt(optCost * 12);

  // Callout colour
  const callout = document.getElementById('savingsCallout');
  if (savingPct >= 50) {
    callout.style.background = 'var(--color-success-light)';
    callout.style.borderColor = 'color-mix(in oklch, var(--color-success) 30%, transparent)';
    callout.style.color = 'var(--color-success)';
  } else if (savingPct >= 20) {
    callout.style.background = 'var(--color-primary-light)';
    callout.style.borderColor = 'color-mix(in oklch, var(--color-primary) 30%, transparent)';
    callout.style.color = 'var(--color-primary)';
  } else {
    callout.style.background = 'var(--color-surface)';
    callout.style.borderColor = 'var(--color-border)';
    callout.style.color = 'var(--color-text-muted)';
  }
}

// Bind calculator inputs
['calcModel','calcCalls','calcInputTokens','calcOutputTokens'].forEach(id => {
  document.getElementById(id)?.addEventListener('input', calcCost);
  document.getElementById(id)?.addEventListener('change', calcCost);
});
['optCache','optSemantic','optModelSwitch','optTruncate','optPrompt','optOutput','optBatch'].forEach(id => {
  document.getElementById(id)?.addEventListener('change', calcCost);
});
calcCost(); // initial

/* ─── SCROLL ANIMATIONS ─── */
const observer = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      e.target.style.opacity = '1';
      e.target.style.transform = 'translateY(0)';
    }
  });
}, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

document.querySelectorAll('.lever-card, .hosting-card, .scenario-card, .tco-card, .maturity-card, .tool-card, .buying-card, .fact-item').forEach(el => {
  el.style.opacity = '0';
  el.style.transform = 'translateY(20px)';
  el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
  observer.observe(el);
});

/* ─── ANIMATE SAVINGS BARS ON SCROLL ─── */
const barObserver = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      // Bars start at 0 width via inline style initially to prevent flash
      e.target.querySelectorAll('.savings-bar-fill').forEach(bar => {
        const target = bar.style.width;
        bar.style.width = '0%';
        setTimeout(() => { bar.style.width = target; }, 100);
      });
      barObserver.unobserve(e.target);
    }
  });
}, { threshold: 0.2 });
document.querySelectorAll('.savings-summary').forEach(el => barObserver.observe(el));
