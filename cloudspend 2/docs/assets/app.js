window.CloudSpendPages = (() => {
  const cfg = window.CLOUDSPEND_CONFIG || {};
  const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
  const override = new URLSearchParams(window.location.search).get('api') || localStorage.getItem('cloudspend_api_base_url');
  const apiBase = (override || (isLocal ? cfg.localApiBaseUrl : cfg.productionApiBaseUrl) || '').replace(/\/$/, '');

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const money = (value) => value === null || value === undefined || value === '' ? '—' : `$${Number(value).toFixed(2)}`;
  const num = (value, digits = 1) => value === null || value === undefined ? '—' : Number(value).toFixed(digits);

  function api(path) {
    if (!apiBase || apiBase.includes('YOUR-')) throw new Error('CloudSpend API URL is not configured. Deploy the Render backend, then update docs/assets/config.js.');
    return `${apiBase}${path}`;
  }

  function showModal(title, message, kicker = 'CLOUDSPEND', code = '') {
    const modal = $('#app-modal');
    if (!modal) return;
    $('#modal-title').textContent = title;
    $('#modal-message').textContent = message;
    $('#modal-kicker').textContent = kicker;
    const codeEl = $('#modal-code');
    if (codeEl) {
      codeEl.hidden = !code;
      codeEl.textContent = code || '';
    }
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }

  function closeModal() {
    const modal = $('#app-modal');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }

  function initBase() {
    $$('[data-modal-close]').forEach((el) => el.addEventListener('click', closeModal));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

    const menu = $('.mobile-menu-btn');
    const links = $('#navLinks');
    menu?.addEventListener('click', () => {
      const open = links?.classList.toggle('open');
      menu.setAttribute('aria-expanded', String(Boolean(open)));
    });

    if (window.matchMedia?.('(pointer:fine)').matches) {
      const dot = $('.cursor'); const ring = $('.cursor-ring');
      if (dot && ring) {
        let rx = 0, ry = 0, tx = 0, ty = 0;
        document.body.classList.add('cursor-ready');
        document.addEventListener('mousemove', (e) => { tx = e.clientX; ty = e.clientY; dot.style.left = `${tx}px`; dot.style.top = `${ty}px`; });
        const animate = () => { rx += (tx-rx)*.18; ry += (ty-ry)*.18; ring.style.left = `${rx}px`; ring.style.top = `${ry}px`; requestAnimationFrame(animate); };
        animate();
        $$('a,button,input,select,label,[role="button"]').forEach((el) => {
          el.addEventListener('mouseenter', () => document.body.classList.add('cursor-hover'));
          el.addEventListener('mouseleave', () => document.body.classList.remove('cursor-hover'));
        });
      }
    }
  }

  async function fetchJson(path, options = {}) {
    let response;
    try {
      response = await fetch(api(path), {headers: {Accept: 'application/json', ...(options.headers || {})}, ...options});
    } catch (_) {
      throw new Error('The CloudSpend API is unavailable. If you just deployed Render, wait for it to finish starting and try again.');
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `CloudSpend API returned ${response.status}.`);
    return data;
  }

  async function startDemo(buttons = []) {
    const originals = buttons.map((b) => b?.textContent);
    buttons.forEach((b) => { if (b) { b.disabled = true; b.textContent = 'Loading demo…'; } });
    try {
      const data = await fetchJson('/api/public/demo', {method: 'POST'});
      window.location.assign(`./scan.html?id=${encodeURIComponent(data.scan_id)}`);
    } catch (err) {
      showModal('The hosted demo could not start.', err.message, 'API UNAVAILABLE');
    } finally {
      buttons.forEach((b, i) => { if (b) { b.disabled = false; b.textContent = originals[i]; } });
    }
  }

  async function initHome() {
    const status = $('#api-status');
    try {
      await fetchJson('/api/public/health');
      status?.classList.add('online');
      status?.querySelector('span:last-child') && (status.querySelector('span:last-child').textContent = 'Connected');
    } catch (_) {
      status?.classList.add('offline');
      status?.querySelector('span:last-child') && (status.querySelector('span:last-child').textContent = 'Offline');
    }
    const demo = $('#demo-button'); const project = $('#demo-project-button');
    demo?.addEventListener('click', () => startDemo([demo, project]));
    project?.addEventListener('click', () => startDemo([demo, project]));
  }

  function initImport() {
    const zone = $('#drop-zone'); const input = $('#file-input'); const status = $('#import-status');
    if (!zone || !input || !status) return;
    zone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    ['dragenter','dragover'].forEach((name) => zone.addEventListener(name, (e) => { e.preventDefault(); e.stopPropagation(); zone.classList.add('dragging'); if (e.dataTransfer) e.dataTransfer.dropEffect='copy'; }));
    ['dragleave','dragend'].forEach((name) => zone.addEventListener(name, (e) => { e.preventDefault(); e.stopPropagation(); zone.classList.remove('dragging'); }));
    zone.addEventListener('drop', (e) => { e.preventDefault(); e.stopPropagation(); zone.classList.remove('dragging'); const file=e.dataTransfer?.files?.[0]; if (file) upload(file); });
    input.addEventListener('change', () => { if (input.files?.[0]) upload(input.files[0]); input.value=''; });

    async function upload(file) {
      const allowed = ['.json','.csv','.xlsx','.zip'];
      const ok = allowed.some((ext) => file.name.toLowerCase().endsWith(ext));
      const maxBytes = Number(zone.dataset.maxBytes || 0);
      status.hidden = false;
      if (!ok) { status.className='status-box error'; status.textContent='Unsupported file type.'; showModal('That file cannot be imported.','CloudSpend supports JSON, CSV, XLSX, and ZIP files.','IMPORT FAILED'); return; }
      if (maxBytes && file.size > maxBytes) { const mb=Math.round(maxBytes/1024/1024); status.className='status-box error'; status.textContent=`File exceeds ${mb} MB.`; showModal('That file is too large.',`Choose a file smaller than ${mb} MB.`,'IMPORT FAILED'); return; }
      status.className='status-box loading'; status.textContent=`Uploading, validating, and analyzing ${file.name}…`;
      const form = new FormData(); form.append('file', file);
      try {
        const data = await fetchJson('/api/public/import', {method:'POST', body:form});
        status.className='status-box success'; status.textContent='Analysis complete. Opening dashboard…';
        window.location.assign(`./scan.html?id=${encodeURIComponent(data.scan_id)}`);
      } catch (err) {
        status.className='status-box error'; status.textContent=err.message;
        showModal('CloudSpend could not import that file.',err.message,'IMPORT FAILED');
      }
    }
  }

  function initHostedAws() {
    const form = $('#hosted-aws-form');
    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      showModal(
        'Live AWS scanning runs locally.',
        'GitHub Pages cannot access the AWS CLI profile or SSO session on your computer, and CloudSpend will not ask you to paste AWS secret keys into the browser. Clone the repository and run the read-only scanner locally.',
        'HOSTED MODE LIMITATION',
        './scripts/run.sh --aws-profile cloudspend-readonly --regions us-east-1'
      );
    });
  }

  function recCard(rec, resource, scanId) {
    const evidence = (rec.evidence || []).map((e) => `<div><span>${esc(e.key)}</span><strong>${esc(formatEvidence(e.value))}</strong>${e.threshold !== null && e.threshold !== undefined ? `<small>${esc(formatEvidence(e.threshold))}</small>` : ''}${e.detail ? `<small>${esc(e.detail)}</small>` : ''}</div>`).join('');
    const missing = rec.missing_signals?.length ? `<div class="missing-box"><strong>Missing signals:</strong> ${esc(rec.missing_signals.join(', '))}</div>` : '';
    const name = resource?.name || rec.resource_id;
    return `<article class="rec-card" data-category="${esc(rec.category)}" data-confidence="${esc(rec.confidence)}" data-environment="${esc(resource?.environment || 'unknown')}">
      <div class="rec-main"><div class="rec-top"><span class="category-pill">${esc(String(rec.category).replaceAll('_',' '))}</span><span class="confidence ${esc(rec.confidence)}">${esc(rec.confidence)}</span><span class="rule-id">${esc(rec.rule_id)} · v${esc(rec.rule_version)}</span></div><h3>${esc(rec.title)}</h3><a class="resource-link" href="./resource.html?scan=${encodeURIComponent(scanId)}&id=${encodeURIComponent(rec.resource_id)}">${esc(name)} <span class="mono">${esc(rec.resource_id)}</span> →</a><p>${esc(rec.suggested_action)}</p></div>
      <div class="rec-savings"><span>EST. MONTHLY SAVINGS</span><strong>${money(rec.estimated_monthly_savings)}</strong><small>${esc(rec.savings_basis)} basis</small></div>
      <details><summary>View evidence</summary><div class="evidence-grid">${evidence}</div>${missing}<p class="safety-note">${esc(rec.safety_note)}</p></details>
    </article>`;
  }

  function formatEvidence(value) {
    if (value && typeof value === 'object') return JSON.stringify(value);
    return value ?? '—';
  }

  function renderCostChart(points) {
    const chart = $('#cost-util-chart');
    if (!chart || !window.Plotly) return;
    const valid = (points || []).filter((p) => p.cpu !== null && p.cost !== null);
    if (!valid.length) { chart.innerHTML='<div class="empty-inline">Cost/utilization correlation needs both CPU and cost evidence.</div>'; return; }
    const trace = {x:valid.map(p=>p.cpu),y:valid.map(p=>p.cost),mode:'markers',type:'scatter',text:valid.map(p=>`${esc(p.name)}<br>${esc(p.id)}<br>${esc(p.basis)} cost`),marker:{size:valid.map(p=>p.opportunity?17:11),opacity:.88,line:{width:1,color:'rgba(255,255,255,.22)'},color:valid.map(p=>p.opportunity?'#69acc2':'#5c6370')},hovertemplate:'%{text}<br>CPU avg %{x:.1f}%<br>Monthly cost $%{y:.2f}<extra></extra>'};
    window.Plotly.newPlot(chart,[trace],{paper_bgcolor:'transparent',plot_bgcolor:'transparent',margin:{l:58,r:20,t:10,b:50},xaxis:{title:'Average CPU utilization (%)',gridcolor:'rgba(255,255,255,.06)',zeroline:false,color:'rgba(241,240,255,.55)'},yaxis:{title:'Monthly equivalent cost ($)',gridcolor:'rgba(255,255,255,.06)',zeroline:false,color:'rgba(241,240,255,.55)'},font:{family:'Instrument Sans, sans-serif',color:'#f1f0ff'},showlegend:false,hoverlabel:{bgcolor:'#101018',bordercolor:'#69acc2'}},{responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']});
  }

  async function initScan() {
    const scanId = new URLSearchParams(window.location.search).get('id');
    const root = $('#scan-root');
    if (!scanId || !root) return;
    try {
      const data = await fetchJson(`/api/public/scans/${encodeURIComponent(scanId)}`);
      document.title = `Overview — CloudSpend`;
      const hero = $('#scan-hero');
      hero.innerHTML = `<div><span class="eyebrow">${esc(data.source_mode.toUpperCase())} SCAN · ${esc(data.scan_id.slice(0,8))}</span><h1>Optimization overview.</h1><p>${data.resources.length} canonical resources analyzed through the same deterministic rule engine.</p></div><div class="dashboard-actions"><a class="btn btn-secondary" href="${esc(api(`/api/export/${data.scan_id}.json`))}">Export JSON</a><a class="btn btn-ghost" href="${esc(api(`/api/export/${data.scan_id}-resources.csv`))}">Resources CSV</a><a class="btn btn-ghost" href="${esc(api(`/api/export/${data.scan_id}-recommendations.csv`))}">Findings CSV</a></div>`;
      const notices = [...(data.warnings||[]).map(w=>`<div class="notice warning"><strong>Data quality</strong><span>${esc(w)}</span></div>`), ...(data.errors||[]).map(e=>`<div class="notice error"><strong>Partial scan</strong><span>${esc(e)}</span></div>`)].join('');
      const byId = Object.fromEntries(data.resources.map(r=>[r.resource_id,r]));
      const s = data.summary;
      const envOptions = (s.environments||[]).map(e=>`<option value="${esc(e)}">${esc(e)}</option>`).join('');
      const recs = data.recommendations.length ? data.recommendations.map(r=>recCard(r,byId[r.resource_id],data.scan_id)).join('') : `<div class="empty-state"><span class="eyebrow">NO FINDINGS</span><h3>No optimization opportunity met the configured evidence thresholds.</h3><p>This can mean the fleet looks healthy or the input lacks enough utilization/cost evidence.</p></div>`;
      const rows = data.resources.map(r=>{ const cpu=r.metrics?.CPUUtilization; return `<tr><td><a href="./resource.html?scan=${encodeURIComponent(data.scan_id)}&id=${encodeURIComponent(r.resource_id)}"><strong>${esc(r.name||'Unnamed')}</strong><span class="mono wrap-id">${esc(r.resource_id)}</span></a></td><td>${esc(r.resource_type)}</td><td><span class="state-dot ${esc(String(r.state).toLowerCase())}"></span>${esc(r.state)}</td><td>${esc(r.environment)}</td><td>${cpu?.avg!==null&&cpu?.avg!==undefined?`${num(cpu.avg)}%`:'—'}</td><td>${esc(r.cost_basis)}</td><td>${esc(r.finding_count)}</td></tr>`; }).join('');
      root.className='';
      root.innerHTML = `${notices?`<div class="notice-stack">${notices}</div>`:''}
        <div class="kpi-grid"><div class="kpi-card"><span class="kpi-label">OBSERVED / MODELED SPEND</span><strong>${money(s.observed)}</strong><small>monthly equivalent</small></div><div class="kpi-card glow"><span class="kpi-label">POTENTIAL SAVINGS</span><strong>${money(s.savings)}</strong><small>deduplicated by resource</small></div><div class="kpi-card"><span class="kpi-label">SAVINGS RATE</span><strong>${num(s.savings_pct)}%</strong><small>projection, not guarantee</small></div><div class="kpi-card"><span class="kpi-label">RESOURCES</span><strong>${esc(s.resource_count)}</strong><small>validated canonical objects</small></div><div class="kpi-card"><span class="kpi-label">OPPORTUNITIES</span><strong>${esc(s.opportunity_count)}</strong><small>versioned findings</small></div></div>
        <div class="panel chart-panel"><div class="panel-heading"><div><span class="eyebrow">COST × UTILIZATION</span><h2>Where spend meets workload.</h2></div><div class="cost-legend"><span>actual ${esc(s.cost_basis_counts.actual)}</span><span>allocated ${esc(s.cost_basis_counts.allocated)}</span><span>estimated ${esc(s.cost_basis_counts.estimated)}</span><span>unknown ${esc(s.cost_basis_counts.unavailable)}</span></div></div><div id="cost-util-chart" class="chart"></div></div>
        <div class="section-heading"><div><span class="eyebrow">RECOMMENDATIONS</span><h2>Evidence-backed opportunities.</h2></div><div class="filters"><select id="filter-category"><option value="">All categories</option><option value="idle">Idle</option><option value="rightsize">Rightsize</option><option value="schedule">Schedule</option><option value="orphan_storage">Orphan storage</option><option value="anomaly">Anomaly</option></select><select id="filter-confidence"><option value="">All confidence</option><option>high</option><option>medium</option><option>low</option></select><select id="filter-environment"><option value="">All environments</option>${envOptions}</select></div></div>
        <div class="recommendation-list" id="recommendation-list">${recs}</div>
        <details class="panel scan-diagnostics"><summary><span class="eyebrow">SCAN INFO</span> Data sources & quality</summary><div class="evidence-grid full"><div><span>EC2 resources</span><strong>${esc(s.scan_info.ec2_resources)}</strong></div><div><span>EBS resources</span><strong>${esc(s.scan_info.ebs_resources)}</strong></div><div><span>With metrics</span><strong>${esc(s.scan_info.resources_with_metrics)}</strong></div><div><span>With memory</span><strong>${esc(s.scan_info.resources_with_memory)}</strong></div><div><span>Actual cost</span><strong>${esc(s.cost_basis_counts.actual)}</strong></div><div><span>Allocated cost</span><strong>${esc(s.cost_basis_counts.allocated)}</strong></div><div><span>Estimated cost</span><strong>${esc(s.cost_basis_counts.estimated)}</strong></div><div><span>Rules executed</span><strong>${esc(s.scan_info.rules_executed)}</strong></div></div><p class="safety-note">Provider: ${esc(data.source_mode)}. Missing Cost Explorer or memory telemetry is surfaced as a limitation rather than fabricated.</p></details>
        <div class="section-heading resources-heading"><div><span class="eyebrow">CANONICAL INVENTORY</span><h2>Resources scanned.</h2></div></div><div class="table-wrap"><table class="resource-table"><thead><tr><th>Resource</th><th>Type</th><th>State</th><th>Environment</th><th>CPU avg</th><th>Cost basis</th><th>Findings</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      ['category','confidence','environment'].forEach((key)=>$(`#filter-${key}`)?.addEventListener('change',()=>{ const c=$('#filter-category').value, f=$('#filter-confidence').value, e=$('#filter-environment').value; $$('.rec-card[data-category]').forEach(card=>card.hidden=!((!c||card.dataset.category===c)&&(!f||card.dataset.confidence===f)&&(!e||card.dataset.environment===e))); }));
      renderCostChart(data.chart);
    } catch (err) {
      root.className='empty-state'; root.innerHTML=`<span class="eyebrow">SCAN UNAVAILABLE</span><h3>${esc(err.message)}</h3><p>Hosted scan history is temporary on the free backend. Start a new demo or import the file again.</p>`;
    }
  }

  function detailRow(label, value) { return `<div><dt>${esc(label)}</dt><dd>${esc(value ?? 'unknown')}</dd></div>`; }

  function renderResourceChart(metrics) {
    const chart=$('#resource-chart'); if(!chart||!window.Plotly) return;
    const entries=Object.entries(metrics||{}).filter(([,m])=>m.timestamps?.length&&m.values?.length);
    if(!entries.length){ chart.innerHTML='<div class="empty-inline">No time-series samples were present in this input.</div>'; return; }
    let days=14;
    const draw=()=>{ const cutoff=Date.now()-days*86400000; const traces=entries.map(([name,m])=>{const pairs=m.timestamps.map((t,i)=>[t,m.values[i]]).filter(([t])=>new Date(t).getTime()>=cutoff);return{x:pairs.map(p=>p[0]),y:pairs.map(p=>p[1]),mode:'lines+markers',name:`${name}${m.unit?` (${m.unit})`:''}`,line:{width:2},marker:{size:4},hovertemplate:`${esc(name)}<br>%{x}<br>%{y:.2f}<extra></extra>`};}); window.Plotly.newPlot(chart,traces,{paper_bgcolor:'transparent',plot_bgcolor:'transparent',margin:{l:55,r:20,t:15,b:50},xaxis:{gridcolor:'rgba(255,255,255,.06)',color:'rgba(241,240,255,.55)'},yaxis:{gridcolor:'rgba(255,255,255,.06)',color:'rgba(241,240,255,.55)'},font:{family:'Instrument Sans, sans-serif',color:'#f1f0ff'},legend:{orientation:'h',y:1.12}},{responsive:true,displaylogo:false}); };
    $$('[data-window]').forEach(b=>b.addEventListener('click',()=>{days=Number(b.dataset.window);$$('[data-window]').forEach(x=>x.classList.remove('active'));b.classList.add('active');draw();})); draw();
  }

  async function initResource() {
    const params=new URLSearchParams(window.location.search); const scanId=params.get('scan'); const resourceId=params.get('id'); const root=$('#resource-root');
    if(!scanId||!resourceId||!root) return;
    $('#resource-back').href=`./scan.html?id=${encodeURIComponent(scanId)}`;
    try {
      const data=await fetchJson(`/api/public/scans/${encodeURIComponent(scanId)}/resources/${encodeURIComponent(resourceId)}`); const r=data.resource; const recs=data.recommendations||[];
      document.title=`${r.name||r.resource_id} — CloudSpend`;
      $('#resource-hero').innerHTML=`<a class="back-link" href="./scan.html?id=${encodeURIComponent(scanId)}">← BACK TO OVERVIEW</a><span class="eyebrow">RESOURCE DETAIL</span><h1>${esc(r.name||r.resource_id)}</h1><p class="mono wrap-id">${esc(r.resource_id)} · ${esc(r.region)} · ${esc(r.state)}</p>`;
      let resourceRows=detailRow('Type',r.resource_type)+detailRow('Region',r.region)+detailRow('Account',r.account_id||'not supplied')+detailRow('Source',`${r.source_lineage?.provider_mode||'unknown'} / ${r.source_lineage?.source_family||'canonical'}`);
      if(r.ec2){resourceRows+=detailRow('Instance type',r.ec2.instance_type)+detailRow('Launch time',r.ec2.launch_time||'unknown');}
      if(r.ebs){resourceRows+=detailRow('Size',`${r.ebs.size_gib} GiB`)+detailRow('Encrypted',String(r.ebs.encrypted))+detailRow('Attachments',r.ebs.attachments?.join(', ')||'none');}
      const c=r.costs||{};
      const costRows=detailRow('Actual resource cost',c.actual_resource_cost!=null?money(c.actual_resource_cost):'unavailable')+detailRow('Allocated cost',c.allocated_cost!=null?money(c.allocated_cost):'unavailable')+detailRow('Estimated resource cost',c.estimated_resource_cost!=null?money(c.estimated_resource_cost):'unavailable')+detailRow('Source',c.source)+detailRow('Confidence',c.confidence);
      const tags=Object.entries(r.tags||{}).map(([k,v])=>`<span><b>${esc(k)}</b>=${esc(v)}</span>`).join('');
      const recHtml=recs.length?recs.map(rec=>{const evidence=(rec.evidence||[]).map(e=>`<div><span>${esc(e.key)}</span><strong>${esc(formatEvidence(e.value))}</strong>${e.threshold!=null?`<small>${esc(formatEvidence(e.threshold))}</small>`:''}${e.detail?`<small>${esc(e.detail)}</small>`:''}</div>`).join('');return `<article class="rec-card"><div class="rec-main"><div class="rec-top"><span class="category-pill">${esc(rec.category)}</span><span class="confidence ${esc(rec.confidence)}">${esc(rec.confidence)}</span><span class="rule-id">${esc(rec.rule_id)} · v${esc(rec.rule_version)}</span></div><h3>${esc(rec.title)}</h3><p>${esc(rec.suggested_action)}</p></div><div class="rec-savings"><span>EST. MONTHLY SAVINGS</span><strong>${money(rec.estimated_monthly_savings)}</strong><small>${esc(rec.savings_basis)} basis</small></div><div class="evidence-grid full">${evidence}</div>${rec.missing_signals?.length?`<div class="missing-box"><strong>Missing signals:</strong> ${esc(rec.missing_signals.join(', '))}</div>`:''}<p class="safety-note">${esc(rec.safety_note)}</p></article>`;}).join(''):`<div class="empty-state"><h3>No rule fired for this resource.</h3><p>That can be a healthy outcome or a data-quality limitation; inspect metric availability above.</p></div>`;
      root.className=''; root.innerHTML=`<div class="detail-grid"><div class="panel"><span class="eyebrow">RESOURCE</span><dl class="detail-list">${resourceRows}</dl></div><div class="panel"><span class="eyebrow">COST PROVENANCE</span><dl class="detail-list">${costRows}</dl><p class="small-note">Estimates are never relabeled as billed actual cost.</p></div></div>${tags?`<div class="tag-row">${tags}</div>`:''}<div class="panel chart-panel"><div class="panel-heading"><div><span class="eyebrow">METRICS</span><h2>Observed telemetry.</h2></div><div class="time-chips"><button data-window="7">7D</button><button class="active" data-window="14">14D</button><button data-window="30">30D</button></div></div><div id="resource-chart" class="chart"></div></div><div class="section-heading"><div><span class="eyebrow">TRIGGERED RULES</span><h2>Why this resource was flagged.</h2></div></div><div class="recommendation-list">${recHtml}</div>`;
      renderResourceChart(r.metrics);
    } catch(err){root.className='empty-state';root.innerHTML=`<span class="eyebrow">RESOURCE UNAVAILABLE</span><h3>${esc(err.message)}</h3><p>Return to the scan overview or start a new hosted demo.</p>`;}
  }

  document.addEventListener('DOMContentLoaded', () => {
    initBase();
    const page=document.body.dataset.page; const dynamic=document.body.dataset.dynamic;
    if(page==='home'&&!dynamic) initHome();
    if(page==='import') initImport();
    if(page==='aws') initHostedAws();
    if(dynamic==='scan') initScan();
    if(dynamic==='resource') initResource();
  });

  return {showModal, apiBase};
})();
