"use strict";
const $ = (id) => document.getElementById(id);
let currentRun = null;
let ws = null;
const RUN_MSG = {};   // run_id -> DOM-элемент сообщения assistant

const ST_ICON = { queued: "•", running: "◐", done: "✓", error: "✕", pending_template: "□" };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
function setPill(ok, text) { const p = $("pill"); p.textContent = text; p.className = "pill " + (ok ? "on" : "off"); }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

async function loadHealth() { try { await api("/health"); setPill(true, "online"); } catch (e) { setPill(false, "offline"); } }
async function loadOntology() {
  try {
    const s = await api("/api/ontology");
    $("onto").innerHTML = Object.entries(s).map(([k, v]) => `<div class="k">${k}</div><div class="v">${v}</div>`).join("");
  } catch (e) { $("onto").textContent = String(e); }
}

// ---------- чат ----------
function addMessage(role, text, extra = {}) {
  const el = document.createElement("div");
  el.className = "msg " + role;
  el.dataset.run = extra.run_id || "";
  const who = role === "user" ? "Вы" : "Оркестратор";
  el.innerHTML =
    `<div class="av">${role === "user" ? "🧑" : "🛠"}</div>
     <div class="bubble"><div class="who">${who}</div>
       <div class="txt">${esc(text)}</div>
       <details class="reason"><summary>Рассуждения</summary><pre class="rsn">—</pre></details>
       <div class="status"></div>
       <ul class="suggest"></ul>
       <div class="openbox"></div>
     </div>`;
  $("messages").appendChild(el);
  $("messages").scrollTop = $("messages").scrollHeight;
  if (extra.run_id) RUN_MSG[extra.run_id] = el;
  return el;
}
function msgBubble(runId) { const el = RUN_MSG[runId]; return el ? el.querySelector(".bubble") : null; }

function updateAssistant(rec) {
  const b = msgBubble(rec.run_id); if (!b) return;
  if (rec.reasoning) b.querySelector(".rsn").textContent = rec.reasoning;
  if (rec.reply) b.querySelector(".txt").textContent = rec.reply;
  const ma = (rec.result || {}).model_artifacts || {};   // task-17: где лежит модель
  b.querySelector(".status").textContent = `${rec.status}` +
    (rec.ensemble_size ? ` · ансамбль ${rec.ensemble_size}` : "") +
    (ma.dir ? ` · модель сохранена: ${ma.dir}` : "") +
    (rec.error ? ` · ${rec.error}` : "");
  b.querySelector(".suggest").innerHTML = (rec.suggestions || []).map(x => `<li>${esc(x)}</li>`).join("");
  const ob = b.querySelector(".openbox");
  const proj = (rec.result || {}).project || {};
  if (proj.ensemble && (proj.ensemble.branches || []).length) {
    ob.innerHTML = `<button class="mbtn" onclick="openProject('${rec.run_id}','base')">Открыть проект в тНаве</button>`;
  }
}

async function loadChat() {
  try {
    const msgs = await api("/api/chat");
    $("messages").innerHTML = "";
    let lastRun = null;
    for (const m of msgs) {
      const role = m.role === "user" ? "user" : "assistant";
      const el = addMessage(role, m.text, { run_id: m.run_id });
      if (m.reasoning) el.querySelector(".rsn").textContent = m.reasoning;
      if (m.run_id) lastRun = m.run_id;
    }
    if (lastRun) openRun(lastRun);      // WS+поллинг: статусы живут и после перезагрузки
  } catch (e) { /* ignore */ }
}

async function doSend() {
  const text = $("message").value.trim();
  if (!text) return;
  const field = $("field").value.trim();
  $("message").value = "";
  addMessage("user", text);
  const el = addMessage("assistant", "…");
  try {
    const res = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, field, execute: $("execute").checked }) });
    el.querySelector(".txt").textContent = res.reply || res.mode;
    if (res.reasoning) el.querySelector(".rsn").textContent = res.reasoning;
    if (res.run_id) { el.dataset.run = res.run_id; RUN_MSG[res.run_id] = el; openRun(res.run_id); }
    if (res.mode === "clarify" && /реализац/i.test(res.reply || "")) addQuickNumbers(el);
  } catch (e) { el.querySelector(".txt").textContent = "Ошибка: " + e; }
}

