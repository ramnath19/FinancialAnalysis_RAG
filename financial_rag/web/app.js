/* Ledger: small, dependency-free UI. All remote text is rendered with textContent. */
'use strict';

const $ = (selector) => document.querySelector(selector);
const state = { busy: false, context: {}, turns: [], view: 'chat', viewController: null, companies: [] };
const titles = { chat: 'Ask your documents', ingest: 'Add company', lab: 'Chunk lab', eval: 'Evaluation', market: 'Market context' };
const SETTINGS_KEY = 'ledger.preferences.v1';
const settingsControls = ['corpus', 'mode', 'strategy', 'rerank', 'offline'];

function element(tag, className = '', text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setError(target, message = '') {
  target.textContent = message;
  target.hidden = !message;
}

async function api(path, { body, signal, timeout = 180000 } = {}) {
  const controller = new AbortController();
  const relay = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener('abort', relay, { once: true });
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {
      signal: controller.signal,
      ...(body !== undefined ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    });
    const data = await response.json();
    if (!response.ok) {
      const reference = data.request_id ? ` Request ID: ${data.request_id}` : '';
      throw new Error((data.error || 'The request failed. Please retry.') + reference);
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError' && !signal?.aborted) {
      throw new Error('The request timed out. The server may still be working. Check ingestion status before retrying a filing.');
    }
    if (error instanceof TypeError) throw new Error('Cannot reach the local server. Check that Ledger is running, then retry.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', relay);
  }
}

function preferences() {
  try {
    const value = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}

function savePreferences() {
  const value = { theme: document.documentElement.dataset.theme || 'light' };
  for (const id of settingsControls) value[id] = ['rerank', 'offline'].includes(id) ? $(`#${id}`).checked : $(`#${id}`).value;
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(value)); } catch { /* Private browsing may disable storage. */ }
}

function restorePreferences() {
  const saved = preferences();
  document.documentElement.dataset.theme = saved.theme === 'dark' ? 'dark' : 'light';
  for (const id of settingsControls.filter((id) => id !== 'corpus')) {
    const control = $(`#${id}`);
    if (['rerank', 'offline'].includes(id) && typeof saved[id] === 'boolean') control.checked = saved[id];
    if (control.tagName === 'SELECT' && [...control.options].some((option) => option.value === saved[id])) control.value = saved[id];
  }
}

function updateContext() {
  $('#context-chip').textContent = [...(state.context.tickers || []), state.context.year].filter(Boolean).join(' · ') || 'No company context';
}

function updateCount() { $('#character-count').textContent = `${$('#question').value.length} / 2000`; }

function locationLabel(metadata) {
  try {
    const location = JSON.parse(metadata.location_json || '{}');
    const pages = location.pdf_pages || (location.pdf_page ? [location.pdf_page] : []);
    return [location.section, pages.length ? `PDF page${pages.length > 1 ? 's' : ''} ${pages.join(', ')}` : ''].filter(Boolean).join(' · ') || 'Report passage';
  } catch { return 'Report passage'; }
}

function sourceCard(source) {
  const metadata = source.metadata || {};
  const card = element('details', 'source-card');
  const summary = element('summary');
  summary.append(element('span', 'citation', source.citation_id), element('span', 'source-title', metadata.company || metadata.document_id || 'Source'), element('span', 'source-location', locationLabel(metadata)));
  const body = element('div', 'source-body');
  body.append(element('p', 'source-year', `Report fiscal year: ${metadata.report_fiscal_year || '—'} · Comparative table columns may refer to other years.`), element('p', 'passage', source.text));
  try {
    const url = new URL(metadata.source_url);
    if (url.protocol === 'https:') {
      const link = element('a', 'source-link', 'Open original report ↗');
      Object.assign(link, { href: url.href, target: '_blank', rel: 'noopener noreferrer' });
      body.append(link);
    }
  } catch { /* A missing original URL does not hide the extracted evidence. */ }
  card.append(summary, body);
  return card;
}

function evidenceSection(sources) {
  const section = element('section');
  section.append(element('h3', 'evidence-heading', `Evidence · ${sources.length} sources`));
  const toolbar = element('div', 'evidence-toolbar');
  const search = element('input');
  search.type = 'search';
  search.placeholder = 'Search cited evidence…';
  search.setAttribute('aria-label', 'Filter cited evidence');
  const label = element('label', 'check-label');
  const expand = element('input');
  expand.type = 'checkbox';
  label.append(expand, document.createTextNode('Expand all'));
  toolbar.append(search, label);
  const cards = sources.map(sourceCard);
  const empty = element('p', 'answer-meta', 'No cited passages match your search.');
  empty.hidden = true;
  search.addEventListener('input', () => {
    const term = search.value.toLowerCase().trim();
    cards.forEach((card) => { card.hidden = !card.textContent.toLowerCase().includes(term); });
    empty.hidden = cards.some((card) => !card.hidden);
  });
  expand.addEventListener('change', () => cards.forEach((card) => { card.open = expand.checked; }));
  section.append(toolbar, ...cards, empty);
  return section;
}

