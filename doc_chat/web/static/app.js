'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  dark: true,
  streaming: false,
  messages: [],          // {role, content, sources}
  lastSources: [],       // [{source_path, source_name, metadata, text, similarity}]
  availableModels: [],
  chatModel: '',
  popoverData: null,
};

// ── DOM refs ───────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const $messages   = $('messages');
const $input      = $('question-input');
const $sendBtn    = $('send-btn');
const $statusPill = $('status-pill');
const $themeBtn   = $('theme-toggle');
const $sidebarBtn = $('sidebar-toggle');
const $sidebar    = $('sidebar');
const $popover    = $('popover');
const $indexBtn   = $('index-btn');
const $indexPath  = $('index-path');
const $modelSel   = $('model-select');

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadStatus();
  bindEvents();
});

function bindEvents() {
  $sendBtn.addEventListener('click', sendMessage);
  $input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  $input.addEventListener('input', () => {
    $input.style.height = 'auto';
    $input.style.height = Math.min($input.scrollHeight, 160) + 'px';
  });
  $themeBtn.addEventListener('click', toggleTheme);
  $sidebarBtn.addEventListener('click', toggleSidebar);
  $indexBtn.addEventListener('click', triggerIndex);
  $('popover-close').addEventListener('click', () => { $popover.style.display = 'none'; });
  $modelSel.addEventListener('change', () => { state.chatModel = $modelSel.value; });
}

// ── Status ─────────────────────────────────────────────────────────────────
async function loadStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();

    const connected = data.connected;
    $statusPill.className = 'pill ' + (connected ? 'pill-green' : 'pill-red');
    $statusPill.innerHTML = `<span class="dot"></span> ${connected ? 'connected' : 'disconnected'}`;

    const s = data.stats;
    $('stat-docs').textContent    = s.total_documents.toLocaleString();
    $('stat-chunks').textContent  = s.total_chunks.toLocaleString();
    $('stat-storage').textContent = s.storage_size_mb.toFixed(1) + ' MB';
    $('stat-last').textContent    = s.last_indexed
      ? new Date(s.last_indexed).toLocaleString(undefined, {dateStyle:'short', timeStyle:'short'})
      : '—';

    $('model-embed').textContent = data.models.embed_model || '—';
    state.availableModels = data.models.available || [];
    state.chatModel = data.models.chat_model || '';
    populateModelSelect();

    if (!connected) {
      addSystemMessage('⚠ Ollama is not running. Start it with: ollama serve');
    } else if (s.total_chunks === 0) {
      addSystemMessage('No documents indexed yet. Use the sidebar to index a folder, or run: doc-chat index ~/path');
    }
  } catch (err) {
    $statusPill.className = 'pill pill-red';
    $statusPill.innerHTML = '<span class="dot"></span> error';
    addSystemMessage('Cannot reach doc-chat server: ' + err.message);
  }
}

function populateModelSelect() {
  $modelSel.innerHTML = '';
  if (!state.availableModels.length) {
    const opt = document.createElement('option');
    opt.textContent = state.chatModel || '(none)';
    $modelSel.appendChild(opt);
    return;
  }
  state.availableModels.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m;
    if (m === state.chatModel) opt.selected = true;
    $modelSel.appendChild(opt);
  });
}

// ── Chat ───────────────────────────────────────────────────────────────────
function sendMessage() {
  if (state.streaming) return;
  const question = $input.value.trim();
  if (!question) return;

  $input.value = '';
  $input.style.height = 'auto';

  addUserMessage(question);
  fetchAnswer(question);
}

function addUserMessage(text) {
  const el = createBubble('user', text);
  $messages.appendChild(el);
  scrollToBottom();
}

function addSystemMessage(text) {
  const el = document.createElement('div');
  el.className = 'msg msg-assistant';
  el.innerHTML = `<div class="msg-bubble" style="border-color:var(--warning);color:var(--warning)">${escapeHtml(text)}</div>`;
  $messages.appendChild(el);
  scrollToBottom();
}