function addQuickNumbers(msgEl) {
  const box = document.createElement("div");
  box.className = "quick";
  [2, 4, 8, 16].forEach(n => {
    const b = document.createElement("button");
    b.className = "mbtn";
    b.textContent = `${n} моделей`;
    b.onclick = () => { $("ensemble").value = n; doRun(); };
    box.appendChild(b);
  });
  msgEl.querySelector(".bubble").appendChild(box);
}

// ---------- детерминированный запуск прогона (без LLM) ----------
async function doRun() {
  const field = $("field").value.trim();
  const execute = $("execute").checked;
  const n = Math.max(0, Math.min(32, parseInt($("ensemble").value || "0", 10) || 0));
  addMessage("user", `запуск прогона: ${field}${n ? `, ансамбль ${n}` : ""}`
    + (execute ? ", реальный тНав" : ", dry-run"));
  const el = addMessage("assistant", "ставлю в очередь…");
  try {
    const res = await api("/api/runs", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field, execute, ensemble_size: n }) });
    el.querySelector(".txt").textContent = res.reply || "прогон запущен";
    el.dataset.run = res.run_id;
    RUN_MSG[res.run_id] = el;
    openRun(res.run_id);
  } catch (e) { el.querySelector(".txt").textContent = "Ошибка запуска: " + e; }
}

// ---------- живой прогон ----------
let pollTimer = null, lastWsTs = 0;

function openRun(runId, wsConnect = true) {
  currentRun = runId;
  if (!wsConnect) return;
  if (ws) { try { ws.close(); } catch (e) {} }
  lastWsTs = Date.now();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/api/runs/${runId}/events`);
  ws.onmessage = (ev) => { lastWsTs = Date.now(); applyRecord(JSON.parse(ev.data)); };
  startPolling(runId);
}

function startPolling(runId) {
  stopPolling();
  pollTimer = setInterval(async () => {
    if (currentRun !== runId) { stopPolling(); return; }
    if (Date.now() - lastWsTs < 3000) return;      // WS живой — дублировать не нужно
    try {
      const rec = await api(`/api/runs/${runId}`);
      applyRecord(rec);
      if (rec.status === "done" || rec.status === "error") stopPolling();
    } catch (e) { /* сеть недоступна — повторим позже */ }
  }, 2000);
}

function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

function applyRecord(rec) {
  renderSteps(rec); renderProject(rec); renderEnsemble(rec); renderLog(rec);
  renderRunGates(rec); updateAssistant(rec); renderProgress(rec); renderMaps(rec);
  renderMapset(rec);
}

function renderSteps(rec) {
  const steps = rec.steps || [];
  const total = steps.length || 1;
  const done = steps.filter(s => s.status === "done").length;
  const err = steps.filter(s => s.status === "error").length;
  const pend = steps.filter(s => s.status === "pending_template").length;
  $("bar").style.width = Math.round(100 * done / total) + "%";
  $("stats").textContent = `${steps.length} шагов · готово ${done} · ошибок ${err} · нет шаблона ${pend}`;
  if (!steps.length) { $("steps").innerHTML = `<span class="mono empty">—</span>`; return; }
  const byStage = {};
  for (const s of steps) (byStage[s.stage] ||= []).push(s);
  $("steps").innerHTML = Object.entries(byStage).map(([stage, list]) => {
    const ok = list.filter(x => x.status === "done").length;
    const rows = list.map(s => `<div class="step ${s.status}">
        <span class="ic">${ST_ICON[s.status] || "?"}</span>
        <span class="fn mono">${esc(s.function)}</span>
        ${s.object ? `<span class="obj">→ ${esc(s.object)}</span>` : ""}
        <span class="msg mono">${esc(s.message || "")}</span></div>`).join("");
    return `<div class="stage"><div class="stage-h">${esc(stage)} <span class="mono">${ok}/${list.length}</span></div>${rows}</div>`;
  }).join("");
}

function renderLog(rec) { $("log").textContent = (rec.log || []).join("\n"); }

// ---------- прогресс прогона ----------
const PHASE_RU = { plan: "подготовка", data: "данные", render: "рендер этапов",
                   stage: "этап", execute: "тНав: исполнение", gate: "вердикт гейта",
                   qa: "QA/QC", ensemble: "ансамбль", done: "завершено", error: "ошибка" };

function renderProgress(rec) {
  const p = rec.progress || {};
  const phase = p.phase || (rec.status === "running" ? "ожидание" : "—");
  const pct = Number.isFinite(p.percent) ? p.percent : 0;
  $("pbar").style.width = Math.max(0, Math.min(100, pct)) + "%";
  $("phaseName").textContent = (PHASE_RU[phase] || phase) +
    (p.total ? ` ${p.index || 0}/${p.total}` : "");
  const started = rec.created_at ? Date.parse(rec.created_at) : NaN;
  const sec = Number.isFinite(started) ? Math.max(0, Math.round((Date.now() - started) / 1000)) : null;
  const elapsed = sec == null ? "" : ` · ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  // решение структурного агента (врез строится/не требуется) — из отчёта прогона
  const er = (((rec.result || {}).structural || {}).erosion) || null;
  let erTxt = "";
  if (er) {
    const cov = er.coverage != null ? `, отбивок ${Math.round(er.coverage * 100)}%` : "";
    erTxt = ` · структурный агент (${er.top_marker || "?"}): ` +
      `${er.enabled ? "врез строится" : "врез не требуется"}${cov}`;
  }
  $("phaseInfo").textContent = `${rec.status}${elapsed}${p.detail ? " · " + p.detail : ""}${erTxt}`;
}

