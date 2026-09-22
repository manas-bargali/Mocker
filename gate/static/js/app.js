"use strict";
// ── State ──────────────────────────────────────────────────────
const state = { cfg: null, questions: [], subjects: [], i: 0, answers: {}, marked: {}, visited: {}, timeLeft: 0, timer: null, startEpoch: 0, submitted: false, maxMarks: 0 };
const $ = id => document.getElementById(id);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(r => r.json());
const cur = () => state.questions[state.i];
const NEG = { 1: "−⅓", 2: "−⅔" };

function show(name) {
  ["home", "loading", "exam", "result"].forEach(s => {
    const el = $(`screen-${s}`); el.classList.toggle("active", s === name);
    el.style.display = s === name ? (s === "loading" ? "flex" : "block") : "none";
  });
  window.scrollTo(0, 0);
}
function toast(msg) { const t = $("toast"); t.textContent = msg; t.style.display = "block"; setTimeout(() => t.style.display = "none", 3500); }
const fmt = sec => { sec = Math.max(sec, 0); const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60; return (h ? h + ":" : "") + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0"); };

// ── Figures (SVG drawn in the browser from a small JSON spec) ──────────
function svgWrap(w, h, body) { return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" font-family="Inter,Arial,sans-serif">${body}</svg>`; }
const LBL = 'style="paint-order:stroke;stroke:#fff;stroke-width:3px" font-size="12" fill="#1e293b" text-anchor="middle"';
function figGraph(f) {
  const S = 3.6, P = n => [f.pos[n][0] * S, f.pos[n][1] * S], R = 17;
  const has = new Set(f.edges.map(e => e[0] + ">" + e[1])); let body = `<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#334155"/></marker></defs>`;
  f.edges.forEach(([a, b, w]) => {
    const [x1, y1] = P(a), [x2, y2] = P(b);
    if (a === b) { body += `<path d="M${x1 - 8} ${y1 - R + 2} C${x1 - 30} ${y1 - 55} ${x1 + 30} ${y1 - 55} ${x1 + 8} ${y1 - R + 2}" fill="none" stroke="#334155" stroke-width="1.6" ${f.directed ? 'marker-end="url(#ar)"' : ""}/><text x="${x1}" y="${y1 - 44}" ${LBL}>${esc(w)}</text>`; return; }
    const dx = x2 - x1, dy = y2 - y1, L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L, nx = -uy, ny = ux;
    const curved = f.directed && has.has(b + ">" + a), off = curved ? 22 : 0;
    const sx = x1 + ux * R, sy = y1 + uy * R, ex = x2 - ux * (R + (f.directed ? 2 : 0)), ey = y2 - uy * (R + (f.directed ? 2 : 0));
    const cx = (sx + ex) / 2 + nx * off, cy = (sy + ey) / 2 + ny * off;
    body += `<path d="M${sx} ${sy} Q${cx} ${cy} ${ex} ${ey}" fill="none" stroke="#334155" stroke-width="1.6" ${f.directed ? 'marker-end="url(#ar)"' : ""}/>`;
    if (w !== "") body += `<text x="${(sx + ex) / 2 + nx * (off / 2 + 9)}" y="${(sy + ey) / 2 + ny * (off / 2 + 9) + 4}" ${LBL}>${esc(w)}</text>`;
  });
  f.nodes.forEach(n => {
    const [x, y] = P(n);
    body += `<circle cx="${x}" cy="${y}" r="${R}" fill="#fff" stroke="#0f172a" stroke-width="1.8"/>` + ((f.accept || []).includes(n) ? `<circle cx="${x}" cy="${y}" r="${R - 4}" fill="none" stroke="#0f172a" stroke-width="1.4"/>` : "")
      + `<text x="${x}" y="${y + 4.5}" font-size="13" font-weight="700" text-anchor="middle" fill="#0f172a">${esc(n)}</text>`;
    if (f.start === n) body += `<path d="M${x - R - 24} ${y} L${x - R - 2} ${y}" stroke="#334155" stroke-width="1.6" marker-end="url(#ar)"/>`;
  });
  return svgWrap(100 * S + 40, 100 * S + 40, `<g transform="translate(20,20)">${body}</g>`);
}
function figTree(f) {
  let x = 0, maxD = 0; const nodes = [], edges = [];
  (function walk(t, d, par) { if (!t) return; walk(t.l, d + 1, t); t._x = x++; t._d = d; maxD = Math.max(maxD, d); nodes.push(t); t._p = par; walk(t.r, d + 1, t); })(f.root, 0, null);
  nodes.forEach(n => { if (n._p) edges.push([n._p, n]); });
  const X = n => 30 + n._x * 40, Y = n => 28 + n._d * 54; let body = "";
  edges.forEach(([p, c]) => body += `<line x1="${X(p)}" y1="${Y(p)}" x2="${X(c)}" y2="${Y(c)}" stroke="#334155" stroke-width="1.6"/>`);
  nodes.forEach(n => body += `<circle cx="${X(n)}" cy="${Y(n)}" r="16" fill="#fff" stroke="#0f172a" stroke-width="1.8"/><text x="${X(n)}" y="${Y(n) + 4.5}" font-size="12.5" font-weight="700" text-anchor="middle">${esc(n.v)}</text>`);
  return svgWrap(x * 40 + 20, (maxD + 1) * 54 + 14, body);
}
function figBar(f) {
  const W = 60 + f.labels.length * 56, H = 250, mx = Math.max(...f.values) * 1.15 || 1; let body = `<line x1="44" y1="20" x2="44" y2="205" stroke="#334155"/><line x1="44" y1="205" x2="${W - 8}" y2="205" stroke="#334155"/>`;
  for (let t = 0; t <= 4; t++) { const v = mx * t / 4, y = 205 - 185 * t / 4; body += `<line x1="41" y1="${y}" x2="${W - 8}" y2="${y}" stroke="#e2e8f0"/><text x="38" y="${y + 4}" font-size="10" text-anchor="end" fill="#475569">${Math.round(v)}</text>`; }
  f.values.forEach((v, i) => { const h = 185 * v / mx, x = 58 + i * 56; body += `<rect x="${x}" y="${205 - h}" width="34" height="${h}" fill="#3b82f6"/><text x="${x + 17}" y="${198 - h}" font-size="11" text-anchor="middle" fill="#0f172a">${v}</text><text x="${x + 17}" y="222" font-size="11" text-anchor="middle" fill="#0f172a">${esc(f.labels[i])}</text>`; });
  if (f.ylabel) body += `<text x="44" y="12" font-size="11" fill="#475569">${esc(f.ylabel)}</text>`;
  return svgWrap(W, H, body);
}
function figGantt(f) {
  const T = Math.max(...f.segments.map(s => s[2])), W = 520, k = (W - 40) / T, col = ["#93c5fd", "#fca5a5", "#86efac", "#fcd34d", "#c4b5fd", "#f9a8d4"], names = [...new Set(f.segments.map(s => s[0]))];
  let body = ""; f.segments.forEach(([n, a, b]) => { body += `<rect x="${20 + a * k}" y="20" width="${(b - a) * k}" height="34" fill="${col[names.indexOf(n) % 6]}" stroke="#0f172a"/><text x="${20 + (a + b) / 2 * k}" y="42" font-size="12" font-weight="700" text-anchor="middle">${esc(n)}</text>`; });
  [...new Set(f.segments.flatMap(s => [s[1], s[2]]))].forEach(t => body += `<text x="${20 + t * k}" y="72" font-size="10" text-anchor="middle" fill="#475569">${t}</text>`);
  return svgWrap(W, 84, body);
}
function drawFigure(f) { try { return { graph: figGraph, tree: figTree, bar: figBar, gantt: figGantt }[f.kind](f); } catch (e) { return ""; } }

// ── Home ─────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  show("home");
  const c = state.cfg = await fetch("/config").then(r => r.json());
  $("ai-status").textContent = c.ai_ready ? `AI generation live · ${c.model} · ${c.batch} Q per call · API budget today ${c.budget.used}/${c.budget.cap} calls (≤${c.budget.rpm}/min)`
    : "ℹ️ No GEMINI_API_KEY (or daily budget used up) — papers are built from code-computed questions + real PYQs, so they still generate.";
  $("paper-note").textContent = `${c.paper.q} questions · ${c.paper.marks} marks · ${c.paper.minutes} minutes · MCQ (−⅓ / −⅔) · MSQ and NAT (no negative marking)`;
  const secs = c.subjects;
  const boxes = (id, list, on) => { $(id).innerHTML = ""; list.forEach((s, i) => { const l = document.createElement("label"); const o = on(s, i); l.className = "chapter-item" + (o ? " checked" : "");
    l.innerHTML = `<input type="checkbox" value="${s.key}" ${o ? "checked" : ""}> ${esc(s.name)}`; l.querySelector("input").addEventListener("change", e => l.classList.toggle("checked", e.target.checked)); $(id).appendChild(l); }); };
  boxes("prac-sections", secs, (s, i) => i === 1);
  boxes("pyq-sections", secs.filter(s => s.pyq > 0), () => true);
  const pills = (id, def) => { $(id).innerHTML = c.counts.map(n => `<button class="pill ${n === def ? "active" : ""}" data-count="${n}">${n}</button>`).join("");
    document.querySelectorAll(`#${id} .pill`).forEach(p => p.addEventListener("click", () => { document.querySelectorAll(`#${id} .pill`).forEach(x => x.classList.remove("active")); p.classList.add("active"); })); };
  pills("count-pills", 10); pills("pyq-count-pills", 5);
  $("pyq-paper").innerHTML = `<option value="">🎲 Fresh sample by subject (${c.pyq_total} keyed PYQs)</option>` + c.papers.map(p => `<option value="${p.id}">${esc(p.label)} — full paper (${p.n} Q)</option>`).join("");
  $("pyq-paper").addEventListener("change", () => $("pyq-subject-box").style.display = $("pyq-paper").value ? "none" : "block");
  $("pyq-fine").textContent = c.papers.length ? `Papers with an official key: ${c.papers.map(p => p.label).join(", ")}.` : "No PYQ bank found — run the tools/ pipeline first.";
  if (!c.papers.length) $("card-pyq").style.opacity = .5;
  $("btn-select-all").addEventListener("click", () => document.querySelectorAll("#prac-sections input").forEach(cb => { cb.checked = true; cb.closest("label").classList.add("checked"); }));
  $("full-desc").textContent = `Official pattern — ${c.paper.q} questions, ${c.paper.marks} marks, ${c.paper.minutes} minutes.`;
  $("full-list").innerHTML = ["<li>⏱ <b>One 180-minute clock</b> — General Aptitude + Computer Science tabs, move freely</li>", "<li class=\"sub\">• 10 Q General Aptitude (5 × 1 + 5 × 2)</li>", "<li class=\"sub\">• 55 Q core (25 × 1 + 30 × 2), all 10 syllabus sections</li>",
    "<li>✓ MCQ +m / −m/3 · MSQ exact match · NAT within range · no negative for MSQ/NAT</li>", "<li>🧮 On-screen calculator · numeric keypad · 5-colour palette</li>"].join("");
  $("btn-start-pyq").addEventListener("click", () => begin("pyq"));
  $("btn-start-practice").addEventListener("click", () => begin("section"));
  $("btn-start-full").addEventListener("click", () => begin("full"));
  $("btn-prev").addEventListener("click", () => go(state.i - 1));
  $("btn-next").addEventListener("click", () => go(state.i + 1, true));
  $("btn-clear").addEventListener("click", () => { delete state.answers[cur().id]; renderQuestion(); });
  $("btn-mark").addEventListener("click", () => { const id = cur().id; if (state.marked[id]) { state.marked[id] = false; renderQuestion(); } else { state.marked[id] = true; go(state.i + 1, true); } });
  $("btn-submit-block").addEventListener("click", () => { const un = state.questions.filter(q => !has(state.answers[q.id])).length; if (confirm(`${un} unanswered question(s). Submit the exam?`)) submitExam(); });
  $("btn-new-test").addEventListener("click", () => window.location.reload());
  $("btn-calc").addEventListener("click", () => $("calc").style.display = $("calc").style.display === "none" ? "block" : "none");
  $("calc-x").addEventListener("click", () => $("calc").style.display = "none");
  initCalc(); initKeypad();
});
const has = a => Array.isArray(a) ? a.length > 0 : a !== undefined && a !== "";

