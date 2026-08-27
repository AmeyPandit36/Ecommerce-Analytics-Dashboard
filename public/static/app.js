/* Ecommerce Analytics Dashboard — client runtime
   Chart rendering, global filters, interactive product table, AI analyst.
   No framework, no build step. Every number shown here comes from the server
   (which computes it with SQL over the bundled dataset) - nothing is simulated. */
(() => {
  'use strict';

  const PAGE = readJson('page-data') || { charts: {}, productTable: null, filters: {}, routes: {} };
  const PALETTE = {
    cyan: '#22d3ee', blue: '#60a5fa', violet: '#a78bfa', amber: '#fbbf24', emerald: '#34d399',
    rose: '#fb7185', teal: '#2dd4bf', orange: '#fb923c', slate: '#7c8ba1'
  };
  const ORDER = ['cyan', 'violet', 'blue', 'teal', 'emerald', 'amber', 'slate', 'rose', 'orange'];
  const charts = new Map();

  /* --------------------------------------------------------------- helpers */
  function readJson(id) {
    const node = document.getElementById(id);
    if (!node) return null;
    try { return JSON.parse(node.textContent); } catch (err) { console.error('bad payload', err); return null; }
  }
  function color(name) { return PALETTE[name] || (typeof name === 'string' && name.startsWith('#') ? name : PALETTE.cyan); }
  function rgba(hex, alpha) {
    const h = hex.replace('#', '');
    const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
    const num = parseInt(full, 16);
    return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
  }
  const nf = (digits) => new Intl.NumberFormat('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });

  function fmtINR(v, compact) {
    if (v === null || v === undefined || isNaN(v)) return 'n/a';
    const sign = v < 0 ? '-' : ''; const a = Math.abs(v);
    if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`;
    if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`;
    if (compact && a >= 1e4) return `${sign}₹${(a / 1e3).toFixed(1)}k`;
    return `${sign}₹${nf(0).format(a)}`;
  }
  function fmtValue(v, unit) {
    if (v === null || v === undefined || isNaN(v)) return 'n/a';
    switch (unit) {
      case 'inr': return fmtINR(v);
      case 'pct': return `${Number(v).toFixed(1)}%`;
      case 'count': return nf(0).format(v);
      case 'num1': return nf(1).format(v);
      case 'num2': return nf(2).format(v);
      case 'sec': { const s = Math.round(v); return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`; }
      default: return nf(v % 1 ? 2 : 0).format(v);
    }
  }
  function fmtTick(v, unit) {
    const num = Number(v);
    if (unit === 'inr') return fmtINR(num, true);
    if (unit === 'pct') return `${num.toFixed(0)}%`;
    const abs = Math.abs(num);
    if (abs >= 1e7) return `${(num / 1e7).toFixed(1)}Cr`;
    if (abs >= 1e5) return `${(num / 1e5).toFixed(1)}L`;
    if (abs >= 1000) return `${(num / 1000).toFixed(abs >= 10000 ? 0 : 1)}k`;
    return `${num}`;
  }
  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  }
  function debounce(fn, ms) { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); }; }

  /* ------------------------------------------------------------- chart.js */
  function baseOptions(spec) {
    const horizontal = !!spec.horizontal;
    const donut = spec.type === 'donut' || spec.type === 'pie';
    const primary = (spec.series.find(s => (s.axis || 'y') === 'y') || spec.series[0] || {});
    const primaryUnit = spec.unit && spec.unit !== 'num' ? spec.unit : (primary.unit || 'num');
    const secondary = spec.series.find(s => s.axis === 'y1');
    const tooltipTotal = donut || spec.tooltipTotal;

    const options = {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: horizontal ? 'y' : 'x',
      animation: { duration: 420, easing: 'easeOutQuart' },
      interaction: { mode: 'index', intersect: false },
      layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } },
      plugins: {
        legend: {
          display: spec.legend !== false && (donut || spec.series.length > 1),
          position: donut ? 'right' : 'bottom',
          labels: {
            usePointStyle: true, boxWidth: 7, boxHeight: 7, padding: 12,
            color: '#9aa9c2', font: { size: 11.5, family: getFont() }
          }
        },
        tooltip: {
          backgroundColor: 'rgba(9,14,26,.97)', borderColor: 'rgba(148,163,184,.2)', borderWidth: 1,
          padding: 10, cornerRadius: 9, titleColor: '#e8eefc', bodyColor: '#c3cfe4', displayColors: true,
          boxWidth: 8, boxHeight: 8, usePointStyle: true, bodySpacing: 5,
          titleFont: { size: 12, weight: '600', family: getFont() },
          bodyFont: { size: 11.5, family: getFont() },
          callbacks: {
            label(ctx) {
              const ds = ctx.dataset || {};
              const unit = ds.meta && ds.meta.unit ? ds.meta.unit : (ctx.datasetIndex === 0 ? primaryUnit : (secondary ? spec.unit : primaryUnit));
              const raw = ctx.parsed === null || ctx.parsed === undefined ? null
                : (typeof ctx.parsed === 'object' ? (horizontal ? ctx.parsed.x : ctx.parsed.y) : ctx.parsed);
              const value = fmtValue(raw, ds.meta && ds.meta.unit ? ds.meta.unit : unit);
              const label = ds.label ? `${ds.label}: ` : '';
              if (tooltipTotal) {
                const total = (ctx.dataset.data || []).reduce((sum, v) => sum + (Number(v) || 0), 0);
                const share = total ? ` (${((Number(raw) || 0) / total * 100).toFixed(1)}%)` : '';
                return `${label}${value}${share}`;
              }
              return `${label}${value}`;
            }
          }
        }
      }
    };

    if (!donut) {
      options.scales = {
        x: {
          grid: { display: horizontal, color: 'rgba(148,163,184,.09)', drawBorder: false },
          border: { display: false },
          stacked: !!spec.stacked,
          beginAtZero: horizontal,
          ticks: {
            color: '#8ea0bb', font: { size: 11, family: getFont() }, autoSkip: true,
            maxTicksLimit: spec.maxTicks || (horizontal ? 8 : undefined),
            callback(value) { return horizontal ? fmtTick(this.getLabelForValue(value), primaryUnit) : this.getLabelForValue(value); }
          }
        },
        y: {
          grid: { display: !horizontal, color: 'rgba(148,163,184,.09)', drawBorder: false },
          border: { display: false },
          stacked: !!spec.stacked,
          beginAtZero: true,
          ticks: {
            color: '#8ea0bb', font: { size: 11, family: getFont() }, maxTicksLimit: 6, padding: 6,
            callback(value) { return horizontal ? this.getLabelForValue(value) : fmtTick(value, primaryUnit); }
          }
        }
      };
      if (secondary) {
        options.scales.y1 = {
          position: 'right', beginAtZero: true, grid: { display: false }, border: { display: false },
          ticks: { color: '#7c8ba1', font: { size: 10.5, family: getFont() }, maxTicksLimit: 5,
                   callback(value) { return fmtTick(value, secondary.unit || 'num'); } }
        };
      }
      if (horizontal) {
        options.scales.x.ticks.callback = function (value) { return fmtTick(this.getLabelForValue(value), primaryUnit); };
        options.scales.y.ticks.callback = function (value) { return this.getLabelForValue(value); };
      }
    } else {
      options.cutout = '62%';
    }
    return options;
  }

  function getFont() { return '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif'; }

  function buildDatasets(spec) {
    const donut = spec.type === 'donut' || spec.type === 'pie';
    const horizontal = !!spec.horizontal;
    return spec.series.map((s, index) => {
      const base = {
        label: s.label || '',
        data: s.data || [],
        meta: { unit: s.unit },
        yAxisID: s.axis === 'y1' ? 'y1' : 'y',
        order: s.type === 'line' ? 0 : 1
      };
      if (donut) {
        const colors = s.colors && s.colors.length === (s.data || []).length
          ? s.colors.map(color) : (s.data || []).map((_, i) => color(ORDER[i % ORDER.length]));
        return {
          ...base, backgroundColor: colors, borderColor: 'rgba(7,10,18,.9)', borderWidth: 2,
          hoverOffset: 8, hoverBorderColor: '#0b1120'
        };
      }
      const stroke = color(s.color || ORDER[index % ORDER.length]);
      if ((s.type || (spec.type === 'line' || spec.type === 'area' ? 'line' : 'bar')) === 'line') {
        const fill = s.fill && spec.type === 'area'
          ? (ctx) => {
            const { chart } = ctx; const { ctx: c, chartArea } = chart;
            if (!chartArea) return rgba(stroke, .16);
            const grad = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
            grad.addColorStop(0, rgba(stroke, .32)); grad.addColorStop(1, rgba(stroke, .01));
            return grad;
          } : (s.fill ? rgba(stroke, .12) : false);
        return {
          ...base, type: 'line', borderColor: stroke, borderWidth: 2, pointRadius: 0,
          pointHoverRadius: 4, pointBackgroundColor: stroke, pointBorderColor: '#0b1120',
          pointBorderWidth: 2, tension: .32, borderDash: s.dash || [], fill, stepped: false
        };
      }
      const bg = s.colors ? s.colors.map((c) => rgba(color(c), .72))
        : rgba(stroke, spec.type === 'bar' && (spec.series || []).length === 1 ? .72 : .62);
      return {
        ...base, type: 'bar', backgroundColor: bg, hoverBackgroundColor: s.colors
          ? s.colors.map((c) => color(c)) : stroke,
        borderColor: 'transparent', borderWidth: 0, borderRadius: 5, borderSkipped: false,
        maxBarThickness: horizontal ? 18 : 34, categoryPercentage: .78, barPercentage: .92
      };
    });
  }

  function renderChart(canvas, spec) {
    if (!window.Chart) { fallback(canvas, 'Chart.js failed to load.'); return; }
    if (!spec) { fallback(canvas, 'No data for this chart.'); return; }
    const id = canvas.dataset.chart;
    if (charts.has(id)) { charts.get(id).destroy(); }
    const hasData = (spec.series || []).some(s => (s.data || []).some(v => v !== null && v !== undefined && v !== 0));
    if (!hasData) { fallback(canvas, 'Nothing to plot for the current filters.'); return; }
    canvas.parentElement.classList.remove('chart-empty');
    const instance = new window.Chart(canvas, {
      type: spec.type === 'donut' || spec.type === 'pie' ? 'doughnut'
        : (spec.type === 'hbar' ? 'bar' : (spec.type === 'line' || spec.type === 'area' ? 'line' : 'bar')),
      data: { labels: spec.labels || [], datasets: buildDatasets(spec) },
      options: baseOptions(spec)
    });
    canvas.dataset.built = instance.options?.indexAxis || 'x';
    charts.set(id, instance);
  }

  function fallback(canvas, message) {
    const wrap = canvas.parentElement;
    wrap.innerHTML = `<div class="chart-fallback">${esc(message)}</div>`;
    wrap.classList.add('chart-empty');
  }

  function renderAllCharts(root = document) {
    root.querySelectorAll('[data-chart]').forEach((canvas) => {
      renderChart(canvas, PAGE.charts[canvas.dataset.chart]);
    });
  }

  /* ------------------------------------------------------------- filters */
  function initFilters() {
    const bar = document.querySelector('[data-filterbar]');
    if (!bar) return;
    bar.querySelectorAll('[data-filter-key]').forEach((input) => {
      const apply = () => {
        const key = input.dataset.filterKey;
        const params = new URLSearchParams(window.location.search);
        if (input.value) params.set(key, input.value); else params.delete(key);
        ['q', 'page', 'sort', 'dir', 'per'].forEach(k => params.delete(k));
        window.location.search = params.toString();
      };
      input.addEventListener('change', apply);
    });
    // Reset is a real <a href="/path"> so the bar still works without JavaScript.
    bar.querySelectorAll('[data-search]').forEach(input => input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') event.preventDefault();
    }));
  }

  /* ------------------------------------------------------- product table */
  function initProductTable() {
    const root = document.querySelector('[data-product-table]');
    if (!root) return;
    const state = Object.assign({ q: '', sort: 'revenue', dir: 'desc', page: 1, per: 12 },
      PAGE.productTable || {});
    const body = root.querySelector('tbody');
    const head = root.querySelector('thead');
    const tools = root.querySelector('[data-tools]');
    if (state.columns) renderTableShell();
    if (tools) bindTools();
    load();

    function query(extra) {
      const params = new URLSearchParams();
      Object.entries(PAGE.filters || {}).forEach(([k, v]) => { if (v) params.set(k, v); });
      const merged = Object.assign({}, state, extra || {});
      if (merged.q) params.set('q', merged.q);
      if (merged.sort) params.set('sort', merged.sort);
      if (merged.dir) params.set('dir', merged.dir);
      if (merged.page) params.set('page', merged.page);
      if (merged.per) params.set('per', merged.per);
      return params;
    }

    function renderTableShell() {
      head.innerHTML = `<tr>${(state.columns || []).map(col => `
        <th class="${col.align === 'right' ? 'num ' : ''}${col.sortable ? 'sortable' : ''}"
            ${col.sortable ? `data-field="${esc(col.field || col.key)}" title="Sort by ${esc(col.label)}"` : ''}>
          ${esc(col.label)}${col.sortable ? '<span class="sort-ind">▲▼</span>' : ''}
        </th>`).join('')}</tr>`;
      body.innerHTML = `<tr><td colspan="${(state.columns || []).length || 8}" class="empty">Loading…</td></tr>`;
      head.querySelectorAll('th.sortable').forEach(th => th.addEventListener('click', () => {
        const field = th.dataset.field;
        state.dir = (state.sort === field && state.dir === 'desc') ? 'asc' : 'desc';
        state.sort = field;
        state.page = 1;
        load();
      }));
    }

    function bindTools() {
      const search = tools.querySelector('[data-search]');
      if (search) {
        search.value = state.q || '';
        search.addEventListener('input', debounce(() => { state.q = search.value.trim(); state.page = 1; load(); }, 260));
      }
      const per = tools.querySelector('[data-per]');
      if (per) { per.value = String(state.per); per.addEventListener('change', () => { state.per = Number(per.value); state.page = 1; load(); }); }
      const clear = tools.querySelector('[data-clear-search]');
      if (clear && search) clear.addEventListener('click', () => { search.value = ''; state.q = ''; state.page = 1; load(); });
    }

    function load() {
      const params = query();
      root.classList.add('is-loading');
      fetch(`${PAGE.routes.products || '/api/products'}?${params}`, { headers: { Accept: 'application/json' } })
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
        .then(data => { if (data && data.ready === false) throw new Error(data.reason || 'dataset unavailable'); render(data); })
        .catch(err => {
          body.innerHTML = `<tr><td colspan="${(state.columns || []).length || 8}" class="empty">
            Could not load products (${esc(err.message)}).</td></tr>`;
        })
        .finally(() => root.classList.remove('is-loading'));
      window.history.replaceState({}, '', `${window.location.pathname}?${params}`.replace(/\?$/, ''));
    }

    function render(data) {
      Object.assign(state, {
        columns: data.columns, rows: data.rows, total: data.total, page: data.page,
        pages: data.pages, per: data.per_page, sort: data.sort, dir: data.direction,
        q: data.q || state.q
      });
      head.querySelectorAll('th').forEach(th => {
        const active = th.dataset.field === state.sort;
        th.classList.toggle('sorted', active);
        const ind = th.querySelector('.sort-ind');
        if (ind) ind.textContent = active ? (state.dir === 'asc' ? '▲' : '▼') : '▲▼';
      });
      if (!state.rows || !state.rows.length) {
        body.innerHTML = `<tr><td colspan="${state.columns.length}" class="empty">
          No products match ${state.q ? `“${esc(state.q)}”` : 'these filters'}.</td></tr>`;
      } else {
        body.innerHTML = state.rows.map(row => `<tr>${state.columns.map(col => `
          <td class="${col.align === 'right' ? 'num' : ''}${col.key === 'product_id' ? ' key' : ''}${col.key === 'category' ? ' dim' : ''}">${esc(row[col.key])}</td>
          `).join('')}</tr>`).join('');
      }
      const info = root.querySelector('[data-count]');
      if (info) {
        const from = state.total ? (state.page - 1) * state.per + 1 : 0;
        const to = Math.min(state.total, (state.page - 1) * state.per + state.per);
        info.innerHTML = `<b>${nf(0).format(state.total)}</b> products${state.q ? ` for “${esc(state.q)}”` : ''}
          · showing ${from}–${to}`;
      }
      renderPager();
    }

    function renderPager() {
      const pager = root.querySelector('[data-pager]');
      if (!pager) return;
      const pages = state.pages || 1;
      const page = state.page || 1;
      const wanted = new Set([1, pages, page, page - 1, page + 1]);
      const list = [...wanted].filter(p => p >= 1 && p <= pages).sort((a, b) => a - b);
      let html = `<button data-go="${page - 1}" ${page <= 1 ? 'disabled' : ''} aria-label="Previous page">‹</button>`;
      let last = 0;
      list.forEach(p => {
        if (last && p - last > 1) html += '<span class="count">…</span>';
        html += `<button data-go="${p}" class="${p === page ? 'current' : ''}">${p}</button>`;
        last = p;
      });
      html += `<button data-go="${page + 1}" ${page >= pages ? 'disabled' : ''} aria-label="Next page">›</button>`;
      pager.innerHTML = html;
      pager.querySelectorAll('button[data-go]').forEach(btn => btn.addEventListener('click', () => {
        const target = Number(btn.dataset.go);
        if (target >= 1 && target <= pages && target !== page) { state.page = target; load(); }
      }));
    }
  }

  /* -------------------------------------------------------------- analyst */
  function initAnalyst() {
    const form = document.querySelector('[data-ask-form]');
    if (!form) return;
    const answers = document.querySelector('[data-answers]');
    const input = form.querySelector('input[name=question]');
    const button = form.querySelector('button[type=submit]');

    form.addEventListener('submit', (event) => { event.preventDefault(); ask(input.value); });
    document.querySelectorAll('[data-ask]').forEach(chip => chip.addEventListener('click', () => {
      const question = chip.dataset.ask;
      input.value = question;
      ask(question);
    }));

    function ask(question) {
      question = (question || '').trim();
      if (!question) { input.focus(); return; }
      button.disabled = true;
      const busy = document.createElement('div');
      busy.className = 'busy';
      busy.innerHTML = '<span class="spinner"></span> Querying the dataset…';
      answers.prepend(busy);
      const params = new URLSearchParams(PAGE.filters || {});
      const started = performance.now();
      fetch(`${PAGE.routes.ask || '/api/ask'}?${params}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
      })
        .then(r => r.json())
        .then(data => { busy.remove(); answers.prepend(renderAnswer(data, question)); })
        .catch(err => {
          busy.remove();
          answers.prepend(card(`Could not reach the analyst API`, `${err.message}`, 'error'));
        })
        .finally(() => {
          button.disabled = false; input.focus(); input.select();
          const ms = Math.round(performance.now() - started);
          const stamp = answers.querySelector('.answer .took');
          if (stamp) stamp.textContent = `${ms} ms`;
        });
    }

    function card(title, body, tone) {
      const el = document.createElement('div');
      el.className = 'answer';
      el.innerHTML = `<div class="q">${icon('sparkles')}<span>${esc(title)}</span></div>
        <div class="a"><div class="headline">${esc(title)}</div>
        <div class="body">${esc(body)}</div></div>`;
      return el;
    }

    function renderAnswer(data, question) {
      const el = document.createElement('div');
      el.className = 'answer';
      const conf = data.confidence === 'measured'
        ? '<span class="pill ok"><span class="dot"></span>computed from data</span>'
        : `<span class="pill ${data.confidence === 'error' ? 'warn' : ''}"><span class="dot"></span>${esc(data.confidence || 'n/a')}</span>`;
      const filters = Object.values(data.filters || {}).filter(Boolean);
      const evidence = data.evidence && data.evidence.rows && data.evidence.rows.length
        ? `<div class="table-wrap"><table class="data"><thead><tr>${data.evidence.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
             <tbody>${data.evidence.rows.map(r => `<tr>${r.map(cell => `<td>${esc(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
        : '';
      el.innerHTML = `
        <div class="q">${icon('search')}<span>${esc(question)}</span>
          <span style="margin-left:auto;display:flex;gap:7px;align-items:center">
            ${filters.length ? `<span class="pill">${filters.length} filter${filters.length > 1 ? 's' : ''} applied</span>` : ''}
            ${conf}<span class="pill count took">…</span>
          </span></div>
        <div class="a">
          <div class="headline">${esc(data.answer || 'No answer returned.')}</div>
          ${data.detail ? `<div class="body">${esc(data.detail)}</div>` : ''}
          <div class="grid-2">
            <div>${evidence}</div>
            <div>${data.chart ? `<div class="chart-wrap" style="--chart-h:${data.chart.height || 240}px"><canvas></canvas></div>` : ''}</div>
          </div>
          ${data.method || data.limitations ? `<div class="grid-2">
            ${data.method ? `<div class="note">${icon('database')}<div><div class="t">How this was computed</div><p>${esc(data.method)}</p></div></div>` : ''}
            ${data.limitations ? `<div class="note warn">${icon('warning')}<div><div class="t">Limitations</div><p>${esc(data.limitations)}</p></div></div>` : ''}
          </div>` : ''}
          ${data.llm_polished ? `<div class="meta"><span class="pill">narrative rephrased by LLM · numbers untouched</span></div>` : ''}
          ${data.llm_error ? `<div class="meta"><span class="pill warn">LLM polish skipped: ${esc(data.llm_error)}</span></div>` : ''}
          ${(data.followups || []).length ? `<div class="suggests">${data.followups.map(q => `<button class="suggest" data-followup="${esc(q)}">${esc(q)}</button>`).join('')}</div>` : ''}
        </div>`;
      if (data.chart) {
        const canvas = el.querySelector('canvas');
        const id = `ai_${Math.random().toString(36).slice(2, 8)}`;
        PAGE.charts[id] = data.chart;
        canvas.dataset.chart = id;
        renderChart(canvas, data.chart);
      }
      el.querySelectorAll('[data-followup]').forEach(btn => btn.addEventListener('click', () => {
        input.value = btn.dataset.followup; ask(btn.dataset.followup);
      }));
      return el;
    }

    const initial = new URLSearchParams(window.location.search).get('q');
    if (initial) { input.value = initial; ask(initial); }
  }

  function icon(name) {
    return `<svg class="i" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  }

  /* ------------------------------------------------------------- bootstrap */
  document.addEventListener('DOMContentLoaded', () => {
    renderAllCharts();
    initFilters();
    initProductTable();
    initAnalyst();
    window.addEventListener('resize', debounce(() => charts.forEach(c => c.resize()), 160));
  });
})();