// ---------- карты прогона (PNG из тНава/фолбэка) ----------
const MAPS_FETCHED = new Set();

function paintMaps(runId, list) {
  $("mapsRun").textContent = runId;
  $("maps").innerHTML = list.map(m => `<figure class="map">
      <img src="/api/runs/${runId}/maps/${encodeURIComponent(m.file)}"
           alt="${esc(m.name)}" loading="lazy"/>
      <figcaption>${esc(m.name)}</figcaption></figure>`).join("");
}

async function renderMaps(rec) {
  const runId = rec.run_id;
  if ((rec.maps || []).length) { paintMaps(runId, rec.maps); return; }
  if (rec.status !== "done" || MAPS_FETCHED.has(runId)) return;
  MAPS_FETCHED.add(runId);
  try {
    const res = await api(`/api/runs/${runId}/maps`);
    if ((res.maps || []).length) paintMaps(runId, res.maps);
  } catch (e) { /* карт может не быть — не ошибка */ }
}

// ---------- карты по версиям (структура + фации на каждую ветку) ----------
const MAPSET_FETCHED = new Set();
let mapsetCache = null;        // {runId, kinds, versions}
let currentVersion = "base";   // активная вкладка версии

const KIND_RU = { structural: "Структурные карты", facies: "Карты фаций", other: "Прочие карты" };

function renderMapsetTabs() {
  const vers = (mapsetCache || {}).versions || [];
  $("verTabs").innerHTML = vers.map(v =>
    `<button class="vtab ${v.id === currentVersion ? "on" : ""}"
       onclick="selectVersion('${esc(v.id)}')">${esc(v.id)}${v.label ? " · " + esc(v.label) : ""}</button>`
  ).join("") || `<span class="mono empty">нет версий с картами</span>`;
}

function renderMapsetGroup(runId, version, kind, maps) {
  const items = maps.filter(m => m.kind === kind);
  if (!items.length) return "";
  const figs = items.map(m => `<figure class="map">
      <img src="/api/runs/${runId}/mapset/${encodeURIComponent(version)}/${encodeURIComponent(m.file)}"
           alt="${esc(m.name)}" loading="lazy"/>
      <figcaption>${esc(m.name)}</figcaption></figure>`).join("");
  return `<div class="mapgroup"><h3>${esc(KIND_RU[kind] || kind)}</h3>
    <div class="maps">${figs}</div></div>`;
}

function paintMapset() {
  const vers = (mapsetCache || {}).versions || [];
  if (!vers.length) {
    $("mapset").innerHTML = `<span class="mono empty">нет карт версий (нужен реальный прогон с экспортом карт)</span>`;
    renderMapsetTabs();
    return;
  }
  if (!vers.some(v => v.id === currentVersion)) currentVersion = vers[0].id;
  renderMapsetTabs();
  const runId = mapsetCache.runId;
  const v = vers.find(x => x.id === currentVersion);
  const kinds = ["structural", "facies", "other"];
  $("mapset").innerHTML = kinds.map(k => renderMapsetGroup(runId, v.id, k, v.maps)).join("")
    || `<span class="mono empty">у версии «${esc(v.id)}» нет карт</span>`;
}

function selectVersion(vid) { currentVersion = vid; paintMapset(); }

