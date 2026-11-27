/* AI Meeting Notes - vanilla JS front-end (no build step). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const LANGS = [["en", "English"], ["vi", "Vietnamese"], ["auto", "Auto-detect (Whisper)"], ["de", "German"], ["fr", "French"],
  ["es", "Spanish"], ["it", "Italian"], ["pt", "Portuguese"], ["ja", "Japanese"], ["zh", "Chinese"], ["ko", "Korean"],
  ["ru", "Russian"], ["nl", "Dutch"], ["hi", "Hindi"]];
const MODE_LABEL = { online: "Online meeting", in_person: "In-person", system: "Computer audio", file: "Recording file" };

const S = { status: null, settings: null, meetings: [], cur: null, ws: null, partials: {}, recording: null, notesTimer: null };

// ------------------------------------------------------------------ helpers
async function api(path, opts = {}) {
  const o = { ...opts, headers: { ...(opts.headers || {}) } };
  if (o.method && o.method !== "GET") o.headers["x-meeting-notes"] = "1";
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers["Content-Type"] = "application/json"; delete o.json; }
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = j.detail || msg; } catch { try { msg = await r.text(); } catch { /* ignore */ } }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("application/json") ? r.json() : r;
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ts = (sec) => { sec = Math.max(0, Math.floor(sec || 0)); const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60; return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":"); };
const fmtDate = (iso) => { try { return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); } catch { return iso; } };
function showError(msg) { const e = $("#errors"); e.textContent = msg; e.classList.toggle("hidden", !msg); }
function fillSelect(sel, items, value) { sel.innerHTML = items.map(([v, l, dis]) => `<option value="${esc(v)}" ${dis ? "disabled" : ""}>${esc(l)}</option>`).join(""); if (value !== undefined) sel.value = value; }

// Tiny, safe Markdown renderer (headings, lists, checkboxes, bold/italic/code, tables, links as text).
function md(src) {
  const inline = (t) => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|\W)\*([^*\n]+)\*(?=\W|$)/g, "$1<i>$2</i>").replace(/(^|\W)_([^_\n]+)_(?=\W|$)/g, "$1<i>$2</i>");
  const lines = String(src || "").replace(/\r/g, "").split("\n");
  let out = "", list = null, table = null;
  const close = () => { if (list) { out += `</${list}>`; list = null; } if (table) { out += "</table>"; table = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m;
    if (/^\s*\|.*\|\s*$/.test(line)) {
      if (/^\s*\|[\s:|-]+\|\s*$/.test(line)) continue;
      if (!table) { close(); out += "<table>"; table = "t"; }
      out += "<tr>" + line.trim().slice(1, -1).split("|").map((c) => `<td>${inline(c.trim())}</td>`).join("") + "</tr>";
      continue;
    }
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) { close(); const n = Math.min(4, m[1].length + 1); out += `<h${n}>${inline(m[2])}</h${n}>`; continue; }
    if ((m = line.match(/^\s*[-*]\s+\[( |x|X)\]\s+(.*)/))) { if (list !== "ul") { close(); out += "<ul>"; list = "ul"; } out += `<li class="task"><input type="checkbox" disabled ${m[1] !== " " ? "checked" : ""}> ${inline(m[2])}</li>`; continue; }
    if ((m = line.match(/^\s*[-*]\s+(.*)/))) { if (list !== "ul") { close(); out += "<ul>"; list = "ul"; } out += `<li>${inline(m[1])}</li>`; continue; }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); out += "<ol>"; list = "ol"; } out += `<li>${inline(m[1])}</li>`; continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(line)) { close(); out += "<hr>"; continue; }
    if (!line.trim()) { close(); continue; }
    close(); out += `<p>${inline(line)}</p>`;
  }
  close();
  return out;
}

// ------------------------------------------------------------------- loading
async function loadStatus() {
  S.status = await api("/api/status");
  S.settings = await api("/api/settings");
  const ts_ = S.settings.transcription;
  fillSelect($("#engine"), S.status.engines.map((e) => [e.name, e.label + (e.available ? "" : " - unavailable"), !e.available]), ts_.engine);
  if ($("#engine").selectedOptions[0]?.disabled) { const ok = S.status.engines.find((e) => e.available); if (ok) $("#engine").value = ok.name; }
  fillSelect($("#language"), LANGS, ts_.language);
  fillSelect($("#aiKind"), Object.entries(S.status.analysis_kinds), "summary");
  fillSelect($("#aiTemplate"), S.status.summary_templates.map((t) => [t.name, t.label]), S.settings.default_summary_template);
  fillSelect($("#aiProvider"), [["auto", "Auto (fallback order)"], ...S.status.ai_providers.map((p) => [p.name, p.label + (p.available ? "" : " - not set up"), !p.available])], "auto");
  const sess = S.status.session;
  S.recording = sess ? { id: sess.meeting_id, status: sess.status } : null;
}

