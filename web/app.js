/* YZU AI Center — demo console.
   No framework and no build step: one page, three files, served by FastAPI. */

import { mountMascot } from '/static/mascot.js';

const $ = id => document.getElementById(id);

/* ── i18n ─────────────────────────────────────────────────── */
const LANG = {
  en: {
    hello: "Hello, {name}", ask: "How can I assist you today?",
    welcomeDesc: "Ask about HPC compute applications, the service team and news — plus archived programs, courses and faculty. Every answer cites its source.",
    placeholder: "Ask about compute applications, programs, faculty…",
    newChat: "New chat", trace: "Trace", traceTitle: "Reasoning trace",
    traceEmpty: "Ask something — the intent, the routing decision, the tool chosen and every MCP call will appear here.",
    localOnly: "stored in this browser",
    samples: [
      "What do I need to apply for compute time?",
      "What credit programs does TAICA offer?",
      "What's the latest news from the centre?",
      "What's the weather like in Hsinchu today?"
    ],
    you: "you", askName: "What should I call you?", guest: "Guest",
    nameHint: "Used only for the greeting, and it stays in this browser.",
    namePlaceholder: "Your name",
    ok: "OK", cancel: "Cancel", save: "Save",
    delTitle: "Delete this conversation?",
    delText: "“{title}” will be removed permanently. This cannot be undone.",
    delOk: "Delete",
    today: "Today", yesterday: "Yesterday", last7: "Previous 7 days", older: "Older",
    noChats: "No conversations yet.",
    errEmpty: "Please enter a question first.",
    errFail: "Request failed: {e}. Check that the server is running.",
    viewTrace: "View reasoning trace",
    confirmDel: "Delete this conversation?",
    srcArchived: "From the site's previous version — that exact page is retired, "
      + "so this links to the centre's current site instead",
    srcGone: "No link is available for this source",
    srcUncited: "Retrieved, but the answer did not cite it",
    srcLive: "Source page"
  },
  zh: {
    hello: "你好，{name}", ask: "今天需要什麼協助？",
    welcomeDesc: "詢問算力申請、服務團隊與最新消息，以及封存的學程、課程與師資——每個答案都附上來源。",
    placeholder: "詢問算力申請、學程、課程、師資…",
    newChat: "新對話", trace: "推理軌跡", traceTitle: "推理軌跡",
    traceEmpty: "問一個問題——意圖判斷、路由決策、選用的工具與每一次 MCP 呼叫都會顯示在這裡。",
    localOnly: "僅儲存在此瀏覽器",
    samples: [
      "算力申請需要什麼條件？",
      "TAICA 有哪些學分學程？",
      "最近有什麼新消息？",
      "請問今天新竹的天氣如何？"
    ],
    you: "你", askName: "我該怎麼稱呼你？", guest: "訪客",
    nameHint: "僅用於問候語，只會儲存在這個瀏覽器中。",
    namePlaceholder: "你的名字",
    ok: "確定", cancel: "取消", save: "儲存",
    delTitle: "刪除這個對話？",
    delText: "「{title}」將被永久刪除，此操作無法復原。",
    delOk: "刪除",
    today: "今天", yesterday: "昨天", last7: "前 7 天", older: "更早",
    noChats: "還沒有對話。",
    errEmpty: "請先輸入問題。",
    errFail: "請求失敗：{e}。請確認伺服器已啟動。",
    viewTrace: "查看推理軌跡",
    confirmDel: "確定刪除這個對話？",
    srcArchived: "來自網站改版前的資料——原始頁面已下線，因此連結指向中心現行網站",
    srcGone: "此來源目前沒有可用連結",
    srcUncited: "已檢索，但答案未引用",
    srcLive: "來源頁面"
  }
};

/* localStorage can throw in a private window, and none of this is worth losing
   a working page over. */
const store = {
  get(k, fallback = null) { try { return localStorage.getItem(k) ?? fallback; } catch { return fallback; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* non-fatal */ } }
};