async function renderMapset(rec) {
  const runId = rec.run_id;
  if (rec.status !== "done" || MAPSET_FETCHED.has(runId)) {
    if (mapsetCache && mapsetCache.runId === runId) paintMapset();
    return;
  }
  MAPSET_FETCHED.add(runId);
  try {
    const res = await api(`/api/runs/${runId}/mapset`);
    mapsetCache = { runId, kinds: res.kinds || {}, versions: res.versions || [] };
    $("mapsetRun").textContent = runId;
    paintMapset();
  } catch (e) { /* карт версий может не быть — не ошибка */ }
}

// ---------- гейты и байпас ----------
const GATE_MODES = ["best", "skip", "halt", "ask"];
let gatesCache = { gates: [] };

async function loadGates() {
  try {
    gatesCache = await api("/api/gates");
    $("gateBypass").checked = !!gatesCache.bypass_enabled;
    renderGatesEditor();
  } catch (e) { $("gatesList").textContent = String(e); }
}

function renderGatesEditor() {
  $("gatesList").innerHTML = (gatesCache.gates || []).map(g => {
    const opts = GATE_MODES.map(m =>
      `<option value="${m}" ${m === g.on_exhausted ? "selected" : ""}>${m}</option>`).join("");
    return `<div class="gate-row"><span class="mono">${esc(g.id)}</span>
      <span class="gate-agent">${esc(g.agent || "")}</span>
      <select data-gate="${esc(g.id)}">${opts}</select></div>`;
  }).join("");
}

async function saveGates() {
  const gates = {};
  document.querySelectorAll("#gatesList select").forEach(s => {
    gates[s.dataset.gate] = { on_exhausted: s.value };
  });
  try {
    gatesCache = await api("/api/gates", { method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gate_bypass: $("gateBypass").checked, gates }) });
    $("gatesSaved").textContent = "сохранено";
    renderGatesEditor();
    setTimeout(() => { $("gatesSaved").textContent = ""; }, 2500);
  } catch (e) { $("gatesSaved").textContent = "ошибка: " + e; }
}

function renderRunGates(rec) {
  const stages = (((rec.result || {}).agents || {}).stages) || [];
  let html = stages.map(s => `<div class="gate-row"><span class="mono">${esc(s.gate)}</span>
      <span class="gate-agent">${esc(s.agent || "")}</span>
      <span class="gate-st ${esc(s.status)}">${esc(s.status)}</span></div>`).join("");
  if (rec.pending_gate) {
    const g = rec.pending_gate, r = rec.run_id;
    html += `<div class="gate-ask"><b>Гейт ${esc(g)} ждёт решения:</b>
      <button class="mbtn" onclick="resolveGate('${r}','${esc(g)}','best')">best</button>
      <button class="mbtn" onclick="resolveGate('${r}','${esc(g)}','skip')">skip</button>
      <button class="mbtn" onclick="resolveGate('${r}','${esc(g)}','halt')">halt</button>
      <button class="mbtn" onclick="resolveGate('${r}','${esc(g)}','waiver')">waiver</button></div>`;
  }
  $("gatesRun").innerHTML = html || `<span class="mono empty">гейты появятся после прогона</span>`;
}

async function resolveGate(runId, gateId, action) {
  try {
    await api(`/api/runs/${runId}/gates/${gateId}/resolve`, { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, author: "operator", comment: "" }) });
  } catch (e) { alert("Ошибка решения: " + e); }
}

function renderProject(rec) {
  const pp = (rec.result || {}).project || null;
  if (!pp) { $("project").innerHTML = `<span class="mono empty">—</span>`; $("projName").textContent = ""; return; }
  $("projName").textContent = pp.name || "";
  $("project").innerHTML =
    `<div class="kv"><div class="k">поле</div><div class="v">${esc(pp.field)}</div>
      <div class="k">ветвей</div><div class="v">${pp.variants_total}</div>
      <div class="k">папка</div><div class="v">${esc(pp.models_dir)}</div></div>
     <button class="mbtn" onclick="openProject('${rec.run_id}','base')">Открыть базовый проект</button>`;
}

function renderEnsemble(rec) {
  const ens = ((rec.result || {}).project || {}).ensemble;
  if (!ens || !(ens.branches || []).length) { $("graph").innerHTML = `<span class="mono empty">нет ветвей</span>`; return; }
  $("bestId").textContent = ens.best ? `лучшая: ${ens.best}` : "";
  $("graph").innerHTML = svgTree(ens, rec.run_id);
}