function createBubble(role, text) {
  const wrap = document.createElement('div');
  wrap.className = `msg msg-${role}`;
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = role === 'user' ? 'You' : 'Assistant';
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  if (role === 'user') {
    bubble.textContent = text;
  } else {
    bubble.innerHTML = renderMarkdown(text);
  }
  wrap.appendChild(label);
  wrap.appendChild(bubble);
  return wrap;
}

function fetchAnswer(question) {
  state.streaming = true;
  setInputEnabled(false);

  const wrap = document.createElement('div');
  wrap.className = 'msg msg-assistant';
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = 'Assistant';
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  const cursor = document.createElement('span');
  cursor.className = 'cursor';
  bubble.appendChild(cursor);
  wrap.appendChild(label);
  wrap.appendChild(bubble);
  $messages.appendChild(wrap);
  scrollToBottom();

  let accumulated = '';
  let sources = [];

  const body = JSON.stringify({
    question,
    n_results: 5,
    chat_model: state.chatModel || undefined,
  });

  fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  }).then(response => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    function read() {
      reader.read().then(({ done, value }) => {
        if (done) { finalize(); return; }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        lines.forEach(line => {
          if (!line.startsWith('data: ')) return;
          let evt;
          try { evt = JSON.parse(line.slice(6)); } catch { return; }
          handleEvent(evt);
        });
        scrollToBottom();
        read();
      }).catch(finalize);
    }

    function handleEvent(evt) {
      if (evt.type === 'retrieval') {
        sources = evt.chunks || [];
        state.lastSources = sources;
        updateSourcesSidebar(sources);
      } else if (evt.type === 'token') {
        accumulated += evt.token || '';
        bubble.innerHTML = renderMarkdown(accumulated);
        bubble.appendChild(cursor);
      } else if (evt.type === 'error') {
        accumulated += '\n\n⚠ ' + (evt.error || 'Unknown error');
        bubble.innerHTML = renderMarkdown(accumulated);
      } else if (evt.type === 'done') {
        finalize();
      }
    }

    function finalize() {
      cursor.remove();
      bubble.innerHTML = renderMarkdown(accumulated);
      if (sources.length) appendSourceBadges(wrap, sources);
      state.streaming = false;
      setInputEnabled(true);
      $input.focus();
      loadStatus();
    }

    read();
  }).catch(err => {
    cursor.remove();
    bubble.innerHTML = '<span style="color:var(--error)">Network error: ' + escapeHtml(err.message) + '</span>';
    state.streaming = false;
    setInputEnabled(true);
  });
}

function appendSourceBadges(msgEl, sources) {
  const seen = new Set();
  const unique = sources.filter(s => {
    if (seen.has(s.source_name)) return false;
    seen.add(s.source_name);
    return true;
  });

  const row = document.createElement('div');
  row.className = 'msg-sources';
  unique.forEach(src => {
    const badge = document.createElement('span');
    badge.className = 'source-badge';
    badge.textContent = src.source_name;
    badge.title = src.source_path;
    badge.addEventListener('click', () => showPopover(src));
    row.appendChild(badge);
  });
  msgEl.appendChild(row);
}

function showPopover(src) {
  $('popover-title').textContent = src.source_name;
  const meta = src.metadata || {};
  const parts = [];
  if (meta.page_number) parts.push(`Page ${meta.page_number}`);
  if (meta.line_start) parts.push(`Lines ${meta.line_start}–${meta.line_end || '?'}`);
  if (meta.function_or_class) parts.push(`def ${meta.function_or_class}`);
  parts.push(`Similarity: ${(src.similarity * 100).toFixed(0)}%`);
  $('popover-meta').textContent = parts.join(' · ');
  $('popover-text').textContent = src.text || '(no preview)';
  $popover.style.display = 'flex';
}