let lang = store.get('lang', 'en');
let userName = store.get('user_name', '');
let sessionId = store.get('session_id', '');
let traces = [];        // one entry per turn in the current session
const t = () => LANG[lang];

/* ── greeting ─────────────────────────────────────────────── */
function renderHello() {
  const name = userName || t().guest;
  const greeting = t().hello.replace('{name}', name);
  const el = $('hello');
  el.innerHTML = '';

  // Word-by-word so the greeting arrives rather than just appearing.
  const line = document.createElement('span');
  line.className = 'grad';
  greeting.split(' ').forEach((word, i) => {
    const s = document.createElement('span');
    s.className = 'w';
    s.textContent = word;
    s.style.animationDelay = `${i * 0.07}s`;
    line.append(s);
    if (i < greeting.split(' ').length - 1) line.append(document.createTextNode(' '));
  });

  const ask = document.createElement('span');
  ask.className = 'hello-ask w';
  ask.textContent = t().ask;
  ask.style.animationDelay = '0.22s';

  el.append(line, ask);
}

function applyLang() {
  store.set('lang', lang);
  document.documentElement.lang = lang === 'zh' ? 'zh-Hant' : 'en';
  $('lang-en').classList.toggle('active', lang === 'en');
  $('lang-zh').classList.toggle('active', lang === 'zh');

  document.querySelectorAll('[data-i18n]').forEach(el => {
    const v = t()[el.dataset.i18n];
    if (v) el.textContent = v;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const v = t()[el.dataset.i18nPlaceholder];
    if (v) el.placeholder = v;
  });

  renderHello();
  renderSamples();
  renderUser();
  loadSessions();
}

function renderSamples() {
  const box = $('samples');
  box.innerHTML = '';
  t().samples.forEach((s, i) => {
    const b = document.createElement('button');
    b.className = 'sample-btn';
    b.textContent = s;
    b.style.animationDelay = `${0.4 + i * 0.06}s`;
    b.onclick = () => { $('input').value = s; $('input').focus(); };
    box.append(b);
  });
}

function renderUser() {
  const name = userName || t().guest;
  $('userNameLabel').textContent = name;
  $('avatar').textContent = [...name][0]?.toUpperCase() ?? '?';
}

/* ── modal ────────────────────────────────────────────────── */
/* One <dialog> serves both prompts and confirmations. Going native buys focus
   trapping, Esc handling and an inert background that a hand-rolled overlay
   would have to reimplement — and usually reimplements badly.
   Resolves to a trimmed string or null for 'prompt', true/false for 'confirm'. */
const modal = $('modal');
let settleModal = null;

function finishModal(value) {
  if (!settleModal) return;
  const done = settleModal;
  settleModal = null;
  if (modal.open) modal.close();
  done(value);
}

const dismissValue = () => ($('modalInput').hidden ? false : null);

function openModal({ title, text = '', kind = 'confirm', value = '', ok, cancel, danger = false }) {
  return new Promise(resolve => {
    finishModal(dismissValue());   // never leave a previous caller hanging
    settleModal = resolve;

    $('modalTitle').textContent = title;
    $('modalText').textContent = text;
    $('modalText').hidden = !text;
    $('modalOk').textContent = ok || t().ok;
    $('modalCancel').textContent = cancel || t().cancel;
    modal.classList.toggle('danger', danger);

    const input = $('modalInput');
    input.hidden = kind !== 'prompt';
    input.value = value;
    input.placeholder = t().namePlaceholder;

    modal.showModal();
    if (kind === 'prompt') { input.focus(); input.select(); } else $('modalOk').focus();
  });
}

$('modalForm').addEventListener('submit', e => {
  e.preventDefault();
  const input = $('modalInput');
  finishModal(input.hidden ? true : input.value.trim());
});
$('modalCancel').onclick = () => finishModal(dismissValue());
// Esc fires 'cancel'; a click that lands on the dialog itself is the backdrop.
modal.addEventListener('cancel', e => { e.preventDefault(); finishModal(dismissValue()); });
modal.addEventListener('click', e => { if (e.target === modal) finishModal(dismissValue()); });