function svgTree(ens, runId) {
  const bs = ens.branches;
  const NW = 300, NH = 76, GAP = 14, PAD = 16;
  const height = bs.length * (NH + GAP) + PAD;
  const width = 820;
  const rootX = 20, boxX = 300;
  const rootCy = height / 2;
  let s = `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`;
  s += `<defs><marker id="ah" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
        <path d="M0,0 L7,3 L0,6" fill="#4a9eff"/></marker></defs>`;
  s += `<rect x="${rootX}" y="${rootCy - 26}" width="200" height="52" rx="10" fill="#123a24" stroke="#1d5a37"/>
        <text x="${rootX + 14}" y="${rootCy - 4}" fill="#e7ecf5" font-size="13" font-weight="700">${esc(ens.root)}</text>
        <text x="${rootX + 14}" y="${rootCy + 14}" fill="#8b97ad" font-size="11">метрика: ${esc(ens.metric_name)}</text>`;
  bs.forEach((b, i) => {
    const top = PAD + i * (NH + GAP);
    const cy = top + NH / 2;
    const isBest = ens.best && b.id === ens.best;
    const stroke = isBest ? "#35c46a" : "#263149";
    const mx = (rootX + 200 + boxX) / 2;
    s += `<path d="M${rootX + 200},${rootCy} C ${mx},${rootCy} ${mx},${cy} ${boxX},${cy}" fill="none"
          stroke="#4a9eff" stroke-width="1.4" marker-end="url(#ah)" opacity="0.8"/>`;
    s += `<g style="cursor:pointer" onclick="openProject('${runId}','${b.id}')">`;
    s += `<rect x="${boxX}" y="${top}" width="${NW}" height="${NH}" rx="10" fill="#171f30"
          stroke="${stroke}" stroke-width="${isBest ? 2 : 1}"/>`;
    s += `<text x="${boxX + 12}" y="${top + 20}" fill="#4a9eff" font-size="13" font-weight="700">${esc(b.id)}</text>`;
    s += `<text x="${boxX + 64}" y="${top + 20}" fill="#e7ecf5" font-size="12">${esc(b.label || "")}</text>`;
    const params = Object.entries(b.parameters || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "базовая";
    s += `<text x="${boxX + 12}" y="${top + 38}" fill="#8b97ad" font-size="11" font-family="monospace">${esc(params)}</text>`;
    s += `<text x="${boxX + 12}" y="${top + 56}" fill="#35c46a" font-size="12" font-family="monospace">STOIIP: ${esc(b.metric == null ? "—" : b.metric)}</text>`;
    s += `<text x="${boxX + 12}" y="${top + 70}" fill="#6b7688" font-size="10" font-family="monospace">${esc(b.path || "")}</text>`;
    s += `</g>`;
  });
  return s + `</svg>`;
}

async function openProject(runId, which) {
  try {
    const r = await api(`/api/runs/${runId}/open?which=${which}`, { method: "POST" });
    if (!r.opened) alert("Проект не открыт: " + (r.reason || "") + "\n" + (r.path || ""));
  } catch (e) { alert("Ошибка открытия: " + e); }
}

// ---------- полный сброс (запуск с нуля) ----------
function clearPanels() {
  $("messages").innerHTML = "";
  $("stats").textContent = "—";
  $("steps").innerHTML = `<span class="mono empty">—</span>`;
  $("bar").style.width = "0%";
  $("phaseName").textContent = "";
  $("pbar").style.width = "0%";
  $("phaseInfo").textContent = "—";
  $("maps").innerHTML = `<span class="mono empty">карты появятся после реального прогона</span>`;
  $("mapsRun").textContent = "";
  $("mapset").innerHTML = `<span class="mono empty">карты версий (структура и фации) появятся после реального прогона</span>`;
  $("mapsetRun").textContent = "";
  $("verTabs").innerHTML = "";
  mapsetCache = null;
  currentVersion = "base";
  $("graph").innerHTML = `<span class="mono empty">ветки появятся после прогона</span>`;
  $("bestId").textContent = "";
  $("log").textContent = "";
}

async function resetAll() {
  if (!confirm("Сбросить всё? Будут удалены все сообщения и прогоны (запуск с нуля).")) return;
  try {
    await api("/api/reset", { method: "POST" });
  } catch (e) {
    alert("Ошибка сброса: " + e);
    return;
  }
  currentRun = null;
  stopPolling();
  if (ws) { try { ws.close(); } catch (e) {} ws = null; }
  for (const k of Object.keys(RUN_MSG)) delete RUN_MSG[k];
  MAPS_FETCHED.clear();
  MAPSET_FETCHED.clear();
  clearPanels();
}

$("btnSend").onclick = doSend;
$("btnRun").onclick = doRun;
$("btnReset").onclick = resetAll;
$("message").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); } });
$("gatesSave").onclick = saveGates;
window.openProject = openProject;
window.resolveGate = resolveGate;
window.selectVersion = selectVersion;