async function loadMeetings() {
  const q = $("#search").value.trim();
  S.meetings = await api("/api/meetings" + (q ? "?q=" + encodeURIComponent(q) : ""));
  $("#meetingList").innerHTML = S.meetings.map((m) => `<li data-id="${esc(m.id)}" class="${S.cur?.meeting.id === m.id ? "active" : ""}">
      ${S.recording?.id === m.id ? '<span class="rec-dot">●</span> ' : ""}${esc(m.title)}
      <span class="sub">${esc(m.snippet || fmtDate(m.created_at) + (m.duration ? " · " + ts(m.duration) : ""))}</span></li>`).join("")
    || `<li class="muted small">${q ? "No matches" : "No meetings yet"}</li>`;
}

async function loadCalendar() {
  if (!S.settings.calendar_ics.length) { $("#calendarBox").classList.add("hidden"); return; }
  try {
    const { events, errors } = await api("/api/calendar/upcoming");
    $("#calendarBox").classList.remove("hidden");
    $("#calendarList").innerHTML = events.slice(0, 6).map((e, i) => `<li data-i="${i}">${esc(e.title)}
      <span class="sub">${esc(fmtDate(e.start))}${e.app ? " · " + esc(e.app) : ""}</span></li>`).join("")
      || `<li class="muted small">${errors.length ? esc(errors[0]) : "Nothing scheduled"}</li>`;
    $$("#calendarList li[data-i]").forEach((li) => li.onclick = () => newMeeting(events[+li.dataset.i]));
  } catch (e) { console.warn(e); }
}

async function openMeeting(id) {
  const data = await api(`/api/meetings/${id}`);
  S.cur = data; S.partials = {};
  $("#empty").classList.add("hidden"); $("#meetingView").classList.remove("hidden");
  renderMeeting(); connectWS(id); loadMeetings();
  history.replaceState(null, "", "#" + id);
}

// ----------------------------------------------------------------- rendering
function renderMeeting() {
  const m = S.cur.meeting;
  $("#title").value = m.title;
  $("#attendees").value = (m.attendees || []).join(", ");
  $("#metaDate").textContent = fmtDate(m.created_at);
  $("#metaDur").textContent = ts(m.duration);
  $("#metaMode").textContent = MODE_LABEL[m.mode] || m.mode;
  if (m.mode !== "file") $("#mode").value = m.mode;
  if (m.language && [...$("#language").options].some((o) => o.value === m.language)) $("#language").value = m.language;
  $("#notes").value = S.cur.notes; $("#notesState").textContent = "";
  renderTranscript(); renderAnalyses(); renderRecorder();
  $("#consentChk").checked = !!m.consent_confirmed;
}