/* ── sessions ─────────────────────────────────────────────── */
async function newSessionId() {
  try {
    const r = await fetch('/api/sessions', { method: 'POST' });
    return (await r.json()).session_id;
  } catch {
    return 's-' + Math.random().toString(36).slice(2, 10);
  }
}

function groupOf(iso) {
  if (!iso) return 'older';
  const then = new Date(iso), now = new Date();
  const days = Math.floor((new Date(now.toDateString()) - new Date(then.toDateString())) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days <= 7) return 'last7';
  return 'older';
}

async function loadSessions() {
  let sessions = [];
  try {
    sessions = (await (await fetch('/api/sessions')).json()).sessions || [];
  } catch { /* the list is a convenience; the chat still works without it */ }

  const box = $('history');
  box.innerHTML = '';
  if (!sessions.length) {
    box.innerHTML = `<p class="history-empty">${t().noChats}</p>`;
    return;
  }

  const groups = { today: [], yesterday: [], last7: [], older: [] };
  sessions.forEach(s => groups[groupOf(s.updated_at)].push(s));

  for (const [key, items] of Object.entries(groups)) {
    if (!items.length) continue;
    const g = document.createElement('div');
    g.className = 'history-group';
    const label = document.createElement('div');
    label.className = 'history-label';
    label.textContent = t()[key === 'last7' ? 'last7' : key];
    g.append(label);

    items.forEach(s => {
      const row = document.createElement('button');
      row.className = 'history-item' + (s.session_id === sessionId ? ' active' : '');
      row.title = s.title;

      const title = document.createElement('span');
      title.className = 'history-title';
      title.textContent = s.title;

      const del = document.createElement('span');
      del.className = 'history-del';
      del.setAttribute('role', 'button');
      del.title = t().confirmDel;
      del.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14H6L5 6m5 0V4h4v2"></path></svg>';
      del.onclick = async e => {
        e.stopPropagation();
        const confirmed = await openModal({
          title: t().delTitle,
          text: t().delText.replace('{title}', s.title),
          ok: t().delOk,
          danger: true
        });
        if (!confirmed) return;
        await fetch(`/api/sessions/${s.session_id}`, { method: 'DELETE' });
        if (s.session_id === sessionId) await startNewChat();
        else loadSessions();
      };

      row.append(title, del);
      row.onclick = () => openSession(s.session_id);
      g.append(row);
    });
    box.append(g);
  }
}

async function openSession(id) {
  if (id === sessionId) return;
  sessionId = id;
  store.set('session_id', id);
  traces = [];
  renderTraces();

  let data = { turns: [] };
  try { data = await (await fetch(`/api/sessions/${id}`)).json(); } catch { /* show empty */ }

  const thread = $('thread');
  thread.innerHTML = '';
  if (!data.turns?.length) {
    showWelcome();
  } else {
    // Citations are persisted with the turn; the trace is not — it describes one
    // request, not the answer, so it exists only for live turns.
    data.turns.forEach(turn => addMessage(turn.role === 'user' ? 'user' : 'bot', turn.content,
      { citations: turn.citations, intent: turn.intent }));
  }
  loadSessions();
  $('input').focus();
  closeOverlaysOnMobile();
}

async function startNewChat() {
  sessionId = await newSessionId();
  store.set('session_id', sessionId);
  traces = [];
  renderTraces();
  $('thread').innerHTML = '';
  showWelcome();
  loadSessions();
  $('input').focus();
  closeOverlaysOnMobile();
}

/* ── mascot ───────────────────────────────────────────────── */
/* Knight, from the page-mascot library (github.com/nilbuild/page-mascot) —
   no React here, so mascot.js is a vanilla-JS port of its component; the
   sprite sheets in mascots/ are the package's own pre-drawn character.

   Two placements, never both on screen at once: the large hero knight sits in
   the empty-state welcome section, and a small one takes over in the bottom
   corner once the session has messages. Each tracks its own unmount function
   so switching between them (new chat, opening another session) can tear the
   old one down explicitly instead of leaning on window-listener self-cleanup. */
