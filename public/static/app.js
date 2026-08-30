/* E-Commerce Customer Behavior & Purchase Analysis — client runtime
   Chart rendering (light BI theme) + global slicers. No framework, no build step.
   Every number shown here comes from the server (SQL over the bundled dataset). */
(() => {
  'use strict';

  const PAGE = readJson('page-data') || { charts: {}, filters: {}, routes: {} };
  const PALETTE = {
    blue: '#2563eb', teal: '#0d9488', violet: '#7c3aed', amber: '#d97706',
    emerald: '#059669', rose: '#e11d48', slate: '#64748b', orange: '#ea580c',
    cyan: '#0891b2', sky: '#0284c7'
  };
  const ORDER = ['blue', 'teal', 'violet', 'amber', 'emerald', 'slate', 'rose', 'orange', 'sky', 'cyan'];
  const charts = new Map();

  /* --------------------------------------------------------------- helpers */
  function readJson(id) {
    const node = document.getElementById(id);
    if (!node) return null;
    try { return JSON.parse(node.textContent); } catch (err) { console.error('bad payload', err); return null; }
  }
  function color(name) { return PALETTE[name] || (typeof name === 'string' && name.startsWith('#') ? name : PALETTE.blue); }
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
      animation: { duration: 380, easing: 'easeOutQuart' },
      interaction: { mode: 'index', intersect: false },
      layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } },
      plugins: {
        legend: {
          display: spec.legend !== false && (donut || spec.series.length > 1),
          position: donut ? 'right' : 'bottom',
          labels: {
            usePointStyle: true, boxWidth: 8, boxHeight: 8, padding: 14,
            color: '#4b5563', font: { size: 11.5, family: getFont() }
          }
        },
        tooltip: {
          backgroundColor: '#ffffff', borderColor: '#cbd1d8', borderWidth: 1,
          padding: 10, cornerRadius: 7, titleColor: '#1f2933', bodyColor: '#4b5563',
          displayColors: true, boxWidth: 8, boxHeight: 8, usePointStyle: true, bodySpacing: 5,
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
          grid: { display: horizontal, color: '#eef1f4', drawBorder: false },
          border: { display: false },
          stacked: !!spec.stacked,
          beginAtZero: horizontal,
          ticks: {
            color: '#8a94a3', font: { size: 11, family: getFont() }, autoSkip: true,
            maxTicksLimit: spec.maxTicks || (horizontal ? 8 : undefined),
            callback(value) { return horizontal ? fmtTick(this.getLabelForValue(value), primaryUnit) : this.getLabelForValue(value); }
          }
        },
        y: {
          grid: { display: !horizontal, color: '#eef1f4', drawBorder: false },
          border: { display: false },
          stacked: !!spec.stacked,
          beginAtZero: true,
          ticks: {
            color: '#8a94a3', font: { size: 11, family: getFont() }, maxTicksLimit: 6, padding: 6,
            callback(value) { return horizontal ? this.getLabelForValue(value) : fmtTick(value, primaryUnit); }
          }
        }
      };
      if (secondary) {
        options.scales.y1 = {
          position: 'right', beginAtZero: true, grid: { display: false }, border: { display: false },
          ticks: { color: '#9aa3af', font: { size: 10.5, family: getFont() }, maxTicksLimit: 5,
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
          ...base, backgroundColor: colors, borderColor: '#ffffff', borderWidth: 2,
          hoverOffset: 6
        };
      }
      const stroke = color(s.color || ORDER[index % ORDER.length]);
      if ((s.type || (spec.type === 'line' || spec.type === 'area' ? 'line' : 'bar')) === 'line') {
        const fill = s.fill && spec.type === 'area'
          ? (ctx) => {
            const { chart } = ctx; const { ctx: c, chartArea } = chart;
            if (!chartArea) return rgba(stroke, .14);
            const grad = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
            grad.addColorStop(0, rgba(stroke, .26)); grad.addColorStop(1, rgba(stroke, .01));
            return grad;
          } : (s.fill ? rgba(stroke, .12) : false);
        return {
          ...base, type: 'line', borderColor: stroke, borderWidth: 2, pointRadius: 0,
          pointHoverRadius: 4, pointBackgroundColor: stroke, pointBorderColor: '#ffffff',
          pointBorderWidth: 2, tension: .32, borderDash: s.dash || [], fill, stepped: false
        };
      }
      const bg = s.colors ? s.colors.map((c) => rgba(color(c), .85))
        : rgba(stroke, spec.type === 'bar' && (spec.series || []).length === 1 ? .85 : .7);
      return {
        ...base, type: 'bar', backgroundColor: bg, hoverBackgroundColor: s.colors
          ? s.colors.map((c) => color(c)) : stroke,
        borderColor: 'transparent', borderWidth: 0, borderRadius: 4, borderSkipped: false,
        maxBarThickness: horizontal ? 20 : 34, categoryPercentage: .72, barPercentage: .9
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

  /* ------------------------------------------------------------- slicers */
  function initFilters() {
    const bar = document.querySelector('[data-filterbar]');
    if (!bar) return;
    bar.querySelectorAll('[data-filter-key]').forEach((input) => {
      const apply = () => {
        const key = input.dataset.filterKey;
        const params = new URLSearchParams(window.location.search);
        if (input.value) params.set(key, input.value); else params.delete(key);
        window.location.search = params.toString();
      };
      input.addEventListener('change', apply);
    });
  }

  /* ------------------------------------------------------------- bootstrap */
  document.addEventListener('DOMContentLoaded', () => {
    renderAllCharts();
    initFilters();
    window.addEventListener('resize', debounce(() => charts.forEach(c => c.resize()), 160));
  });
})();