function showResult(result) {
  const labels = { answered: 'Answer from your documents', excerpts: 'Source excerpts', clarify: 'A little more context', refused: 'Outside the selected scope', abstained: 'More evidence needed', unsupported: 'Choose an available chunking method' };
  const card = element('article', 'answer-card');
  card.tabIndex = -1;
  const heading = element('div', 'answer-heading');
  heading.append(element('span', 'answer-avatar', 'L'), element('strong', '', labels[result.answer_status] || 'Research result'), element('span', 'status-badge', result.answer_status));
  const copy = element('button', 'copy-answer', 'Copy answer');
  copy.type = 'button';
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(result.answer); copy.textContent = 'Copied'; }
    catch { copy.textContent = 'Select the text to copy'; }
    setTimeout(() => { copy.textContent = 'Copy answer'; }, 2500);
  };
  heading.append(copy);
  card.append(heading, element('div', 'answer-text', result.answer));
  card.append(element('p', 'answer-meta', `${result.strategy} chunks · Reranking ${result.reranking ? 'on' : 'off'} · ${Number(result.elapsed_seconds).toFixed(1)}s`));
  if (result.backend) card.append(element('p', 'answer-meta', result.backend));
  if (result.understood_as) card.append(element('p', 'answer-meta', `Interpreted as: ${result.understood_as}`));
  if (result.verification) card.append(element('p', 'answer-meta', result.verification.scope));
  if (result.trace?.length) {
    const trace = element('details', 'source-card');
    const list = element('ol', 'trace-list');
    trace.append(element('summary', '', 'Execution trail'));
    for (const step of result.trace) list.append(element('li', '', `${step.step}: ${step.detail}`));
    trace.append(list);
    card.append(trace);
  }
  if (result.sources?.length) card.append(evidenceSection(result.sources));
  if (result.available_strategies?.length) {
    const actions = element('div', 'answer-suggestions');
    for (const strategy of result.available_strategies) {
      const button = element('button', '', `Retry with ${strategy} chunks`);
      button.type = 'button';
      button.onclick = () => { $('#strategy').value = strategy; savePreferences(); $('#question').value = result.question; updateCount(); $('#ask-form').requestSubmit(); };
      actions.append(button);
    }
    card.append(actions);
  }
  if (result.suggested_questions?.length) {
    const suggestions = element('div', 'answer-suggestions');
    for (const question of result.suggested_questions) {
      const button = element('button', '', question);
      button.type = 'button';
      button.onclick = () => { $('#question').value = question; updateCount(); $('#ask-form').requestSubmit(); };
      suggestions.append(button);
    }
    card.append(suggestions);
  }
  if (result.request_id) {
    const diagnostics = element('details', 'answer-diagnostics');
    diagnostics.append(element('summary', '', 'Request details'), element('p', 'answer-meta', `Request ID: ${result.request_id}`));
    card.append(diagnostics);
  }
  $('#messages').append(card);
  return card;
}

async function sendQuestion(event) {
  event.preventDefault();
  const question = $('#question').value.trim();
  if (state.busy || !question) return;
  state.busy = true;
  setError($('#error'));
  $('#welcome').hidden = true;
  $('#messages').append(element('div', 'user-question', question));
  $('#question').value = '';
  updateCount();
  $('#submit').disabled = true;
  $('#submit').textContent = 'Reading documents…';
  $('#ask-form').setAttribute('aria-busy', 'true');
  let responseCard;
  const pending = element('p', 'pending', 'Retrieving evidence and preparing your response…');
  $('#messages').append(pending);
  try {
    const result = await api('/api/ask', { body: {
      question, strategy: $('#strategy').value, rerank: $('#rerank').checked,
      mode: $('#mode').value, selector: $('#corpus').value, offline: $('#offline').checked, context: state.context,
    } });
    if (typeof result.answer !== 'string' || !result.answer.trim()) throw new Error('The server returned no answer text. Please retry. Request ID: ' + (result.request_id || 'unavailable'));
    state.context = result.context || state.context;
    state.turns.push({ question, ...result });
    updateContext();
    responseCard = showResult(result);
    $('#conversation-tools').hidden = false;
  } catch (error) {
    setError($('#error'), error.message);
    $('#question').value = question;
    updateCount();
  } finally {
    pending.remove();
    state.busy = false;
    $('#submit').disabled = false;
    $('#submit').textContent = 'Ask Ledger ↑';
    $('#ask-form').setAttribute('aria-busy', 'false');
    if (state.view === 'chat') {
      $('#question').focus({ preventScroll: true });
      if (responseCard) responseCard.scrollIntoView({ behavior: 'auto', block: 'start' });
      else $('#error').scrollIntoView({ behavior: 'auto', block: 'nearest' });
    }
  }
}