const KNIGHT_SHEETS = {
  directions: '/static/mascots/knight-directions.webp',
  reactions: '/static/mascots/knight-reactions.webp',
};
let heroMascotUnmount = null;
let cornerMascotUnmount = null;

function mountHeroMascot() {
  const slot = $('welcome')?.querySelector('.mascot-slot');
  if (!slot) return;
  heroMascotUnmount = mountMascot(slot, { ...KNIGHT_SHEETS, size: 120, label: 'knight' });
}

function mountCornerMascot() {
  const el = $('mascotCorner');
  if (!el || cornerMascotUnmount) return;   // already mounted
  el.hidden = false;
  cornerMascotUnmount = mountMascot(el, { ...KNIGHT_SHEETS, size: 76, label: 'knight' });
}

function unmountCornerMascot() {
  cornerMascotUnmount?.();
  cornerMascotUnmount = null;
  const el = $('mascotCorner');
  if (el) el.hidden = true;
}

function showWelcome() {
  unmountCornerMascot();
  heroMascotUnmount = null;   // its slot is rebuilt from scratch just below
  const s = document.createElement('section');
  s.className = 'welcome';
  s.id = 'welcome';
  s.innerHTML = `<div class="mascot-slot"></div>
    <h1 class="hello" id="hello"></h1>
    <p class="hello-sub">${t().welcomeDesc}</p>
    <div class="samples" id="samples"></div>`;
  $('thread').append(s);
  renderHello();
  renderSamples();
  mountHeroMascot();
}

/* ── messages ─────────────────────────────────────────────── */
/* Not just "remove the node if it's there": openSession() clears #thread with
   a blanket innerHTML = '' before ever calling this, so #welcome can already
   be gone by the time addMessage() calls it for the first restored turn. Both
   lines below are already idempotent, so this always runs in full rather than
   gating on $('welcome') existing — a guard there previously meant reopening a
   session with history left the corner mascot unmounted. */
function removeWelcome() {
  $('welcome')?.remove();
  heroMascotUnmount = null;
  mountCornerMascot();
}

function addMessage(who, text, opts = {}) {
  removeWelcome();
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + who + (opts.grounded === false ? ' ungrounded' : '');

  const label = document.createElement('div');
  label.className = 'label';
  label.textContent = who === 'user' ? t().you : (opts.intent || 'assistant');

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  wrap.append(label, bubble);

  if (opts.citations?.length) {
    const box = document.createElement('div');
    box.className = 'cites';
    opts.citations.forEach(c => {
      const name = c.title + (c.heading ? ' › ' + c.heading : '');
      const status = c.status || 'live';
      // Every citation resolves on the real site now — an "archived" source
      // links to the centre's current home page rather than the exact retired
      // page. c.url can still be empty defensively (nothing in the backend
      // produces that today), and an <a> with an empty href would silently
      // reload the console, reading as a broken link with extra steps — so an
      // empty url renders as a plain span, never a dead link.
      const linkable = !!c.url;
      const el = document.createElement(linkable ? 'a' : 'span');
      if (linkable) { el.href = c.url; el.target = '_blank'; el.rel = 'noopener'; }
      el.className = 'cite-chip'
        + (linkable ? ' ' + status : ' gone')
        + (c.cited === false ? ' uncited' : '');
      const why = linkable
        ? (status === 'archived' ? t().srcArchived : t().srcLive)
        : t().srcGone;
      el.title = name + ' — ' + why
        + (c.cited === false ? ' · ' + t().srcUncited : '')
        + (c.source_url ? '\n' + c.source_url : '');
      const n = document.createElement('span');
      n.className = 'n'; n.textContent = c.n;
      const lbl = document.createElement('span');
      lbl.className = 'cite-label';
      lbl.textContent = name;
      el.append(n, lbl);
      box.append(el);
    });
    wrap.append(box);
  }

  if (opts.trace?.length) {
    const idx = traces.length - 1;
    const btn = document.createElement('button');
    btn.className = 'msg-trace';
    btn.textContent = t().viewTrace;
    btn.onclick = () => { openTrace(); document.getElementById(`turn-${idx}`)?.scrollIntoView({ behavior: 'smooth' }); };
    wrap.append(btn);
  }

  $('thread').append(wrap);
  scrollDown();
  return bubble;
}