function segHTML(s, hl) {
  return `<div class="seg ${hl ? "hl" : ""}" data-seq="${s.seq}"><span class="ts">${ts(s.start)}</span>
    <span class="sp ${esc(s.source)}" title="${esc(s.speaker)}">${esc(s.speaker)}</span><span class="tx">${esc(s.text)}</span></div>`;
}
function isHighlighted(s) { return (S.cur.meeting.highlights || []).some((h) => h.t >= s.start - 1 && h.t <= s.end + 1); }
function renderTranscript() {
  const segs = S.cur.segments;
  $("#transcript").innerHTML = segs.length ? segs.map((s) => segHTML(s, isHighlighted(s))).join("") : '<p class="muted">No transcript yet. Press Start to begin live transcription.</p>';
  const speakers = [...new Set(segs.map((s) => s.speaker))];
  fillSelect($("#speakerOld"), speakers.map((s) => [s, s]));
  renderPartials();
}
function renderPartials() {
  $("#partials").innerHTML = Object.entries(S.partials).filter(([, p]) => p.text)
    .map(([src, p]) => `<div class="seg"><span class="ts">…</span><span class="sp ${esc(src)}">${esc(p.speaker)}</span><span class="tx">${esc(p.text)}</span></div>`).join("");
}
function renderAnalyses() {
  const a = S.cur.analyses || {}, meta = S.cur.meeting.analyses || {};
  const order = ["summary", "action_items", "decisions", "follow_up_email", "draft_doc", "speakers", "qa"];
  const kinds = Object.keys(a).sort((x, y) => order.indexOf(x) - order.indexOf(y));
  const names = { ...S.status.analysis_kinds, qa: "Questions & answers" };
  $("#analyses").innerHTML = kinds.length ? kinds.map((k) => `<article class="analysis" data-kind="${esc(k)}">
      <div class="a-head"><b>${esc(names[k] || k)}</b><span>${esc(meta[k]?.provider || "")} ${esc(meta[k]?.model || "")} · ${esc(fmtDate(meta[k]?.created_at))}
      <button class="ghost small copy" data-kind="${esc(k)}">Copy</button></span></div><div class="md">${md(a[k])}</div></article>`).join("")
    : `<p class="muted">No AI notes yet. Transcription works without AI; when the meeting is over, choose what to generate above.
       ${S.status.ai_providers.some((p) => p.available) ? "" : "<br><b>No AI provider is set up</b> - add GEMINI_API_KEY to .env, sign in to the Antigravity CLI (agy), or install Claude Code."}</p>`;
  $$("#analyses .copy").forEach((b) => b.onclick = () => navigator.clipboard.writeText(a[b.dataset.kind]));
}
function updateEngineNote() {
  const eng = S.status.engines.find((e) => e.name === $("#engine").value);
  const real = S.status.engines.some((e) => e.available && e.name !== "mock");
  let html = "";
  if (eng?.name === "mock") {
    html = "<b>Test engine selected - it does not turn speech into words.</b> It only marks where someone spoke, to check that audio capture works.";
    if (!real) {
      const vosk = S.status.engines.find((e) => e.name === "vosk");
      html += `<br>For live transcription install a speech model, then reload this page:<code>python scripts/download_models.py vosk en</code>` +
        (vosk && !vosk.reason.startsWith("pip") ? "" : ` (first <code>pip install -e ".[vosk]"</code>)`) +
        `. Use <code>vosk vi</code>, <code>vosk de</code>… for other languages.`;
    } else {
      html += " Pick another engine above for live transcription.";
    }
  }
  $("#engineNote").innerHTML = html;
  $("#engineNote").classList.toggle("hidden", !html);
}

function renderRecorder() {
  updateEngineNote();
  const id = S.cur?.meeting.id, rec = S.recording, mine = rec && rec.id === id, busy = rec && !mine;
  $("#startBtn").classList.toggle("hidden", !!mine); $("#startBtn").disabled = !!busy;
  $("#startBtn").title = busy ? "Another meeting is recording" : "";
  $("#pauseBtn").classList.toggle("hidden", !(mine && rec.status === "recording"));
  $("#resumeBtn").classList.toggle("hidden", !(mine && rec.status === "paused"));
  $("#stopBtn").classList.toggle("hidden", !mine); $("#highlightBtn").classList.toggle("hidden", !mine);
  ["#mode", "#engine", "#language"].forEach((s) => $(s).disabled = !!mine);
  $("#consent").classList.toggle("hidden", !(mine && S.settings.consent_reminder));
  if (!mine) $$(".lvl i").forEach((i) => i.style.width = "0");
  $("#startBtn").textContent = S.cur?.segments.length ? "● Continue" : "● Start";
}