loadHealth(); loadOntology(); loadGates(); loadChat();

// ================= ВКЛАДКА «ГРАФ МОДЕЛИРОВАНИЯ» =============================
// Данные ТОЛЬКО из API/отчёта прогона: названия этапов, шагов, гейтов, проверок,
// ветвей и статусы приходят в payload — в этом файле доменных имён нет.
let GRAPH = null;              // последний payload /api/runs/{id}/graph
let GRAPH_TIMER = null;        // авто-обновление, пока прогон идёт
const TONE_LABEL = { ok: "норма", warn: "внимание", bad: "провал",
                     info: "данные", neutral: "без вердикта" };

function setView(name) {
  for (const btn of document.querySelectorAll("#viewTabs .tab"))
    btn.classList.toggle("on", btn.dataset.view === name);
  $("viewRun").classList.toggle("hidden", name !== "run");
  $("viewGraph").classList.toggle("hidden", name !== "model-graph");
  if (name === "model-graph") loadGraphRuns();
}

async function loadGraphRuns() {
  const sel = $("graphRun");
  try {
    const runs = await api("/api/runs");
    const list = Array.isArray(runs) ? runs : [];
    sel.innerHTML = list.map(r => {
      const label = [r.field, r.run_id, r.status].filter(Boolean).join(" · ");
      return `<option value="${esc(r.run_id)}">${esc(label)}</option>`;
    }).join("") || `<option value="">прогонов нет</option>`;
    if (!sel.value && list.length) sel.value = list[0].run_id;
    if (sel.value) loadModelGraph();
    else $("graphCanvas").innerHTML =
      `<span class="mono empty">прогонов нет — запустите прогон на вкладке «Прогон»</span>`;
  } catch (e) {
    $("graphCanvas").innerHTML = `<span class="mono empty">ошибка списка прогонов: ${esc(e)}</span>`;
  }
}

async function loadModelGraph() {
  const runId = $("graphRun").value;
  const source = $("graphSource").value || "auto";
  if (GRAPH_TIMER) { clearTimeout(GRAPH_TIMER); GRAPH_TIMER = null; }
  if (!runId) return;
  $("graphMeta").textContent = "загрузка…";
  try {
    GRAPH = await api(`/api/runs/${encodeURIComponent(runId)}/graph?source=${encodeURIComponent(source)}`);
  } catch (e) {
    GRAPH = null;
    $("graphMeta").textContent = "";
    $("graphSummary").textContent = String(e).slice(0, 300);
    $("graphCanvas").innerHTML =
      `<span class="mono empty">граф недоступен: ${esc(String(e).slice(0, 200))}</span>`;
    $("graphDetails").innerHTML =
      `<span class="mono empty">данных отчёта пока нет — граф строится по report.json, steps.json и agents/gates|handoffs</span>`;
    return;
  }
  paintModelGraph();
}