function scrollDown() {
  $('chatWrap').scrollTo({ top: $('chatWrap').scrollHeight, behavior: 'smooth' });
}

function showTyping() {
  removeWelcome();
  const wrap = document.createElement('div');
  wrap.className = 'msg bot';
  wrap.id = 'typing';
  wrap.innerHTML = `<div class="label">assistant</div>
    <div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>`;
  $('thread').append(wrap);
  scrollDown();
}
const removeTyping = () => $('typing')?.remove();

/* ── trace panel ──────────────────────────────────────────── */
function stepKind(stage) {
  if (stage.startsWith('intent')) return 'k-intent';
  if (stage.startsWith('router')) return 'k-router';
  if (stage.startsWith('subagent')) return 'k-subagent';
  if (stage.startsWith('tool')) return 'k-tool';
  if (stage.startsWith('mcp')) return 'k-mcp';
  return '';
}

/* Rendered generically from stage/detail/ms/payload, so a new pipeline stage
   shows up here without touching the UI. */
function renderTraces() {
  const body = $('traceBody');
  body.innerHTML = '';
  if (!traces.length) {
    body.innerHTML = `<p class="trace-empty">${t().traceEmpty}</p>`;
    return;
  }
  traces.forEach((turn, i) => {
    const box = document.createElement('div');
    box.className = 'trace-turn';
    box.id = `turn-${i}`;

    const q = document.createElement('div');
    q.className = 'trace-q';
    q.textContent = turn.question;
    box.append(q);

    if (turn.agents?.length) {
      const chips = document.createElement('div');
      chips.className = 'agent-chips';
      turn.agents.forEach(a => {
        const c = document.createElement('span');
        c.className = 'agent-chip';
        c.textContent = a;
        chips.append(c);
      });
      box.append(chips);
    }

    turn.trace.forEach(step => {
      const s = document.createElement('div');
      s.className = 'tstep ' + stepKind(step.stage);

      const head = document.createElement('div');
      head.className = 'tstep-head';
      const stage = document.createElement('span');
      stage.className = 'tstep-stage';
      stage.textContent = step.stage;
      const ms = document.createElement('span');
      ms.className = 'tstep-ms';
      ms.textContent = step.ms != null ? `${step.ms} ms` : '';
      head.append(stage, ms);
      s.append(head);

      if (step.detail) {
        const d = document.createElement('div');
        d.className = 'tstep-detail';
        d.textContent = step.detail;
        s.append(d);
      }

      if (step.payload && Object.keys(step.payload).length) {
        const det = document.createElement('details');
        const sum = document.createElement('summary');
        sum.textContent = 'payload';
        const pre = document.createElement('pre');
        pre.textContent = JSON.stringify(step.payload, null, 2);
        det.append(sum, pre);
        s.append(det);
      }
      box.append(s);
    });
    body.append(box);
  });
  body.scrollTop = body.scrollHeight;
}

const openTrace  = () => { $('app').classList.add('trace-open'); $('traceBtn').classList.add('on'); };
const closeTrace = () => { $('app').classList.remove('trace-open'); $('traceBtn').classList.remove('on'); };

function closeOverlaysOnMobile() {
  if (window.matchMedia('(max-width: 820px)').matches) {
    $('app').classList.add('sidebar-collapsed');
    closeTrace();
  }
}

/* ── send ─────────────────────────────────────────────────── */
/* A hard re-entrancy lock, checked before anything else touches the DOM or the
   network. `$('send').disabled` alone does not cover this: it is set after the
   text is read, so two calls to send() arriving close enough together — a key
   that auto-repeats, a duplicate event some environment fires, a click landing
   the same tick as an Enter — can both pass the disabled check before either
   has set it. `sending` is set as the very first statement, synchronously,
   before any `await`, so at most one call ever gets past it regardless of what
   triggered the extra calls. */