// ── Start / generation ───────────────────────────────────────────
async function begin(mode) {
  const box = mode === "pyq" ? "#pyq-sections" : "#prac-sections", paper = mode === "pyq" ? $("pyq-paper").value : "";
  const subjects = mode === "full" || paper ? [] : [...document.querySelectorAll(`${box} input:checked`)].map(c => c.value);
  if (mode !== "full" && !paper && !subjects.length) { alert("Please select at least one subject."); return; }
  const pill = document.querySelector(mode === "pyq" ? "#pyq-count-pills .pill.active" : "#count-pills .pill.active");
  const res = await post("/start", { mode, subjects, count: pill ? +pill.dataset.count : 10, paper });
  if (res.status !== "ok") { alert(res.error || "Could not start."); return; }
  $("exam-mode-label").textContent = res.plan.label;
  show("loading");
  if (res.pending > 0) { if (!await runGeneration(res.plan.total, res.pending)) return; }
  else { $("loading-title").textContent = "Loading paper"; $("progress-fill").style.width = "100%"; $("progress-label").textContent = `${res.plan.total} / ${res.plan.total}`; }
  await loadExam();
}
async function runGeneration(total, pending) {
  $("loading-title").textContent = "Writing & verifying your paper";
  const tips = ["💡 Each batch is written by Gemini and blind-solved by a second pass to catch wrong keys.", "🧮 Graph, tree and table questions have answers computed by code, not guessed.",
    "⏱ Real GATE: 180 minutes, 65 questions — about 1.8 minutes per mark.", "➖ MCQ has negative marking; MSQ and NAT do not — attempt them all."];
  let t = 0, done = total - pending; $("loading-tip").textContent = tips[0];
  const tt = setInterval(() => $("loading-tip").textContent = tips[++t % tips.length], 4000);
  let errors = 0, calls = 0;
  const upd = g => { $("progress-fill").style.width = `${Math.round(g / total * 100)}%`; $("progress-label").textContent = `${g} / ${total}`; }; upd(done);
  while (done < total && errors < 4 && calls++ < total + 4) {
    try { const r = await post("/generate-next"); if (r.error) { errors++; await sleep(1500); continue; }
      done = r.generated; upd(done); $("loading-sub").textContent = `Ready: ${done} of ${total} questions${r.fallback ? ` (${r.fallback} filled from code/PYQ bank to stay within API limits)` : ""}`; if (r.done) break; }
    catch (e) { errors++; await sleep(1500); }
  }
  clearInterval(tt);
  if (done < total) toast(`Only ${done} of ${total} questions could be prepared — starting with those.`);
  return true;
}
async function loadExam() {
  const d = await fetch("/questions").then(r => r.json());
  if (!d.questions || !d.questions.length) { alert("No questions available."); show("home"); return; }
  Object.assign(state, { questions: d.questions, subjects: d.subjects, answers: {}, marked: {}, visited: {}, submitted: false, i: 0, timeLeft: d.time_sec, startEpoch: Date.now(), maxMarks: d.max_marks });
  buildNav(); buildSubTabs(); renderQuestion(); startTimer(); show("exam");
}