async function refreshStatus() {
  const status = await api('/api/status', { timeout: 15000 });
  state.companies = status.companies;
  $('#connection').textContent = status.services.generation ? 'Nebius configured · local mode ready' : 'Local excerpts available';
  $('#document-count').textContent = `${status.documents} documents in your collection`;
  $('#company-count').textContent = `${status.companies.length} companies. One workspace.`;
  const select = $('#corpus');
  const chosen = select.value;
  while (select.options.length > 2) select.remove(2);
  $('#company-list').replaceChildren();
  for (const company of status.companies) {
    const option = element('option', '', `${company.ticker} · ${company.name}`);
    option.value = company.ticker;
    select.append(option);
    const row = element('div', 'company');
    row.append(element('b', '', company.ticker[0]), element('span', '', company.name));
    $('#company-list').append(row);
  }
  const desired = preferences().corpus || chosen;
  select.value = [...select.options].some((option) => option.value === desired) ? desired : 'active';
  const messages = [];
  if (!status.services.generation) messages.push('Generation is not configured. Ledger will return source excerpts.');
  if (!status.services.dense_retrieval) messages.push('Dense retrieval is not configured; local lexical retrieval is available.');
  $('#notice').textContent = messages.join(' ');
  $('#notice').hidden = !messages.length;
  updateStrategyAvailability();
  $('#status-dot').classList.remove('unavailable');
  return status;
}

function updateStrategyAvailability() {
  const company = state.companies.find((item) => item.ticker === $('#corpus').value);
  const options = [...$('#strategy').options];
  for (const option of options) option.disabled = Boolean(company && !company.strategies.includes(option.value));
  const help = $('#strategy-help');
  help.hidden = !company || company.strategies.length === options.length;
  if (company && !help.hidden) {
    help.textContent = `${company.ticker} has ${company.strategies.join(' and ')} chunks. Semantic chunking has not been generated for this filing.`;
    if (options.find((option) => option.value === $('#strategy').value)?.disabled) {
      $('#strategy').value = company.strategies[0] || 'fixed';
      help.textContent += ` Selected ${$('#strategy').value} instead.`;
      savePreferences();
    }
  }
}

function panelHeading(title, introduction) {
  const heading = element('h2', '', title);
  heading.id = 'tool-heading';
  heading.tabIndex = -1;
  $('#tools-panel').replaceChildren(heading, element('p', 'panel-intro', introduction));
}

function table(headers, rows, caption) {
  const wrapper = element('div', 'table-scroll');
  const result = element('table', 'metrics');
  result.append(element('caption', '', caption));
  const head = element('thead');
  const heading = element('tr');
  for (const title of headers) {
    const cell = element('th', '', title);
    cell.scope = 'col';
    heading.append(cell);
  }
  head.append(heading);
  const body = element('tbody');
  for (const row of rows) {
    const tr = element('tr');
    for (const value of row) tr.append(element('td', '', value));
    body.append(tr);
  }
  result.append(head, body);
  wrapper.append(result);
  return wrapper;
}

async function evaluationView(signal) {
  panelHeading('Evaluate the evidence', 'Compare the saved answer benchmark with the separate local retrieval experiment. These measure different systems and outcomes.');
  const data = await api('/api/evaluation', { signal });
  if (data.local_retrieval) {
    const report = data.local_retrieval;
    $('#tools-panel').append(element('p', 'answer-meta', report.scope));
    $('#tools-panel').append(table(['Chunking', 'Retrieval', 'Rerank', 'Hit@1', 'Hit@5', 'MRR@10'], report.rows.map((row) => [
      row.strategy, row.mode, row.rerank ? 'On' : 'Off', row.hit_at_1.toFixed(3), row.hit_at_5.toFixed(3), row.mrr_at_10.toFixed(3),
    ]), 'Six-way local retrieval · development questions'));
  }
  const report = element('details', 'source-card');
  report.append(element('summary', '', 'Original Pinecone answer comparison · full report'), element('pre', 'report', data.report));
  $('#tools-panel').append(report);
}