function paintModelGraph() {
  const g = GRAPH || {};
  const s = g.summary || {};
  const src = g.sources || {};
  const parts = [
    g.field ? `поле: ${g.field}` : "",
    g.run_status ? `прогон: ${g.run_status}` : "",
    `этапов: ${s.stages_total ?? "—"}`,
    `шагов: ${s.steps_total ?? "—"}${s.steps && s.steps.total ? ` (done ${s.steps.done ?? "—"}, error ${s.steps.error ?? "—"})` : ""}`,
    `гейтов: ${s.gates_total ?? "—"}`,
    s.critic_verdict ? `Метакритик: ${s.critic_verdict}` : "",
    s.branches_total ? `ветвей: ${s.branches_total}${s.best_branch ? `, лучшая ${s.best_branch}` : ""}` : "ансамбль: не объявлен",
    s.grid ? `сетка: ${s.grid.nx}×${s.grid.ny}×${s.grid.nz}` : "",
  ].filter(Boolean);
  $("graphMeta").textContent = src.report ? `отчёт: ${src.report} (${src.report_kind || "—"})` : "";
  // выбор источника: список отчётов приходит из API (в каталоге могут быть оба)
  const avail = src.available || [];
  const srcSel = $("graphSource");
  const prev = srcSel.value;
  srcSel.innerHTML = [["auto", "авто"]].concat(
    avail.map(a => [a.kind, `${a.kind} · ${a.file}`])
  ).map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
  srcSel.value = avail.some(a => a.kind === prev) || prev === "auto" ? prev : "auto";
  $("graphSourceBox").classList.toggle("hidden", avail.length < 2);
  if (s.artifacts_consistent === false)
    parts.push("⚠ артефакты от разных прогонов");
  $("graphSummary").innerHTML = parts.map(p => `<span class="chip">${esc(p)}</span>`).join("");
  $("graphLegend").innerHTML = (g.legend && g.legend.tones || [])
    .map(t => `<span class="lg"><i class="dot tone-${esc(t)}"></i>${esc(TONE_LABEL[t] || t)}</span>`)
    .join("");
  if (!(g.nodes || []).length) {
    $("graphCanvas").innerHTML = `<span class="mono empty">узлов нет: ${esc((g.warnings || []).join("; ") || "данных недостаточно")}</span>`;
    return;
  }
  $("graphCanvas").innerHTML = graphSvg(g);
  for (const el of document.querySelectorAll("#graphCanvas .gnode"))
    el.addEventListener("click", () => showNodeDetails(el.dataset.node));
  if ((g.warnings || []).length)
    $("graphCanvas").insertAdjacentHTML("beforeend",
      `<div class="gwarn mono">${esc(g.warnings.join(" · "))}</div>`);
  if (String(g.run_status || "") === "running") GRAPH_TIMER = setTimeout(loadModelGraph, 5000);
}

function graphSvg(g) {
  const nodes = g.nodes || [], edges = g.edges || [];
  const W = 178, H = 52, GX = 34, GY = 20;
  const cols = Math.max(...nodes.map(n => n.col || 0)) + 1;
  const rows = Math.max(...nodes.map(n => (n.row || 0) + 1)) + 1;
  const width = cols * (W + GX) + GX, height = rows * (H + GY) + GY + 10;
  const pos = {};
  for (const n of nodes) {
    pos[n.id] = { x: GX + (n.col || 0) * (W + GX), y: GY + ((n.row || 0) + 1) * (H + GY) };
  }
  const paths = edges.map(e => {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) return "";
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
    const d = x2 > x1
      ? `M ${x1} ${y1} C ${x1 + 30} ${y1}, ${x2 - 30} ${y2}, ${x2} ${y2}`
      : `M ${x1} ${y1} C ${x1 + 24} ${y1}, ${x1 + 24} ${y2}, ${x2} ${y2}`;
    const title = `${e.type}${e.label ? " · " + e.label : ""}`;
    return `<path class="gedge e-${esc(e.type)}" d="${d}" data-edge="${esc(e.id)}"><title>${esc(title)}</title></path>`;
  }).join("");
  const boxes = nodes.map(n => {
    const p = pos[n.id];
    const label = String(n.label || "").slice(0, 24);
    const sub = String(n.subtitle || "").slice(0, 26);
    return `<g class="gnode t-${esc(n.type)} tone-${esc(n.tone)}" data-node="${esc(n.id)}"
                transform="translate(${p.x},${p.y})">
      <rect width="${W}" height="${H}" rx="7"></rect>
      <text class="nl" x="9" y="21">${esc(label)}</text>
      <text class="ns" x="9" y="39">${esc(sub)}</text>
      <title>${esc([n.type, n.status, n.label, n.subtitle].filter(Boolean).join(" · "))}</title>
    </g>`;
  }).join("");
  return `<svg class="gsvg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
    ${paths}${boxes}</svg>`;
}