// ── Index ──────────────────────────────────────────────────────────────────
function triggerIndex() {
  const path = $indexPath.value.trim();
  if (!path) return;

  const $progress = $('index-progress');
  const $bar = $('progress-bar');
  const $lbl = $('progress-label');

  $progress.style.display = 'block';
  $bar.style.width = '0%';
  $lbl.textContent = 'Starting…';
  $indexBtn.disabled = true;

  fetch('/api/index', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  }).then(response => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    function read() {
      reader.read().then(({ done, value }) => {
        if (done) { finalize(null); return; }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        lines.forEach(line => {
          if (!line.startsWith('data: ')) return;
          let evt;
          try { evt = JSON.parse(line.slice(6)); } catch { return; }
          if (evt.type === 'progress') {
            $bar.style.width = evt.percent + '%';
            $lbl.textContent = evt.file ? `Indexing ${evt.file}…` : 'Indexing…';
          } else if (evt.type === 'done') {
            $bar.style.width = '100%';
            $lbl.textContent = `Done — ${evt.files_processed} files, ${evt.chunks_created} chunks`;
            finalize(null);
          } else if (evt.type === 'error') {
            $lbl.textContent = '⚠ ' + evt.error;
            finalize(null);
          }
        });
        read();
      }).catch(() => finalize(null));
    }

    function finalize() {
      $indexBtn.disabled = false;
      loadStatus();
    }
    read();
  }).catch(err => {
    $lbl.textContent = '⚠ ' + err.message;
    $indexBtn.disabled = false;
  });
}

// ── Sidebar & sources ──────────────────────────────────────────────────────
function updateSourcesSidebar(sources) {
  const $list = $('sources-list');
  if (!sources.length) { $list.innerHTML = '<span class="muted">—</span>'; return; }

  const seen = new Set();
  $list.innerHTML = '';
  sources.forEach(src => {
    if (seen.has(src.source_name)) return;
    seen.add(src.source_name);
    const item = document.createElement('div');
    item.className = 'source-item';
    item.textContent = src.source_name;
    item.title = src.source_path;
    item.addEventListener('click', () => showPopover(src));
    $list.appendChild(item);
  });
}

function toggleTheme() {
  state.dark = !state.dark;
  document.body.className = state.dark ? 'dark' : 'light';
  $themeBtn.textContent = state.dark ? '☀' : '☾';
}

function toggleSidebar() {
  $sidebar.classList.toggle('collapsed');
}

// ── Markdown renderer ──────────────────────────────────────────────────────
function renderMarkdown(text) {
  let html = escapeHtml(text);

  // code blocks
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
    `<pre><code class="lang-${lang}">${code.trimEnd()}</code></pre>`
  );
  // inline code
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  // headings
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
  // italic
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/_(.+?)_/g, '<em>$1</em>');
  // links
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>'
  );
  // unordered lists
  html = html.replace(/(^|\n)([ \t]*[-*] .+(\n[ \t]*[-*] .+)*)/g, (_, pre, block) => {
    const items = block.split('\n').filter(l => l.match(/^\s*[-*] /));
    return pre + '<ul>' + items.map(l => `<li>${l.replace(/^\s*[-*] /, '')}</li>`).join('') + '</ul>';
  });
  // ordered lists
  html = html.replace(/(^|\n)([ \t]*\d+\. .+(\n[ \t]*\d+\. .+)*)/g, (_, pre, block) => {
    const items = block.split('\n').filter(l => l.match(/^\s*\d+\. /));
    return pre + '<ol>' + items.map(l => `<li>${l.replace(/^\s*\d+\. /, '')}</li>`).join('') + '</ol>';
  });
  // blockquote
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  // paragraphs (double newline → paragraph break)
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = '<p>' + html + '</p>';
  // single newline → <br> within paragraphs
  html = html.replace(/([^>])\n([^<])/g, '$1<br>$2');
  // clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '');
  // don't wrap block elements in <p>
  html = html.replace(/<p>(<(?:pre|ul|ol|blockquote|h[1-6]))/g, '$1');
  html = html.replace(/(<\/(?:pre|ul|ol|blockquote|h[1-6])>)<\/p>/g, '$1');

  return html;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Helpers ────────────────────────────────────────────────────────────────
function setInputEnabled(enabled) {
  $input.disabled = !enabled;
  $sendBtn.disabled = !enabled;
}

function scrollToBottom() {
  $messages.scrollTop = $messages.scrollHeight;
}