// ── Exam ─────────────────────────────────────────────────────────
function buildNav() {
  const nav = $("q-nav"); nav.innerHTML = "";
  state.questions.forEach((q, i) => { const b = document.createElement("button"); b.className = "q-nav-btn"; b.id = `nav-${i}`; b.textContent = q.q_num; b.title = `${q.marks} mark`; b.addEventListener("click", () => go(i)); nav.appendChild(b); });
}
function buildSubTabs() {
  const el = $("sub-tabs"); el.innerHTML = state.subjects.map(s => `<button class="sec-tab" data-start="${s.start}">${esc(s.name)} <small>(${s.end - s.start})</small></button>`).join("");
  el.querySelectorAll(".sec-tab").forEach(b => b.addEventListener("click", () => go(+b.dataset.start)));
}
function go(i, fromNext) { if (i >= state.questions.length) { if (fromNext) toast("That was the last question — review, then Submit Exam."); return; } if (i < 0) return; state.i = i; renderQuestion(); }
function updateNav() {
  state.questions.forEach((q, i) => { const b = $(`nav-${i}`); if (!b) return;
    b.className = "q-nav-btn" + (state.marked[q.id] ? " marked" : "") + (has(state.answers[q.id]) ? " answered" : state.visited[q.id] ? " visited" : "") + (i === state.i ? " active" : ""); });
  document.querySelectorAll("#sub-tabs .sec-tab").forEach(b => { const s = state.subjects.find(x => x.start === +b.dataset.start); b.classList.toggle("current", state.i >= s.start && state.i < s.end); });
}
function renderContext(txt) {
  const el = $("q-context"); if (!txt) { el.style.display = "none"; return; }
  const rows = txt.split("\n").map(l => l.trim()).filter(Boolean).map(l => l.split("|").map(c => esc(c.trim())));
  el.innerHTML = rows.length >= 2 && rows[0].length >= 2 ? `<table class="ctx"><tr>${rows[0].map(c => `<th>${c}</th>`).join("")}</tr>${rows.slice(1).map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</table>` : esc(txt);
  el.style.display = "block";
}
function renderQuestion() {
  const q = cur(); state.visited[q.id] = true;
  $("q-counter").textContent = `Q ${q.q_num} of ${state.questions.length}`;
  $("q-section-tag").textContent = q.label ? `${q.label}` : q.subject === "ga" ? "General Aptitude" : "";
  const t = $("q-type-tag"); t.textContent = q.type.toUpperCase(); t.className = "type-tag " + q.type;
  $("q-marks-tag").textContent = q.type === "mcq" ? `+${q.marks} / ${NEG[q.marks]}` : `+${q.marks} / no negative`;
  renderContext(q.context);
  $("q-code").style.display = q.code ? "block" : "none"; $("q-code").textContent = q.code || "";
  $("q-figure").style.display = q.figure ? "block" : "none"; $("q-figure").innerHTML = q.figure ? drawFigure(q.figure) : "";
  $("q-text").textContent = q.question; $("q-text").style.display = q.question ? "block" : "none";
  $("q-img").style.display = q.img ? "block" : "none"; if (q.img) $("q-img").src = q.img;
  const opts = $("q-options"), nat = $("nat-box"); opts.innerHTML = "";
  if (q.type === "nat") { opts.style.display = "none"; nat.style.display = "block"; $("nat-input").value = state.answers[q.id] || ""; }
  else {
    nat.style.display = "none"; opts.style.display = "flex";
    const sel = a => q.type === "msq" ? (state.answers[q.id] || []).includes(a) : state.answers[q.id] === a;
    Object.keys(q.options).sort().forEach(k => {
      const b = document.createElement("button"); b.className = "option-btn" + (q.type === "msq" ? " multi" : "") + (sel(k) ? " selected" : "");
      b.innerHTML = `<span class="opt-label">${k.toUpperCase()}</span><span class="opt-text">${q.img ? "Option " + k.toUpperCase() : esc(q.options[k])}</span>`;
      b.addEventListener("click", () => {
        if (q.type === "msq") { const s = new Set(state.answers[q.id] || []); s.has(k) ? s.delete(k) : s.add(k); state.answers[q.id] = [...s].sort(); }
        else state.answers[q.id] = k;
        renderQuestion(); });
      opts.appendChild(b);
    });
  }
  $("btn-prev").disabled = state.i === 0;
  $("btn-mark").classList.toggle("on", !!state.marked[q.id]);
  $("btn-mark").textContent = state.marked[q.id] ? "Unmark Review" : "Mark for Review & Next";
  $("btn-next").textContent = state.i + 1 >= state.questions.length ? "Save" : "Save & Next →";
  updateNav();
}
function initKeypad() {
  const keys = ["7", "8", "9", "⌫", "4", "5", "6", "C", "1", "2", "3", "−", "0", ".", "e"]; const kp = $("keypad");
  keys.forEach(k => { const b = document.createElement("button"); b.textContent = k; b.addEventListener("click", () => {
    const inp = $("nat-input"); let v = inp.value;
    if (k === "⌫") v = v.slice(0, -1); else if (k === "C") v = ""; else if (k === "−") v = v.startsWith("-") ? v.slice(1) : "-" + v; else if (k === "e") v += "e"; else v += k;
    inp.value = v; setNat(v); }); kp.appendChild(b); });
  $("nat-input").addEventListener("input", e => setNat(e.target.value.replace(/[^0-9.eE+\-]/g, "")));
}
function setNat(v) { const q = cur(); if (v === "") delete state.answers[q.id]; else state.answers[q.id] = v; updateNav(); }
function initCalc() {
  const keys = ["7", "8", "9", "/", "sqrt(", "4", "5", "6", "*", "log(", "1", "2", "3", "-", "ln(", "0", ".", "^", "+", "exp(", "(", ")", "π", "sin(", "cos(", "C", "⌫", "tan(", "mod", "="];
  const d = $("calc-disp"); let expr = "";
  keys.forEach(k => { const b = document.createElement("button"); b.textContent = k.replace("(", ""); b.addEventListener("click", () => {
    if (k === "C") expr = ""; else if (k === "⌫") expr = expr.replace(/(sqrt\(|log\(|ln\(|exp\(|sin\(|cos\(|tan\(|.)$/, "");
    else if (k === "=") { try { let e = expr.replace(/π/g, "Math.PI").replace(/\^/g, "**").replace(/mod/g, "%").replace(/sqrt\(/g, "Math.sqrt(").replace(/log\(/g, "Math.log10(").replace(/ln\(/g, "Math.log(").replace(/exp\(/g, "Math.exp(").replace(/sin\(/g, "Math.sin(").replace(/cos\(/g, "Math.cos(").replace(/tan\(/g, "Math.tan(");
      if (/[^0-9+\-*\/().%\s]/.test(e.replace(/Math\.(PI|sqrt|log10|log|exp|sin|cos|tan)/g, ""))) throw 0; const v = Function('"use strict";return (' + e + ")")(); expr = String(+(+v).toPrecision(12)); } catch (x) { expr = ""; d.value = "Error"; return; } }
    else expr += k;
    d.value = expr || "0"; }); $("calc-keys").appendChild(b); });
}
function startTimer() { clearInterval(state.timer); tick(); state.timer = setInterval(() => { state.timeLeft--; tick(); if (state.timeLeft <= 0) { toast("⏰ Time is up — submitting your exam"); submitExam(); } }, 1000); }
function tick() { $("timer-display").textContent = fmt(state.timeLeft); $("timer-box").className = "timer-box" + (state.timeLeft <= 300 ? " timer-danger" : state.timeLeft <= 900 ? " timer-warn" : ""); }

// ── Submit / result ──────────────────────────────────────────────
async function submitExam() {
  if (state.submitted) return; state.submitted = true; clearInterval(state.timer); show("loading");
  $("loading-title").textContent = "Evaluating your paper…"; $("loading-sub").textContent = "Applying GATE marking scheme…"; $("progress-fill").style.width = "85%"; $("progress-label").textContent = "";
  const r = await post("/submit", { answers: state.answers, time_taken_sec: Math.round((Date.now() - state.startEpoch) / 1000) });
  if (r.error) { alert("Submission error: " + r.error); return; }
  renderResult(r); show("result");
}
function renderResult(r) {
  $("result-grade").textContent = `${r.label} · ${r.grade}`;
  $("res-score").textContent = `${r.score}/${r.total_marks}`; $("res-pct").textContent = `${r.percent}%`; $("res-correct").textContent = r.correct; $("res-wrong").textContent = r.wrong;
  $("res-acc").textContent = `${r.accuracy}%`; $("res-time").textContent = `${Math.floor(r.time_taken_sec / 60)}m ${r.time_taken_sec % 60}s`;
  $("sec-table").innerHTML = `<tr><th>Subject</th><th>Attempted</th><th>Correct</th><th>Wrong</th><th>Score</th><th>Accuracy</th></tr>` + r.section_summary.map(s => {
    const c = s.accuracy >= 70 ? "#16a34a" : s.accuracy >= 45 ? "#d97706" : "#dc2626";
    return `<tr><td>${esc(s.section)}</td><td>${s.attempted}/${s.total}</td><td class="pos">${s.correct}</td><td class="neg">${s.wrong}</td><td><b>${s.score}</b>/${s.max}</td><td style="color:${c}"><b>${s.accuracy}%</b></td></tr>`; }).join("");
  if (r.weak.length) { $("weak-block").style.display = "block"; $("weak-chapters").innerHTML = r.weak.map(w => `<span class="weak-tag">📌 ${esc(w)}</span>`).join(""); }
  const s = r.sources; $("result-note").textContent = `📝 Paper mix: ${s.ai} AI-written (blind-solve verified) · ${s.code} code-computed (answers calculated, not guessed) · ${s.pyq} real PYQs with official keys. Generated keys are checked, but report anything that looks off.`;
  $("review-list").innerHTML = r.review.map(it => {
    const cls = it.is_correct === null ? "skipped" : it.is_correct ? "correct" : "wrong";
    const badge = it.is_correct === null ? `<span class="review-badge badge-skipped">— Skipped</span>` : it.is_correct ? `<span class="review-badge badge-correct">✓ +${it.score}</span>` : `<span class="review-badge badge-wrong">✗ ${it.score}</span>`;
    const opts = it.type !== "nat" && !it.img ? Object.keys(it.options).sort().map(k => { const ks = it.key.split(", "), us = it.user.split(", "); const c = ks.includes(k.toUpperCase()) ? "correct-ans" : us.includes(k.toUpperCase()) ? "user-wrong" : "";
      return `<div class="review-opt ${c}">(${k}) ${esc(it.options[k])}</div>`; }).join("") : "";
    return `<div class="review-item ${cls}"><div class="review-header">${badge}<span>Q${it.q_num} · ${esc(it.subject)} · ${it.type.toUpperCase()} · ${it.marks}M <span class="src-chip">${esc(it.label || (it.src === "ai" ? "AI" : "Code-verified"))}</span></span></div>
      <div class="review-body">${it.context ? `<div class="review-ctx">${esc(it.context)}</div>` : ""}${it.code ? `<pre class="review-code">${esc(it.code)}</pre>` : ""}${it.figure ? `<div class="review-fig">${drawFigure(it.figure)}</div>` : ""}
      ${it.img ? `<img class="q-img" src="${it.img}">` : `<div class="review-q">${esc(it.question)}</div>`}<div class="review-opts">${opts}</div>
      <div class="review-key">Your answer: <b style="color:${it.is_correct ? "#16a34a" : "#dc2626"}">${esc(it.user || "—")}</b> · Correct: <b>${esc(it.key)}</b></div>
      ${it.explanation ? `<div class="review-expl">💡 ${esc(it.explanation)}</div>` : ""}</div></div>`; }).join("");
}