function showNodeDetails(nodeId) {
  const g = GRAPH || {};
  const node = (g.nodes || []).find(n => n.id === nodeId);
  if (!node) return;
  const attrs = node.attrs || {};
  const rows = [];
  const skip = new Set(["findings", "rules_sample", "evidence", "lineage",
                        "artifact_revisions", "parameters", "sha256", "qaqc",
                        "counts", "metrics", "unresolved_findings"]);
  for (const [k, v] of Object.entries(attrs)) {
    if (skip.has(k) || v === null || v === undefined || v === "") continue;
    if (typeof v === "object") continue;
    rows.push(`<div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>`);
  }
  let extra = "";
  if (attrs.counts) extra += `<h4>счёт по уровням</h4>${kvTable(attrs.counts)}`;
  if (attrs.qaqc) extra += `<h4>QA/QC</h4>${kvTable(attrs.qaqc)}`;
  if (attrs.metrics && Object.keys(attrs.metrics).length)
    extra += `<h4>метрики ветви</h4>${kvTable(attrs.metrics)}`;
  if (attrs.parameters && Object.keys(attrs.parameters).length)
    extra += `<h4>параметры ветви</h4><pre>${esc(JSON.stringify(attrs.parameters, null, 1))}</pre>`;
  if (Array.isArray(attrs.lineage) && attrs.lineage.length)
    extra += `<h4>lineage (зависимости)</h4><ol class="lin">${attrs.lineage.map(x => `<li>${esc(x)}</li>`).join("")}</ol>`;
  if (Array.isArray(attrs.findings) && attrs.findings.length)
    extra += findingsTable(attrs.findings, "проверки этапа");
  if (Array.isArray(attrs.rules_sample) && attrs.rules_sample.length)
    extra += `<h4>правила Метакритика (не passed, первые ${attrs.rules_sample.length} из ${attrs.rules_not_passed ?? "—"})</h4>`
      + `<ul class="lin">${attrs.rules_sample.map(r => `<li><span class="mono">${esc(r.rule_id)}</span> — ${esc(r.verdict)}: ${esc(r.note || "")}</li>`).join("")}</ul>`;
  if (attrs.evidence) extra += `<h4>свидетельство</h4><pre>${esc(JSON.stringify(attrs.evidence, null, 1)).slice(0, 4000)}</pre>`;
  if (attrs.sha256) extra += `<h4>sha256 артефактов</h4>${kvTable(attrs.sha256)}`;
  if (Array.isArray(attrs.artifact_revisions) && attrs.artifact_revisions.length)
    extra += `<h4>ревизии артефактов</h4><ul class="lin">${attrs.artifact_revisions.map(r => `<li><span class="mono">${esc(r.path || "")}</span><br>${esc(String(r.sha256 || "").slice(0, 24))}…</li>`).join("")}</ul>`;
  if (Array.isArray(attrs.unresolved_findings) && attrs.unresolved_findings.length)
    extra += `<h4>незакрытые находки</h4><ul class="lin">${attrs.unresolved_findings.map(x => `<li>${esc(typeof x === "string" ? x : JSON.stringify(x))}</li>`).join("")}</ul>`;
  $("graphDetails").innerHTML = `
    <h3>${esc(node.label || node.id)}</h3>
    <div class="dsub mono">${esc(node.type)} · ${esc(node.status || "—")}</div>
    <div class="dsub">${esc(node.subtitle || "")}</div>
    <div class="dkv">${rows.join("")}</div>${extra}`;
}

function kvTable(obj) {
  return `<div class="dkv">${Object.entries(obj || {})
    .map(([k, v]) => `<div class="k">${esc(k)}</div><div class="v">${esc(typeof v === "object" ? JSON.stringify(v) : v)}</div>`)
    .join("")}</div>`;
}

function findingsTable(list, title) {
  return `<h4>${esc(title)}</h4><table class="ftab"><thead><tr>
      <th>id</th><th>уровень</th><th>вердикт</th><th>что проверено</th><th>remediation</th>
    </tr></thead><tbody>${list.map(f => `<tr class="tone-${f.passed ? "ok" : "bad"}">
      <td class="mono">${esc(f.id || "")}</td><td>${esc(f.severity || "")}</td>
      <td>${f.passed ? "passed" : "failed"}</td><td>${esc(f.title || f.message || "")}</td>
      <td>${esc(f.remediation || "")}</td></tr>`).join("")}</tbody></table>`;
}

for (const btn of document.querySelectorAll("#viewTabs .tab"))
  btn.addEventListener("click", () => setView(btn.dataset.view));
$("graphRun").onchange = loadModelGraph;
$("graphRefresh").onclick = loadModelGraph;
$("graphSource").onchange = loadModelGraph;
window.setView = setView;
window.loadModelGraph = loadModelGraph;

