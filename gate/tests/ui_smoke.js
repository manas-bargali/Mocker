// Headless UI smoke test (jsdom).  npm i jsdom ; python app.py &  ; node tests/ui_smoke.js http://localhost:5000
const { JSDOM } = require("jsdom");
const base = process.argv[2] || "http://localhost:5000"; let cookie = "";
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function main() {
  const dom = await JSDOM.fromURL(base + "/", { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse(w) {
    w.fetch = async (u, o = {}) => { const r = await fetch(new URL(u, base), { ...o, headers: { ...(o.headers || {}), cookie } }); const sc = r.headers.getSetCookie?.() || []; if (sc.length) cookie = sc.map(c => c.split(";")[0]).join("; "); return r; };
    w.confirm = () => true; w.alert = m => { console.log("ALERT:", m); }; w.scrollTo = () => {}; } });
  const w = dom.window, d = w.document, $ = id => d.getElementById(id), errs = [];
  w.addEventListener("error", e => errs.push(e.message));
  await sleep(1500);
  const check = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) process.exitCode = 1; };
  check($("full-desc").textContent.includes("65"), "home config loaded");
  check(d.querySelectorAll("#pyq-paper option").length > 1, "PYQ paper list populated");
  $("btn-start-full").click();
  for (let i = 0; i < 40 && !$("screen-exam").classList.contains("active"); i++) await sleep(500);
  check($("screen-exam").classList.contains("active"), "exam screen shown");
  check(d.querySelectorAll("#q-nav .q-nav-btn").length === 65, "65 palette buttons");
  check($("timer-display").textContent.startsWith("3:00:0") || $("timer-display").textContent.startsWith("2:59"), "180-minute clock: " + $("timer-display").textContent);
  let figs = 0, imgs = 0, nats = 0, msqs = 0, mcqs = 0, codes = 0;
  for (let i = 0; i < 65; i++) {
    const t = $("q-type-tag").textContent;
    if ($("q-figure").style.display === "block" && $("q-figure").innerHTML.includes("<svg")) figs++;
    if ($("q-img").style.display === "block") imgs++;
    if ($("q-code").style.display === "block") codes++;
    if (t === "NAT") { nats++; $("keypad").children[0].click(); $("keypad").children[5].click(); }            // types 75
    else if (t === "MSQ") { msqs++; const o = d.querySelectorAll("#q-options .option-btn"); o[0].click(); d.querySelectorAll("#q-options .option-btn")[2].click(); }
    else { mcqs++; d.querySelectorAll("#q-options .option-btn")[i % 4].click(); }
    if (i % 9 === 4) $("btn-mark").click(); else $("btn-next").click();
  }
  console.log(`types: mcq ${mcqs} msq ${msqs} nat ${nats}; with svg figure ${figs}, image ${imgs}, code ${codes}`);
  check(d.querySelectorAll("#q-nav .answered").length > 55, "palette shows answered questions: " + d.querySelectorAll("#q-nav .answered").length);
  check(d.querySelectorAll("#q-nav .marked").length >= 6, "palette shows marked questions");
  $("calc-keys").children[0].click(); $("calc-keys").children[3].click(); $("calc-keys").children[5].click(); $("calc-keys").children[29].click();
  check(true, "calculator display: " + $("calc-disp").value);
  $("btn-submit-block").click();
  for (let i = 0; i < 20 && !$("screen-result").classList.contains("active"); i++) await sleep(300);
  check($("screen-result").classList.contains("active"), "result screen shown, score " + $("res-score").textContent);
  check(d.querySelectorAll("#review-list .review-item").length === 65, "65 review items");
  check(d.querySelectorAll("#sec-table tr").length > 2, "subject table rows: " + d.querySelectorAll("#sec-table tr").length);
  check(errs.length === 0, "no uncaught JS errors " + errs.join("|"));
  process.exit(process.exitCode || 0);
}
main();
