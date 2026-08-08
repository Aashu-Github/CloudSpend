window.CloudSpend = (() => {
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

  function safeJson(value, fallback) {
    try { return JSON.parse(value || ''); } catch (_) { return fallback; }
  }

  function showModal(title, message, kicker = 'CLOUDSPEND') {
    const modal = document.getElementById('app-modal');
    if (!modal) return;
    const titleEl = document.getElementById('modal-title');
    const messageEl = document.getElementById('modal-message');
    const kickerEl = document.getElementById('modal-kicker');
    if (titleEl) titleEl.textContent = title;
    if (messageEl) messageEl.textContent = message;
    if (kickerEl) kickerEl.textContent = kicker;
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    modal.querySelector('[data-modal-close]')?.focus();
  }

  function closeModal() {
    const modal = document.getElementById('app-modal');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }

  function initModal() {
    document.querySelectorAll('[data-modal-close]').forEach((el) => el.addEventListener('click', closeModal));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
  }

  function initMobileMenu() {
    const button = document.querySelector('.mobile-menu-btn');
    const links = document.getElementById('navLinks');
    if (!button || !links) return;
    button.addEventListener('click', () => {
      const open = links.classList.toggle('open');
      button.setAttribute('aria-expanded', String(open));
    });
    links.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
      links.classList.remove('open');
      button.setAttribute('aria-expanded', 'false');
    }));
  }

  function initCursor() {
    if (!window.matchMedia?.('(pointer:fine)').matches) return;
    const dot = document.querySelector('.cursor');
    const ring = document.querySelector('.cursor-ring');
    if (!dot || !ring) return;
    let rx = 0, ry = 0, tx = 0, ty = 0;
    document.body.classList.add('cursor-ready');
    document.addEventListener('mousemove', (e) => {
      tx = e.clientX; ty = e.clientY;
      dot.style.left = `${tx}px`; dot.style.top = `${ty}px`;
    });
    const animate = () => {
      rx += (tx - rx) * 0.18; ry += (ty - ry) * 0.18;
      ring.style.left = `${rx}px`; ring.style.top = `${ry}px`;
      requestAnimationFrame(animate);
    };
    animate();
    document.querySelectorAll('a,button,input,select,label,[role="button"]').forEach((el) => {
      el.addEventListener('mouseenter', () => document.body.classList.add('cursor-hover'));
      el.addEventListener('mouseleave', () => document.body.classList.remove('cursor-hover'));
    });
  }

  function initImport() {
    const zone = document.getElementById('drop-zone');
    const input = document.getElementById('file-input');
    const status = document.getElementById('import-status');
    if (!zone || !input || !status) return;

    zone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        input.click();
      }
    });

    ['dragenter', 'dragover'].forEach((eventName) => zone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      zone.classList.add('dragging');
    }));
    ['dragleave', 'dragend'].forEach((eventName) => zone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      zone.classList.remove('dragging');
    }));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      zone.classList.remove('dragging');
      const file = e.dataTransfer?.files?.[0];
      if (file) upload(file);
    });
    input.addEventListener('change', () => {
      if (input.files?.[0]) upload(input.files[0]);
      input.value = '';
    });

    async function upload(file) {
      const allowed = ['.json', '.csv', '.xlsx', '.zip'];
      const lower = file.name.toLowerCase();
      const extensionOk = allowed.some((ext) => lower.endsWith(ext));
      const maxBytes = Number(zone.dataset.maxBytes || 0);
      status.hidden = false;

      if (!extensionOk) {
        status.className = 'status-box error';
        status.textContent = 'Unsupported file type. Use JSON, CSV, XLSX, or ZIP.';
        showModal('That file cannot be imported.', 'CloudSpend supports JSON, CSV, XLSX, and ZIP files in the MVP.', 'IMPORT FAILED');
        return;
      }
      if (maxBytes && file.size > maxBytes) {
        const limit = Math.round(maxBytes / 1024 / 1024);
        status.className = 'status-box error';
        status.textContent = `File is larger than the configured ${limit} MB limit.`;
        showModal('That file is too large.', `Choose a file smaller than the configured ${limit} MB limit.`, 'IMPORT FAILED');
        return;
      }

      status.className = 'status-box loading';
      status.textContent = `Validating and analyzing ${file.name}…`;
      const form = new FormData();
      form.append('file', file);

      try {
        const response = await fetch('/api/import', {
          method: 'POST',
          body: form,
          headers: {'X-CSRF-Token': csrf(), 'Accept': 'application/json'}
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          if (data.mapping_proposal) {
            const confidence = Math.round((data.mapping_proposal.overall_confidence || 0) * 100);
            const message = `Deterministic mapping did not match. AI proposed a schema mapping (${confidence}% confidence). Human review is required before applying it; no values were silently imported.`;
            status.className = 'status-box warning';
            status.textContent = message;
            showModal('Schema review is required.', message, 'IMPORT NEEDS REVIEW');
            return;
          }
          throw new Error(data.error || 'Import failed safely.');
        }
        status.className = 'status-box success';
        status.textContent = 'Import complete. Opening dashboard…';
        window.location.assign(data.redirect);
      } catch (err) {
        const message = err?.message || 'The file could not be imported.';
        status.className = 'status-box error';
        status.textContent = message;
        showModal('CloudSpend could not import that file.', message, 'IMPORT FAILED');
      }
    }
  }

  function initAwsScan() {
    const form = document.getElementById('aws-scan-form');
    if (!form) return;
    const button = form.querySelector('[data-scan-button]');

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const original = button?.textContent || 'Run read-only scan →';
      if (button) { button.disabled = true; button.textContent = 'Checking AWS…'; }

      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          headers: {'X-CSRF-Token': csrf(), 'Accept': 'application/json', 'X-Requested-With': 'fetch'}
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'CloudSpend could not connect to AWS with the supplied local configuration.');
        if (!data.redirect) throw new Error('The scan completed without a dashboard destination.');
        window.location.assign(data.redirect);
      } catch (err) {
        showModal(
          'Live AWS scan could not run.',
          err?.message || 'Check that your AWS CLI or SSO session is authenticated and that the profile and regions are valid.',
          'AWS CONNECTION FAILED'
        );
      } finally {
        if (button) { button.disabled = false; button.textContent = original; }
      }
    });
  }

  function initDashboard(pointsArg) {
    const category = document.getElementById('filter-category');
    const confidence = document.getElementById('filter-confidence');
    const environment = document.getElementById('filter-environment');
    const cards = [...document.querySelectorAll('.rec-card[data-category]')];
    const apply = () => cards.forEach((card) => {
      const okCategory = !category?.value || card.dataset.category === category.value;
      const okConfidence = !confidence?.value || card.dataset.confidence === confidence.value;
      const okEnvironment = !environment?.value || card.dataset.environment === environment.value;
      card.hidden = !(okCategory && okConfidence && okEnvironment);
    });
    category?.addEventListener('change', apply);
    confidence?.addEventListener('change', apply);
    environment?.addEventListener('change', apply);

    const chart = document.getElementById('cost-util-chart');
    if (!chart || !window.Plotly) return;
    const points = pointsArg || safeJson(chart.dataset.points, []);
    const valid = (points || []).filter((p) => p.cpu !== null && p.cost !== null);
    if (!valid.length) {
      chart.innerHTML = '<div class="empty-inline">Cost/utilization correlation needs both CPU and cost evidence.</div>';
      return;
    }
    const trace = {
      x: valid.map((p) => p.cpu), y: valid.map((p) => p.cost), mode: 'markers', type: 'scatter',
      text: valid.map((p) => `${p.name}<br>${p.id}<br>${p.basis} cost`),
      marker: {size: valid.map((p) => p.opportunity ? 17 : 11), opacity: .88, line: {width: 1, color: 'rgba(255,255,255,.22)'}, color: valid.map((p) => p.opportunity ? '#69acc2' : '#5c6370')},
      hovertemplate: '%{text}<br>CPU avg %{x:.1f}%<br>Monthly cost $%{y:.2f}<extra></extra>'
    };
    window.Plotly.newPlot(chart, [trace], {
      paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', margin: {l: 58, r: 20, t: 10, b: 50},
      xaxis: {title: 'Average CPU utilization (%)', gridcolor: 'rgba(255,255,255,.06)', zeroline: false, color: 'rgba(241,240,255,.55)'},
      yaxis: {title: 'Monthly equivalent cost ($)', gridcolor: 'rgba(255,255,255,.06)', zeroline: false, color: 'rgba(241,240,255,.55)'},
      font: {family: 'Instrument Sans, sans-serif', color: '#f1f0ff'}, showlegend: false,
      hoverlabel: {bgcolor: '#101018', bordercolor: '#69acc2'}
    }, {responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso2d', 'select2d']});
  }

  function initResourceChart(metricsArg) {
    const chart = document.getElementById('resource-chart');
    if (!chart || !window.Plotly) return;
    const metrics = metricsArg || safeJson(chart.dataset.metrics, {});
    if (!metrics || !Object.keys(metrics).length) return;
    let days = 14;
    const draw = () => {
      const cutoff = Date.now() - days * 86400000;
      const traces = Object.entries(metrics).map(([name, m]) => {
        const pairs = (m.timestamps || []).map((t, i) => [t, m.values[i]]).filter(([t]) => new Date(t).getTime() >= cutoff);
        return {x: pairs.map((p) => p[0]), y: pairs.map((p) => p[1]), mode: 'lines+markers', name: `${name}${m.unit ? ` (${m.unit})` : ''}`, line: {width: 2}, marker: {size: 4}, hovertemplate: `${name}<br>%{x}<br>%{y:.2f}<extra></extra>`};
      });
      window.Plotly.newPlot(chart, traces, {
        paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', margin: {l: 55, r: 20, t: 15, b: 50},
        xaxis: {gridcolor: 'rgba(255,255,255,.06)', color: 'rgba(241,240,255,.55)'},
        yaxis: {gridcolor: 'rgba(255,255,255,.06)', color: 'rgba(241,240,255,.55)'},
        font: {family: 'Instrument Sans, sans-serif', color: '#f1f0ff'}, legend: {orientation: 'h', y: 1.12}
      }, {responsive: true, displaylogo: false});
    };
    document.querySelectorAll('[data-window]').forEach((button) => button.addEventListener('click', () => {
      days = Number(button.dataset.window);
      document.querySelectorAll('[data-window]').forEach((b) => b.classList.remove('active'));
      button.classList.add('active');
      draw();
    }));
    draw();
  }

  function autoInit() {
    initModal();
    initMobileMenu();
    initCursor();
    initImport();
    initAwsScan();
    initDashboard();
    initResourceChart();
  }

  document.addEventListener('DOMContentLoaded', autoInit);
  return {initImport, initAwsScan, initDashboard, initResourceChart, showModal};
})();