async function chunkView(signal) {
  panelHeading('Inspect your chunks', 'Compare bundled chunk lengths and inspect source boundaries. Chunk counts alone do not establish retrieval quality.');
  const results = await Promise.all(['fixed', 'semantic', 'section'].map((strategy) => api(`/api/chunks?strategy=${strategy}`, { signal })));
  for (const data of results) {
    const details = element('details', 'source-card');
    details.append(element('summary', '', `${data.strategy} · ${data.count.toLocaleString()} chunks · ${data.mean_characters.toLocaleString()} average characters`));
    details.append(element('p', 'source-body answer-meta', `Maximum length: ${data.max_characters.toLocaleString()} characters. Showing ${data.samples.length} sample chunks.`));
    for (const sample of data.samples) details.append(element('pre', 'report', `${sample.company} · ${JSON.stringify(sample.location)}\n\n${sample.text}`));
    $('#tools-panel').append(details);
  }
}

function tickerForm(buttonText, initial = '') {
  const form = element('form', 'tool-form');
  const label = element('label', '', 'Company ticker');
  const input = element('input');
  Object.assign(input, { value: initial, placeholder: 'e.g. TSLA', maxLength: 10, required: true, pattern: '[A-Za-z][A-Za-z0-9.\\-]{0,9}' });
  input.autocomplete = 'off';
  label.append(input);
  const button = element('button', '', buttonText);
  button.type = 'submit';
  form.append(label, button);
  return { form, input, button };
}

function jobCard(job) {
  const card = element('div', 'job-card');
  card.setAttribute('role', 'status');
  card.append(element('strong', '', `${job.ticker || 'Company'} · ${job.stage}`));
  const progress = element('progress');
  progress.max = 100;
  progress.value = job.progress;
  progress.setAttribute('aria-label', `${job.ticker || 'Company'} ingestion progress`);
  card.append(progress, element('p', 'answer-meta', `${job.progress}% · ${job.status}`));
  if (job.error) card.append(element('p', 'panel-error', job.error));
  return card;
}

async function ingestionView(signal) {
  panelHeading('Grow your research collection', 'Add or refresh the latest recent SEC 10-K. Filings remain separate from the bundled benchmark and use local fixed-size or section-aware retrieval.');
  const { form, input, button } = tickerForm('Fetch latest filing');
  const output = element('div');
  const errors = element('p', 'panel-error');
  errors.setAttribute('role', 'alert');
  errors.hidden = true;
  $('#tools-panel').append(form, errors, output);
  let following = false;
  async function poll() {
    if (following) return;
    following = true;
    try {
      while (!signal.aborted) {
        const { jobs } = await api('/api/jobs', { signal, timeout: 15000 });
        output.replaceChildren(...jobs.slice(-5).reverse().map(jobCard));
        const running = jobs.some((job) => job.status === 'running');
        button.disabled = running;
        if (!running) {
          await refreshStatus();
          break;
        }
        await new Promise((resolve) => {
          const done = () => { clearTimeout(timer); signal.removeEventListener('abort', done); resolve(); };
          const timer = setTimeout(done, 1500);
          signal.addEventListener('abort', done, { once: true });
        });
      }
    } catch (error) {
      if (!signal.aborted) setError(errors, error.message);
    } finally {
      following = false;
    }
  }
  form.onsubmit = async (event) => {
    event.preventDefault();
    button.disabled = true;
    setError(errors);
    try {
      const job = await api('/api/ingest', { body: { ticker: input.value.trim().toUpperCase() }, signal });
      output.replaceChildren(jobCard(job));
      await poll();
    } catch (error) {
      if (!signal.aborted) setError(errors, error.message);
    } finally {
      button.disabled = false;
    }
  };
  $('#tools-panel').setAttribute('aria-busy', 'false');
  await poll();
}

function marketChart(data) {
  const values = data.rows.map((row) => row.close);
  const low = Math.min(...values), high = Math.max(...values);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 600 180');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `${data.ticker} delayed closing prices from ${data.rows[0].date} to ${data.as_of}; range ${low} to ${high} ${data.currency || ''}`);
  const line = document.createElementNS(svg.namespaceURI, 'polyline');
  line.setAttribute('points', values.map((value, index) => `${10 + index * 580 / Math.max(1, values.length - 1)},${160 - (value - low) * 140 / Math.max(.01, high - low)}`).join(' '));
  line.setAttribute('class', 'chart-line');
  svg.append(line);
  return svg;
}