// ----------------------------------------------------------------- websocket
function connectWS(id) {
  if (S.ws) { S.ws.onclose = null; S.ws.close(); }
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/meetings/${id}`);
  S.ws = ws;
  ws.onmessage = (msg) => onEvent(JSON.parse(msg.data));
  ws.onclose = () => setTimeout(() => S.cur?.meeting.id === id && connectWS(id), 2000);
  clearInterval(S.ping); S.ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
}
function onEvent(e) {
  if (!S.cur) return;
  if (e.type === "segment") {
    S.cur.segments.push(e.segment);
    const box = $("#transcript"), atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    if (S.cur.segments.length === 1) box.innerHTML = "";
    box.insertAdjacentHTML("beforeend", segHTML(e.segment, false));
    if (atBottom) $("#partials").scrollIntoView({ block: "end" });
  } else if (e.type === "partial") {
    S.partials[e.source] = { speaker: e.speaker, text: e.text }; renderPartials();
  } else if (e.type === "level") {
    const bar = $(`.lvl[data-src="${e.source}"] i`); if (bar) bar.style.width = Math.min(100, Math.sqrt(e.rms) * 260) + "%";
  } else if (e.type === "status") {
    $("#timer").textContent = ts(e.elapsed);
    if (e.status === "done") { S.recording = null; S.partials = {}; renderPartials(); refreshCurrent(); }
    else S.recording = { id: S.cur.meeting.id, status: e.status };
    renderRecorder();
  } else if (e.type === "error") {
    showError(`${e.source}: ${e.message}`);
  }
}
async function refreshCurrent() { if (S.cur) { const d = await api(`/api/meetings/${S.cur.meeting.id}`); S.cur = d; renderMeeting(); loadMeetings(); } }

// ------------------------------------------------------------------- actions
async function newMeeting(ev) {
  const body = ev && ev.title ? { title: ev.title, attendees: ev.attendees || [], mode: "online", calendar_event: ev } : { mode: $("#mode").value || "online" };
  const m = await api("/api/meetings", { method: "POST", json: body });
  await openMeeting(m.id);
  if (!ev || !ev.title) { $("#title").focus(); $("#title").select(); }
}
async function record(action) {
  showError("");
  const id = S.cur.meeting.id;
  try {
    if (action === "start") {
      $("#startBtn").disabled = true;
      await api(`/api/meetings/${id}/record/start`, { method: "POST", json: { mode: $("#mode").value, engine: $("#engine").value, language: $("#language").value } });
      S.recording = { id, status: "recording" };
      switchTab("transcript");
    } else {
      const r = await api(`/api/meetings/${id}/record/${action}`, { method: "POST" });
      S.recording = r.status === "done" ? null : { id, status: r.status };
      if (r.status === "done") { await refreshCurrent(); switchTab("summary"); }
    }
  } catch (e) { showError(e.message); } finally { $("#startBtn").disabled = false; renderRecorder(); loadMeetings(); }
}
function switchTab(name) {
  $$(".tabs [data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$("[data-panel]").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== name));
}
async function patchMeeting(changes) { S.cur.meeting = await api(`/api/meetings/${S.cur.meeting.id}`, { method: "PATCH", json: changes }); loadMeetings(); }

async function runAI() {
  const kind = $("#aiKind").value, btn = $("#aiRun");
  btn.disabled = true; $("#aiStatus").textContent = "Working… long meetings can take a minute.";
  try {
    const r = await api(`/api/meetings/${S.cur.meeting.id}/analyze`, { method: "POST", json: { kind, template: $("#aiTemplate").value, provider: $("#aiProvider").value, doc_type: $("#docType").value } });
    $("#aiStatus").textContent = `Done with ${r.provider}.`;
    await refreshCurrent();
  } catch (e) { $("#aiStatus").textContent = ""; showError(e.message); } finally { btn.disabled = false; }
}
async function ask(all) {
  const input = all ? $("#askAllInput") : $("#askInput"), out = all ? $("#askAllOut") : $("#askOut");
  const q = input.value.trim(); if (!q) return;
  out.innerHTML = '<p class="muted">Thinking…</p>';
  try {
    const provider = $("#aiProvider").value;
    if (all) {
      const r = await api("/api/ask", { method: "POST", json: { question: q, provider } });
      out.innerHTML = md(r.answer) + (r.sources?.length ? `<p class="small muted">Sources: ${[...new Map(r.sources.map((s) => [s.meeting_id, s])).values()].map((s) => `<a href="#${esc(s.meeting_id)}" data-open="${esc(s.meeting_id)}">${esc(s.title)}</a>`).join(", ")}</p>` : "");
      $$("[data-open]", out).forEach((a) => a.onclick = (ev) => { ev.preventDefault(); $("#askAllDlg").close(); openMeeting(a.dataset.open); });
    } else {
      const r = await api(`/api/meetings/${S.cur.meeting.id}/ask`, { method: "POST", json: { question: q, provider } });
      out.innerHTML = md(r.text) + `<p class="small muted">${esc(r.provider)} - saved under Summary › Questions & answers</p>`;
      const d = await api(`/api/meetings/${S.cur.meeting.id}`); S.cur.analyses = d.analyses; S.cur.meeting = d.meeting; renderAnalyses();
    }
  } catch (e) { out.innerHTML = `<p class="danger-text">${esc(e.message)}</p>`; }
}

// ------------------------------------------------------------------ settings
async function openSettings() {
  const s = S.settings, t = s.transcription, a = s.ai;
  fillSelect($("#sEngine"), S.status.engines.map((e) => [e.name, e.label + (e.available ? "" : " - " + e.reason)]), t.engine);
  fillSelect($("#sLanguage"), LANGS, t.language);
  const dev = await api("/api/devices");
  fillSelect($("#sMic"), [["", "System default"], ...dev.microphones.map((d) => [d.name, d.name])], t.mic_device);
  fillSelect($("#sSystem"), [["", dev.platform === "darwin" ? "Choose a loopback device (BlackHole…)" : "Default output (speakers / headphones)"], ...dev.system.map((d) => [d.name, d.name + (d.virtual ? " (virtual)" : "")])], t.system_device);
  $("#sDeviceNote").textContent = dev.available ? dev.note : dev.error;
  $("#sWhisper").value = t.whisper_model; $("#sMe").value = t.me_label; $("#sOthers").value = t.others_label; $("#sRoom").value = t.room_label;
  $("#sOrder").value = a.provider_order.join(", "); $("#sGeminiModel").value = a.gemini_model; $("#sAgy").value = a.agy_model;
  $("#sClaude").value = a.claude_model; $("#sOutLang").value = a.output_language;
  $("#sProviders").innerHTML = S.status.ai_providers.map((p) => `<div class="${p.available ? "prov-ok" : "prov-no"}">${p.available ? "✓" : "○"} ${esc(p.label)} - ${esc(p.reason)}</div>`).join("");
  $("#sIcs").value = s.calendar_ics.join("\n"); $("#sConsent").checked = s.consent_reminder;
  $("#sDataDir").textContent = S.status.data_dir; $("#restoreState").textContent = "";
  $("#settingsDlg").showModal();
}
async function saveSettings() {
  const patch = {
    transcription: { engine: $("#sEngine").value, language: $("#sLanguage").value, mic_device: $("#sMic").value, system_device: $("#sSystem").value,
      whisper_model: $("#sWhisper").value.trim() || "small", me_label: $("#sMe").value.trim() || "Me", others_label: $("#sOthers").value.trim() || "Others", room_label: $("#sRoom").value.trim() || "Speaker" },
    ai: { provider_order: $("#sOrder").value.split(",").map((x) => x.trim()).filter(Boolean), gemini_model: $("#sGeminiModel").value.trim(),
      agy_model: $("#sAgy").value.trim(), claude_model: $("#sClaude").value.trim(), output_language: $("#sOutLang").value.trim() },
    calendar_ics: $("#sIcs").value.split("\n").map((x) => x.trim()).filter(Boolean),
    consent_reminder: $("#sConsent").checked,
  };
  await api("/api/settings", { method: "PUT", json: patch });
  await loadStatus(); loadCalendar(); if (S.cur) renderRecorder();
}
async function restoreBackup(file) {
  $("#restoreState").textContent = "Restoring…";
  try {
    const r = await api("/api/restore", { method: "POST", body: await file.arrayBuffer(), headers: { "Content-Type": "application/zip" } });
    $("#restoreState").textContent = `Restored ${r.restored.length} meetings, skipped ${r.skipped.length} that already exist.`;
    loadMeetings();
  } catch (e) { $("#restoreState").textContent = e.message; }
}

// --------------------------------------------------------------------- wire
function wire() {
  $("#newMeeting").onclick = $("#newMeeting2").onclick = () => newMeeting();
  let st; $("#search").oninput = () => { clearTimeout(st); st = setTimeout(loadMeetings, 250); };
  $("#meetingList").onclick = (e) => { const li = e.target.closest("li[data-id]"); if (li) openMeeting(li.dataset.id); };
  $("#engine").onchange = updateEngineNote;
  $("#startBtn").onclick = () => record("start"); $("#pauseBtn").onclick = () => record("pause");
  $("#resumeBtn").onclick = () => record("resume"); $("#stopBtn").onclick = () => record("stop");
  $("#highlightBtn").onclick = async () => { const label = prompt("Highlight label (optional)") ?? ""; try { await api(`/api/meetings/${S.cur.meeting.id}/highlight`, { method: "POST", json: { label } }); } catch (e) { showError(e.message); } };
  $$(".tabs [data-tab]").forEach((b) => b.onclick = () => switchTab(b.dataset.tab));
  $("#title").onchange = () => patchMeeting({ title: $("#title").value.trim() || "Untitled meeting" });
  $("#attendees").onchange = () => patchMeeting({ attendees: $("#attendees").value.split(",").map((x) => x.trim()).filter(Boolean) });
  $("#consentChk").onchange = () => patchMeeting({ consent_confirmed: $("#consentChk").checked });
  $("#notes").oninput = () => {
    $("#notesState").textContent = "Saving…"; clearTimeout(S.notesTimer);
    S.notesTimer = setTimeout(async () => { await api(`/api/meetings/${S.cur.meeting.id}/notes`, { method: "PUT", json: { text: $("#notes").value } }); S.cur.notes = $("#notes").value; $("#notesState").textContent = "Saved"; }, 600);
  };
  $("#aiKind").onchange = () => { $("#aiTemplate").classList.toggle("hidden", $("#aiKind").value !== "summary"); $("#docType").classList.toggle("hidden", $("#aiKind").value !== "draft_doc"); };
  $("#aiRun").onclick = runAI;
  $("#askBtn").onclick = () => ask(false); $("#askInput").onkeydown = (e) => e.key === "Enter" && ask(false);
  $("#askAllBtn").onclick = () => { $("#askAllDlg").showModal(); $("#askAllInput").focus(); };
  $("#askAllRun").onclick = () => ask(true); $("#askAllInput").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); ask(true); } };
  $("#exportBtn").onclick = () => { location.href = `/api/meetings/${S.cur.meeting.id}/export?format=${$("#exportFmt").value}`; };
  $("#deleteBtn").onclick = async () => {
    if (!confirm(`Move "${S.cur.meeting.title}" to the trash folder? (It can be recovered from the data folder.)`)) return;
    try { await api(`/api/meetings/${S.cur.meeting.id}`, { method: "DELETE" }); S.cur = null; $("#meetingView").classList.add("hidden"); $("#empty").classList.remove("hidden"); loadMeetings(); } catch (e) { showError(e.message); }
  };
  $("#transcript").onclick = (e) => {
    const tx = e.target.closest(".tx"); if (!tx || tx.isContentEditable) return;
    const seq = +tx.closest(".seg").dataset.seq; tx.contentEditable = "true"; tx.focus();
    const done = async () => { tx.contentEditable = "false"; const text = tx.textContent.trim(); const seg = S.cur.segments.find((s) => s.seq === seq);
      if (seg && text !== seg.text) { await api(`/api/meetings/${S.cur.meeting.id}/segments/${seq}`, { method: "PATCH", json: { text } }); seg.text = text; } };
    tx.onblur = done; tx.onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); tx.blur(); } };
  };
  $("#renameBtn").onclick = async () => {
    const old = $("#speakerOld").value, nw = $("#speakerNew").value.trim(); if (!old || !nw) return;
    await api(`/api/meetings/${S.cur.meeting.id}/speakers/rename`, { method: "POST", json: { old, new: nw } }); $("#speakerNew").value = ""; refreshCurrent();
  };
  $("#copyTranscript").onclick = () => navigator.clipboard.writeText(S.cur.segments.map((s) => `[${ts(s.start)}] ${s.speaker}: ${s.text}`).join("\n"));
  $("#settingsBtn").onclick = openSettings;
  $("#saveSettings").onclick = (e) => { e.preventDefault(); saveSettings().then(() => $("#settingsDlg").close()).catch((err) => alert(err.message)); };
  $("#backupBtn").onclick = () => { location.href = "/api/backup"; };
  $("#restoreFile").onchange = (e) => e.target.files[0] && restoreBackup(e.target.files[0]);
}

(async function init() {
  wire();
  try { await loadStatus(); } catch (e) { document.body.insertAdjacentHTML("afterbegin", `<div class="errors">Cannot reach the app server: ${esc(e.message)}</div>`); return; }
  $("#aiKind").onchange();
  await loadMeetings(); loadCalendar();
  const id = location.hash.slice(1) || S.recording?.id;
  if (id) openMeeting(id).catch(() => history.replaceState(null, "", "#"));
})();