let sending = false;

async function send() {
  if (sending) return;
  const text = $('input').value.trim();
  if (!text) { $('err').textContent = t().errEmpty; $('input').focus(); return; }
  sending = true;
  $('err').textContent = '';
  $('input').value = '';
  $('send').disabled = true;

  const isFirst = !$('thread').querySelector('.msg');
  addMessage('user', text);
  showTyping();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId, lang })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    removeTyping();
    traces.push({ question: text, trace: data.trace || [], agents: data.agents || [] });
    renderTraces();
    addMessage('bot', data.answer, data);
    if (isFirst) loadSessions();      // the session now has a title to show
  } catch (e) {
    removeTyping();
    $('err').textContent = t().errFail.replace('{e}', e.message);
  } finally {
    sending = false;
    $('send').disabled = false;
    $('input').focus();
  }
}

/* ── status ───────────────────────────────────────────────── */
async function loadStatus() {
  try {
    const d = await (await fetch('/api/status')).json();
    const idx = d.index || {};
    const mode = (idx.mode || '').startsWith('hybrid') ? 'hybrid' : 'lexical';
    const corpus = (idx.live != null && idx.archived != null)
      ? ` · ${idx.live} live / ${idx.archived} archived`
      : '';
    $('status').textContent =
      `${d.transport} · ${d.tools.length} tools · ${idx.chunks ?? '?'} chunks · ${mode}${corpus}`;
    $('status').classList.toggle('degraded', mode !== 'hybrid');
  } catch {
    $('status').textContent = 'offline';
    $('status').classList.add('degraded');
  }
}

/* ── name ─────────────────────────────────────────────────── */
async function askName() {
  const entered = await openModal({
    kind: 'prompt',
    title: t().askName,
    text: t().nameHint,
    value: userName,
    ok: t().save
  });
  if (entered === null) return;      // cancelled; an empty string clears the name
  userName = entered.slice(0, 32);
  store.set('user_name', userName);
  renderUser();
  renderHello();
}

/* ── init ─────────────────────────────────────────────────── */
$('send').onclick = send;
$('input').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
$('input').addEventListener('input', () => { $('err').textContent = ''; });
$('lang-en').onclick = () => { lang = 'en'; applyLang(); };
$('lang-zh').onclick = () => { lang = 'zh'; applyLang(); };
$('newChat').onclick = startNewChat;
$('collapseBtn').onclick = () => { $('app').classList.add('sidebar-collapsed'); store.set('sidebar', 'closed'); };
$('expandBtn').onclick = () => { $('app').classList.remove('sidebar-collapsed'); store.set('sidebar', 'open'); };
$('traceBtn').onclick = () => $('app').classList.contains('trace-open') ? closeTrace() : openTrace();
$('traceClose').onclick = closeTrace;
$('scrim').onclick = () => { $('app').classList.add('sidebar-collapsed'); closeTrace(); };
$('userCard').onclick = askName;
$('userCard').addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); askName(); } });

(async function init() {
  if (store.get('sidebar') === 'closed' || window.matchMedia('(max-width: 820px)').matches) {
    $('app').classList.add('sidebar-collapsed');
  }
  if (!sessionId) {
    sessionId = await newSessionId();
    store.set('session_id', sessionId);
  }
  applyLang();
  loadStatus();

  // Restore the conversation this browser was last in.
  try {
    const data = await (await fetch(`/api/sessions/${sessionId}`)).json();
    if (data.turns?.length) {
      $('thread').innerHTML = '';
      data.turns.forEach(turn => addMessage(turn.role === 'user' ? 'user' : 'bot', turn.content,
        { citations: turn.citations, intent: turn.intent }));
    }
  } catch { /* a fresh session has no file yet */ }

  mountHeroMascot();   // for the hero that ships in index.html; a no-op once it is gone
  loadSessions();
  $('input').focus();
})();