async function marketView(signal) {
  panelHeading('Market context', 'Optional delayed observations from external providers. These are kept separate from filing answers and evaluation.');
  const { form, input, button } = tickerForm('Load price history', state.context.tickers?.[0] || 'AAPL');
  const output = element('div');
  $('#tools-panel').append(form, output);
  form.onsubmit = async (event) => {
    event.preventDefault();
    button.disabled = true;
    output.replaceChildren(element('p', 'pending', 'Fetching delayed provider data…'));
    try {
      const data = await api(`/api/market?ticker=${encodeURIComponent(input.value.trim())}`, { signal, timeout: 35000 });
      output.replaceChildren();
      if (!data.available) {
        output.append(element('p', 'notice', data.message || 'Market observations unavailable.'));
        return;
      }
      output.append(element('p', 'answer-meta', `${data.ticker} · ${data.currency || 'Currency unspecified'} · ${data.source} · as of ${data.as_of} · delayed`), marketChart(data));
      const format = (number) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(number);
      output.append(element('p', 'chart-summary', `Latest close: ${format(data.rows.at(-1).close)} ${data.currency || ''}. ${data.rows[0].date} — ${data.as_of}. Cached for up to ${data.cache_seconds / 60} minutes.`));
      const records = element('details', 'source-card');
      records.append(element('summary', '', `View ${data.rows.length} observations`), table(['Date', 'Closing price'], data.rows.slice().reverse().map((row) => [row.date, format(row.close)]), 'Delayed daily closing prices'));
      output.append(records);
    } catch (error) {
      if (!signal.aborted) output.replaceChildren(element('p', 'panel-error', error.message));
    } finally {
      button.disabled = false;
    }
  };
}

async function navigate(view) {
  state.viewController?.abort();
  state.viewController = new AbortController();
  const { signal } = state.viewController;
  state.view = view;
  $('#view-title').textContent = titles[view];
  $('#chat-view').hidden = view !== 'chat';
  $('#tools-panel').hidden = view === 'chat';
  for (const button of document.querySelectorAll('[data-view]')) {
    if (button.dataset.view === view) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (view === 'chat') return;
  panelHeading(titles[view], 'Loading workspace…');
  $('#tools-panel').setAttribute('aria-busy', 'true');
  try {
    await ({ ingest: ingestionView, lab: chunkView, eval: evaluationView, market: marketView })[view](signal);
  } catch (error) {
    if (!signal.aborted) {
      const message = element('p', 'panel-error', error.message);
      message.setAttribute('role', 'alert');
      const retry = element('button', '', 'Retry loading');
      retry.onclick = () => navigate(view);
      $('#tools-panel').append(message, retry);
    }
  } finally {
    if (!signal.aborted) $('#tools-panel').setAttribute('aria-busy', 'false');
  }
}

function downloadConversation() {
  const lines = ['# Ledger research conversation', '', 'Check cited originals before relying on financial figures.', ''];
  for (const turn of state.turns) {
    lines.push(`## ${turn.question}`, '', turn.answer, '', `Mode: ${turn.strategy}; status: ${turn.answer_status}; request: ${turn.request_id || '—'}`, '');
    for (const source of turn.sources || []) lines.push(`[${source.citation_id}] ${source.metadata.company || ''} · ${locationLabel(source.metadata)} · ${source.metadata.source_url || ''}`, '');
  }
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }));
  const link = element('a');
  link.href = url;
  link.download = 'ledger-conversation.md';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

restorePreferences();
$('#ask-form').addEventListener('submit', sendQuestion);
$('#question').addEventListener('input', updateCount);
$('#question').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('#ask-form').requestSubmit(); }
});
for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => navigate(button.dataset.view));
for (const button of document.querySelectorAll('.example')) button.addEventListener('click', () => { $('#question').value = button.dataset.question; updateCount(); $('#question').focus(); });
for (const id of settingsControls) $(`#${id}`).addEventListener('change', savePreferences);
$('#corpus').addEventListener('change', () => { state.context = {}; updateContext(); updateStrategyAvailability(); });
$('#clear').addEventListener('click', () => {
  if (state.busy) return;
  state.context = {};
  state.turns = [];
  updateContext();
  $('#messages').replaceChildren();
  $('#welcome').hidden = false;
  $('#conversation-tools').hidden = true;
  setError($('#error'));
  $('#question').value = '';
  updateCount();
  $('#question').focus();
});
$('#export').addEventListener('click', downloadConversation);
$('#theme').addEventListener('click', () => {
  document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  savePreferences();
});
refreshStatus().catch((error) => {
  $('#connection').textContent = 'Service status unavailable';
  $('#status-dot').classList.add('unavailable');
  $('#notice').textContent = error.message;
  $('#notice').hidden = false;
});
