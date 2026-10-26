/* Retrofit Check: the page. Talks to retrofit/server.py; every answer comes from a run of the agent.
   The card reads only the answer JSON (retrofit/schema.py); the map also reads the run's result for roof planes and areas. */

const $ = (id) => document.getElementById(id);
const D2R = Math.PI / 180, R = 6378137;
const C = (h, a = 1) => Cesium.Color.fromCssColorString(h).withAlpha(a);
const INK = "#13202B", YELLOW = "#FFD21F", LAV = "#A79FE6", CORAL = "#FF5A5F", TEAL = "#2EC4A0";
const ST_CLASS = { allowed: "y", allowed_with_conditions: "c", check_with_council: "c", needs_permission: "n", needs_consent: "n" };
const ST_TAG = { allowed: "Allowed", allowed_with_conditions: "Allowed, with conditions", check_with_council: "Check with the council", needs_permission: "Needs permission", needs_consent: "Needs consent" };
const REC_CLASS = { "Worth getting quotes": "go", "Ask the council first": "ask", "Probably not worth it for this house": "no" };
// One action per next step; no button when the advice is not to go ahead.
const CTA = { "Worth getting quotes": ["Find MCS certified installers", "https://mcscertified.com/find-an-installer/"],
  "Ask the council first": ["Find your council", "https://www.gov.uk/find-local-council"] };
const FACING = { N: "north", NE: "north east", E: "east", SE: "south east", S: "south", SW: "south west", W: "west", NW: "north west" };
const AGENT_OF = { start: "planner", decision: "planner", intake: "planner", thought: "planner", note: "planner", done: "planner", error: "planner",
  tool_start: "analyst", tool_end: "analyst", house: "analyst", zetaris: "analyst", requery: "analyst", challenge: "evaluator",
  critic: "critic", memory_recall: "memory", memory_write: "memory", answer: "reporter", answer_update: "reporter" };
const STATUS_WORD = { retrying: "retrying", needs_revision: "needs revision", blocked: "blocked", fallback: "fallback", failed: "failed" };

const STATIC = !!window.STATIC_SITE;   // docs/: replays recorded runs, no server
const api = {
  area: (e) => (STATIC ? `samples/areas/${e}.json` : `/api/area/${e}`),
  run: (n) => (STATIC ? `samples/${n}.json` : `/api/runs/${encodeURIComponent(n)}`),
  examples: () => (STATIC ? "samples/index.json" : "/api/examples"),
};
let viewer, state = { answer: null, result: null, old: false, open: false, det: {}, request: null, live: false };
const S = { center: null, hpr: null, home: null, house: [], overlay: [] };
let tapMode = false, evCount = 0, source = null;

/* ---------------- map ---------------- */
const local = (o) => { const k = Math.cos(o[1] * D2R); return { to: (p) => [(p[0] - o[0]) * D2R * R * k, (p[1] - o[1]) * D2R * R], back: (p) => [o[0] + p[0] / (R * k) / D2R, o[1] + p[1] / R / D2R] }; };
function ring(coords) { const c = coords.slice(); if (c.length > 1 && c[0][0] === c[c.length - 1][0] && c[0][1] === c[c.length - 1][1]) c.pop(); return c; }
function centroid(poly) { let a = 0, x = 0, y = 0; for (let i = 0; i < poly.length; i++) { const p = poly[i], q = poly[(i + 1) % poly.length], cr = p[0] * q[1] - q[0] * p[1]; a += cr; x += (p[0] + q[0]) * cr; y += (p[1] + q[1]) * cr; } return [x / (3 * a), y / (3 * a)]; }
function clipHalf(poly, n) { const out = []; for (let i = 0; i < poly.length; i++) { const a = poly[i], b = poly[(i + 1) % poly.length], da = a[0] * n[0] + a[1] * n[1], db = b[0] * n[0] + b[1] * n[1]; if (da >= 0) out.push(a); if ((da >= 0) !== (db >= 0)) { const t = da / (da - db); out.push([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]); } } return out; }
let CLASSIFY = () => Cesium.ClassificationType.CESIUM_3D_TILE;  // flat OSM map when there is no Google key
const drape = (lonlat, color, alpha) => viewer.entities.add({ polygon: { hierarchy: Cesium.Cartesian3.fromDegreesArray(lonlat.flat()), material: C(color, alpha), classificationType: CLASSIFY() } });
function drapeGeo(geom, color, alpha) {
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.type === "MultiPolygon" ? geom.coordinates : [];
  return polys.map((p) => viewer.entities.add({ polygon: { hierarchy: new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(p[0].flat()), p.slice(1).map((h) => new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(h.flat())))), material: C(color, alpha), classificationType: CLASSIFY() } }));
}
const clearOverlay = () => { S.overlay.forEach((e) => viewer.entities.remove(e)); S.overlay = []; };
const applyView = () => { if (S.center && S.hpr) viewer.camera.lookAt(S.center, S.hpr); };
function readHpr() { if (!S.center) return; const cam = viewer.camera; S.hpr = new Cesium.HeadingPitchRange(cam.heading, cam.pitch, Cesium.Cartesian3.distance(cam.positionWC, S.center)); }
$("rl").onclick = () => { readHpr(); if (S.hpr) { S.hpr.heading -= 30 * D2R; applyView(); } };
$("rr").onclick = () => { readHpr(); if (S.hpr) { S.hpr.heading += 30 * D2R; applyView(); } };
$("zi").onclick = () => { readHpr(); if (S.hpr) { S.hpr.range = Math.max(30, S.hpr.range * 0.75); applyView(); } };
$("zo").onclick = () => { readHpr(); if (S.hpr) { S.hpr.range = Math.min(1500, S.hpr.range * 1.33); applyView(); } };
$("reset").onclick = () => { if (S.home) { S.hpr = Cesium.HeadingPitchRange.clone(S.home); viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(S.center, 12), { offset: S.hpr, duration: 1.2, complete: applyView }); } };

async function groundAt(lon, lat, fb) { if (!window.GOOGLE_MAPS_API_KEY) return Cesium.Cartesian3.fromDegrees(lon, lat, 0); try { const r = await viewer.scene.clampToHeightMostDetailed([Cesium.Cartesian3.fromDegrees(lon, lat, 800)]); if (r && r[0]) return r[0]; } catch (e) { /* fallback */ } return Cesium.Cartesian3.fromDegrees(lon, lat, fb); }

async function showHouse(h) {
  viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
  S.house.forEach((e) => viewer.entities.remove(e)); S.house = []; clearOverlay();
  S.coords = ring(h.coords); S.lonlat = [+h.lon, +h.lat];
  S.house.push(drape(S.coords, LAV, 0.75));
  S.center = await groundAt(h.lon, h.lat, 90);
  const size = Math.sqrt(Math.max(60, h.footprint_m2 || 120));
  const flat = !window.GOOGLE_MAPS_API_KEY;   // the flat OSM map reads better from closer and higher
  S.home = new Cesium.HeadingPitchRange(0, (flat ? -60 : -40) * D2R, flat ? Math.max(70, size * 6) : Math.max(110, size * 9));
  S.hpr = Cesium.HeadingPitchRange.clone(S.home);
  viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(S.center, 12), { offset: S.hpr, duration: 2.2, complete: applyView });
}
function aimHome(az) { if (!S.home) return; S.home.heading = ((az + 180) % 360) * D2R; S.hpr = Cesium.HeadingPitchRange.clone(S.home); viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(S.center, 12), { offset: S.hpr, duration: 1.4, complete: applyView }); }

// Map labels are the film's dark pills.
const mapLabel = (text, height) => viewer.entities.add({ position: Cesium.Cartesian3.fromDegrees(S.lonlat[0], S.lonlat[1], height ?? (window.GOOGLE_MAPS_API_KEY ? 70 : 5)), label: {
  text, font: "600 15px IBM Plex Sans, sans-serif", fillColor: Cesium.Color.WHITE, showBackground: true, backgroundColor: C(INK, 0.95),
  backgroundPadding: new Cesium.Cartesian2(12, 7), pixelOffset: new Cesium.Cartesian2(0, -30), disableDepthTestDistance: Number.POSITIVE_INFINITY } });

/* What the solar answer looks like on the house: the sunny slope, or the listed building */
async function overlayFor(open) {
  clearOverlay();
  const res = state.result, a = state.answer;
  if (!open || !res || !a || !S.coords) return;
  const s = a.solar, o = S.coords[0], L = local(o), pts = S.coords.map(L.to), c0 = centroid(pts);
  if (s.numbers && s.numbers.facing && s.status !== "needs_consent") {
    const plane = (res.planes || []).find((p) => p.facing === s.numbers.facing);
    const az = plane ? +plane.azimuth_deg : 180, n = [Math.sin(az * D2R), Math.cos(az * D2R)];
    const rel = pts.map((p) => [p[0] - c0[0], p[1] - c0[1]]);
    const sunny = clipHalf(rel, n), other = clipHalf(rel, [-n[0], -n[1]]);
    if (sunny.length > 2) S.overlay.push(drape(sunny.map((p) => L.back([p[0] + c0[0], p[1] + c0[1]])), YELLOW, 0.85));
    if (other.length > 2) S.overlay.push(drape(other.map((p) => L.back([p[0] + c0[0], p[1] + c0[1]])), LAV, 0.55));
    S.overlay.push(mapLabel(`${cap(FACING[s.numbers.facing] || s.numbers.facing)} roof${plane ? " · " + plane.pitch_deg + "°" : ""} · indicative`));
    aimHome(az);
    return;
  }
  const area = (res.areas || []).find((x) => (s.status === "needs_consent" ? /listed/.test(x.dataset) : x.dataset === "conservation-area"));
  if (!area || !area.entity) return;
  try {
    const g = await (await fetch(api.area(area.entity))).json();
    if (state.result !== res) return;
    S.overlay.push(...drapeGeo(s.status === "needs_consent" ? g.fill : g.edge, s.status === "needs_consent" ? CORAL : TEAL, s.status === "needs_consent" ? 0.55 : 0.95));
    S.overlay.push(mapLabel(s.status === "needs_consent" ? "Listed building" : `${g.name || "Conservation area"}`, 60));
  } catch (e) { trace({ type: "error", agent_name: "planner", status: "failed", text: "area outline did not load: " + e }); }
}

/* ---------------- panel ---------------- */
const fmtDate = (iso) => { if (!iso) return ""; const d = new Date(String(iso).slice(0, 10)); return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);
const gbp = (n) => "£" + Number(n).toLocaleString("en-GB");
const range = (r, f = (x) => x) => (r && r.length === 2 ? `${f(r[0])} to ${f(r[1])}` : "");
const SUN = `<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="#F0A23A"/></svg>`;

function factsLine(a) {
  const f = Object.fromEntries((a.house_facts || []).map((x) => [x.key, x]));
  const bits = [];
  if (f.listed) bits.push(f.listed.value);
  if (f.conservation_area) {
    const ca = String(f.conservation_area.value);
    bits.push(ca === "None" ? "not in a conservation area" : / \(\d{4}\)$/.test(ca) ? ca.replace(/ \((\d{4})\)$/, " conservation area, $1") : /conservation area/i.test(ca) ? ca : `${ca} conservation area`);
  }
  const roof = f.roof && /^([a-z ]+) slope, ([\d.]+)°/.exec(f.roof.value || "");
  if (roof) bits.push(`${roof[1]} roof ${roof[2]}°`);
  if (f.electricity_use && f.electricity_use.value) bits.push(`${f.electricity_use.value} (you)`);
  return bits.join(" · ");
}

function renderFacts() {
  const a = state.answer; if (!a) return;
  $("factsLine").textContent = factsLine(a);
  $("factList").innerHTML = (a.house_facts || []).map((f) => `<div class="f${f.from_owner ? " you" : ""}"><dt>${esc(f.label)}</dt>
    <dd>${esc(f.value || "Not given yet")}<span class="s">${esc(f.source)}${f.date ? ", " + esc(fmtDate(f.date)) : ""}</span></dd></div>`).join("");
  const owner = a.owner || {};
  if (owner.elec_kwh && document.activeElement !== $("elec")) $("elec").value = Math.round(owner.elec_kwh);
}

function chain(s) {
  const listed = s.facts.find((f) => f.fact === "listed"), ca = s.facts.find((f) => f.fact === "conservation-area");
  const bits = ["this house", listed ? (listed.value === "no" ? "not listed" : `listed: ${listed.value}`) : null, ca ? ca.value : null,
    ...s.rules.map((r) => r.clause), s.status_text];
  return bits.filter(Boolean).map(esc).join(" → ");
}

const IF_YES = { check_with_council: "If the council says yes:", needs_permission: "If you get planning permission:", needs_consent: "If you get listed building consent:" };

// The one condition an owner must know, from this house's facts: which walls face a road, or the roof rule.
function condition(a) {
  const s = a.solar, rule = (id) => s.rules.find((r) => r.id === id);
  if (s.status !== "allowed" && s.status !== "allowed_with_conditions") return s.lines.one;
  const walls = ((a.house_facts || []).find((f) => f.key === "road_walls") || {}).value || "";
  const dirs = [...new Set(String(walls).split(/,\s*/).filter((w) => / to /.test(w)).map((w) => w.replace(/ to .*$/, "").trim()))];
  if (rule("solar-ca-wall") && dirs.length) {
    const list = dirs.length > 1 ? `${dirs.slice(0, -1).join(", ")} or ${dirs[dirs.length - 1]}` : dirs[0];
    return `Not on the ${list} wall: ${dirs.length > 1 ? "they face" : "it faces"} a road. The roof is fine.`;
  }
  const r = rule("solar-ca-wall") || rule("solar-pitched");
  return r ? r.plain : s.lines.one;
}

const details = (key, label, body) => `<details class="x" data-k="${key}"${state.det[key] ? " open" : ""}><summary>${label}</summary><div class="xb">${body}</div></details>`;

function sources(s) {
  const rules = s.rules.map((r) => `<li class="src"><b>${esc(r.clause)}</b>, in force ${esc(fmtDate(r.in_force))}${r.amended_by ? ", last change " + esc(r.amended_by) : ""}. ${esc(r.plain || "")} ${/^https?:/.test(r.source_url || "") ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">Read the rule</a>` : ""}</li>`);
  const facts = s.facts.map((f) => { const url = /^https?:/.test(f.source || ""); return `<li class="src"><b>${esc(f.fact)}</b>: ${esc(String(f.value).replace(/\.$/, ""))}. ${url ? `<a href="${esc(f.source)}" target="_blank" rel="noopener">Source</a>` : esc(f.source)}${f.date ? ", " + esc(fmtDate(f.date)) : ""}</li>`; });
  return `<ul class="srcs">${[...rules, ...facts].join("")}</ul>`;
}

// The answer as a stack: status and condition, cost and payback, the next step, then sources and limits.
// state.open is "Why this answer" (demo.js opens it); the other details keep their state across re-renders.
function renderCard() {
  const a = state.answer;
  if (state.old) { $("card").innerHTML = `<div class="card"><p class="old">This recording comes from an older version of the app, so the card cannot show it. Run the check again.</p></div>`; return; }
  if (!a) { $("card").innerHTML = ""; return; }
  state.det.why = state.open;
  const s = a.solar, l = s.lines || {}, n = s.numbers || {}, conf = s.confidence || {}, allowed = /^allowed/.test(s.status);
  const pct = Math.round((conf.score || 0) * 100);
  const who = s.written_by === "nemotron" ? `Explained by Nemotron via Nightshift, checked by ${esc(s.checked_by || "code")}.`
    : `Written from the rules in code.${state.live ? " Nemotron is rewriting it now." : ""}`;
  const addElec = !s.usage && !STATIC && !state.replay && n.kwh_year;
  const tag = ST_TAG[s.status] || s.status_text;

  const why = [
    allowed && l.one ? `<p class="roofLine">${esc(l.one)}</p>` : "",
    s.usage ? `<p>${esc(s.usage.text)}</p>` : "",
    `<p>${esc(l.why)}</p>`, `<div class="chain">${chain(s)}</div>`,
    `<div class="conf"><span>Confidence</span><span class="bar" role="img" aria-label="Confidence ${esc(conf.level)}, ${pct} of 100"><i style="width:${pct}%"></i></span></div>`,
    `<p class="sub">${esc(conf.text || cap(conf.level))}</p>`,
  ].join("");
  const status = `<section class="card" aria-label="Solar panels">
    <div class="cardTop"><span class="sun">${SUN}</span><h3>Solar panels</h3><span class="tag ${ST_CLASS[s.status] || "c"}">${esc(tag)}</span></div>
    <p class="cond">${esc(condition(a))}</p>
    ${s.status_text !== tag ? `<p class="sub">${esc(s.status_text)}</p>` : ""}
    ${details("why", "Why this answer", why)}
  </section>`;

  let money = "";
  if (n.cost_gbp) {
    const figs = [[range(n.cost_gbp, gbp), "to install"]];
    if (n.payback_years) figs.push([`${range(n.payback_years)} years`, "to pay back"]);
    else if (n.value_gbp_year) figs.push([range(n.value_gbp_year, gbp), "value a year"]);
    const basis = s.usage ? `For the ${Number(s.usage.elec_kwh).toLocaleString("en-GB")} kWh a year you use.`
      : n.value_gbp_year ? `For a home with typical use (Ofgem).${addElec ? ` <button class="link" id="addElec" type="button">Add your electricity use</button>` : ""}` : "";
    money = `<section class="card" aria-label="Cost and payback">
      <h3>Cost and payback</h3>
      ${IF_YES[s.status] ? `<p class="ifYes">${IF_YES[s.status]}</p>` : ""}
      <div class="figs">${figs.map(([v, k]) => `<div class="fig"><b>${esc(v)}</b><span>${k}</span></div>`).join("")}</div>
      ${basis ? `<p class="sub">${basis}</p>` : ""}
      ${n.payback_years ? details("money", "More about the money", `${n.value_gbp_year ? `<div class="money"><span>Value a year</span><span>${esc(range(n.value_gbp_year, gbp))}</span></div>` : ""}<p>${esc(l.cost)}</p>`) : `<p class="sub">${esc(l.cost)}</p>`}
    </section>`;
  }

  const rec = s.recommendation, cta = CTA[rec];
  const step = `<section class="card step rc-${REC_CLASS[rec] || "ask"}" aria-label="Next step">
    <span class="eye">Next step</span>
    ${rec ? `<h3>${esc(rec)}</h3>` : ""}
    <p>${esc(s.next_step)}</p>
    ${cta ? `<a class="cta" href="${cta[1]}" target="_blank" rel="noopener">${cta[0]} <span aria-hidden="true">↗</span><span class="sr"> (opens in a new tab)</span></a>` : ""}
  </section>`;

  const more = `<details class="more" data-k="src"${state.det.src ? " open" : ""}><summary>Sources and limits</summary><div class="xb">
    ${sources(s)}<ul class="lims">${(s.limitations || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul><div class="who">${who}</div></div></details>`;

  $("card").innerHTML = status + money + step + more;
  $("card").querySelectorAll("details[data-k]").forEach((d) => d.addEventListener("toggle", () => { state.det[d.dataset.k] = d.open; if (d.dataset.k === "why") state.open = d.open; }));
  if ($("addElec")) $("addElec").onclick = () => { openFacts(true); $("elec").focus(); $("facts").scrollIntoView({ block: "nearest" }); };
}

function renderAll() {
  const a = state.answer;
  const day = (state.result && state.result.today) || (a && /^(\d{4})(\d{2})(\d{2})/.test(a.trace_id || "") ? a.trace_id.replace(/^(\d{4})(\d{2})(\d{2}).*/, "$1-$2-$3") : null);
  if (a) { renderFacts(); $("foot").textContent = `Checked ${day ? fmtDate(day) : "on an unknown date"}. Rules for England, demo data for London. The rules decide the answer in code; the agents plan, challenge the evidence and explain. Not legal or financial advice.`; }
  renderCard();
}

function openFacts(open) { $("facts").classList.toggle("hid", !open); $("factsToggle").setAttribute("aria-expanded", String(open)); }

/* ---------------- How we checked ---------------- */
function trace(e) {
  evCount++; $("traceCount").textContent = `${evCount} steps`;
  const agent = e.agent_name || AGENT_OF[e.type] || (e.type === "model" && String(e.role).startsWith("critic") ? "critic" : e.type === "model" ? "reporter" : "planner");
  let kind = "", txt = "", extra = "", tag = "";
  switch (e.type) {
    case "start": txt = `Run ${e.run_id} started`; break;
    case "tool_start": kind = "step"; txt = `${e.tool} → ${e.source}`; break;
    case "tool_end": kind = "step"; txt = `${e.tool} ${e.ok ? "done" : "failed: " + (e.error || "")}${e.seconds !== undefined ? ` (${e.seconds} s)` : ""}`; break;
    case "house": txt = `Found the house ${e.house_id}`; break;
    case "zetaris": kind = "zetaris"; txt = `${e.purpose || "query"} · ${e.rows ?? "no"} rows · ${e.seconds} s`; extra = `<details><summary>SQL</summary><pre>${esc(e.sql)}${e.error ? "\n\nERROR " + esc(e.error) : ""}</pre></details>`; break;
    case "model": kind = "nemotron"; txt = `${e.role} · ${e.ok ? (e.routed_model || e.model) + " · " + e.seconds + " s · receipt " + (e.receipt_id || "none") : "no answer after " + e.seconds + " s: " + (e.error || "").slice(0, 90)}`; break;
    case "critic": txt = `Critic, round ${e.round}: ${e.ok ? "accepted" : "rejected: " + (e.problems || []).join("; ")}`; break;
    case "memory_recall": kind = "h-mem"; txt = `Recall: ${e.memories && e.memories.length ? e.memories.map((m) => m.content).join(" · ") : "nothing yet"}`; break;
    case "memory_write": kind = "h-mem"; txt = `Remember ${e.kind}: ${e.content}${e.result && e.result.superseded ? " (replaces: " + e.result.superseded.content + ")" : ""}`; break;
    case "intake": txt = `Read your note: ${JSON.stringify(e.understood)}`; break;
    case "challenge": tag = `<span class="tag challenge">challenge</span>`; txt = e.text; break;
    case "requery": tag = e.ok === false || e.status === "fallback" ? `<span class="tag soft">not settled</span>` : `<span class="tag again">checked again</span>`; kind = "zetaris"; txt = `${e.about}: ${e.text}`; break;
    case "answer": txt = e.answer ? `Answer: ${e.answer.solar.status_text} · ${e.answer.solar.recommendation || ""}` : "Answer from the rules"; break;
    case "answer_update": kind = "nemotron"; txt = "Nemotron's plain words passed the checks"; break;
    case "done": txt = `Done in ${e.seconds} s`; break;
    default: txt = e.text || e.output_summary || e.type;
  }
  if (!tag && STATUS_WORD[e.status]) tag = `<span class="tag ${e.status === "failed" || e.status === "blocked" ? "bad" : "soft"}">${STATUS_WORD[e.status]}</span>`;
  if (!tag && e.level === "warn") tag = `<span class="tag soft">note</span>`;
  const li = document.createElement("li"); li.className = `ev ${e.type}`;
  li.title = e.ts || `${(+e.t || 0).toFixed(1)} s`;
  li.innerHTML = `<span class="no">${String(evCount).padStart(2, "0")}</span><span><span class="ag ${esc(agent)}">${esc(agent)}</span></span><span class="tx">${kind ? `<span class="kind">${kind}</span>` : ""}${esc(txt)}${tag}${extra}</span>`;
  $("traceBody").appendChild(li); $("traceBody").scrollTop = $("traceBody").scrollHeight;
}

/* ---------------- runs ---------------- */
function handle(e) {
  trace(e);
  if (e.type === "house") { $("houseBox").classList.remove("hid"); $("place").textContent = e.label; $("here").textContent = e.label; $("factsLine").textContent = "Checking…"; S.ready = showHouse({ ...e, footprint_m2: null }); }
  if (e.type === "answer") { state.result = e.result; state.old = !e.answer; state.answer = e.answer || null; renderAll(); Promise.resolve(S.ready).then(() => { if (viewer && state.result === e.result) overlayFor(true); }); }   // the map shows where as soon as the answer is in
  if (e.type === "answer_update" && e.answer) { state.answer = e.answer; renderAll(); }
  if (e.type === "done" || e.type === "error") { state.live = false; $("traceDot").classList.remove("live"); $("panel").setAttribute("aria-busy", "false"); renderCard(); }
  if (e.type === "error") { $("err").style.display = "block"; $("err").textContent = e.text; }
}

// The owner's inputs belong to one house: a new house or a replay clears them; replays cannot run a check.
function setInputs(on) { $("elecForm").classList.toggle("hid", !on); $("noteToggle").classList.toggle("hid", !on); if (!on) $("noteBox").classList.add("hid"); }

function resetForRun(sameHouse = false) {
  if (source) source.close();
  if (!sameHouse) { $("elec").value = ""; $("note").value = ""; $("elec").removeAttribute("aria-invalid"); $("houseBox").classList.add("hid"); }
  state = { ...state, answer: null, result: null, old: false, open: false, det: {}, live: true };
  $("card").innerHTML = ""; $("err").style.display = "none"; $("traceBody").innerHTML = ""; evCount = 0;
  $("traceDot").classList.add("live"); $("tap").classList.remove("on"); tapMode = false; $("panel").setAttribute("aria-busy", "true");
  if (viewer) clearOverlay();
}

async function apiError(r) {
  const text = await r.text();
  try { const j = JSON.parse(text); return (j.error && j.error.message) || (typeof j.detail === "string" ? j.detail : "the input was not accepted"); } catch (e) { return text.slice(0, 160) || `error ${r.status}`; }
}

// said: what the owner typed for this same house (electricity use, a note); absent for a new house.
async function startCheck(body, said) {
  resetForRun(!!said);
  state.request = body; state.replay = false;
  if (!STATIC) setInputs(true);
  const payload = { ...body, note: (said && said.note) || null, elec_kwh: (said && said.elec_kwh) || null };
  try {
    const r = await fetch("/api/check", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
    if (!r.ok) { handle({ type: "error", text: `The check could not start: ${await apiError(r)}` }); return; }
    const { run_id } = await r.json();
    source = new EventSource(`/api/runs/${run_id}/events`);
    source.onmessage = (m) => handle(JSON.parse(m.data));
    source.addEventListener("end", () => { source.close(); state.live = false; renderCard(); });
    source.onerror = () => { if (!state.live) return; source.close(); handle({ type: "error", text: "Lost the connection to the server before the check finished. Try again." }); };
  } catch (e) { handle({ type: "error", text: "Could not reach the server. Is it running?" }); }
}

// Send what the owner typed, for the house on screen; the number is checked first.
function sendSaid() {
  if (!state.request || state.live) return;
  const el = $("elec");
  if (el.value && !el.checkValidity()) {
    el.setAttribute("aria-invalid", "true"); el.focus();
    $("err").style.display = "block"; $("err").textContent = "Electricity use must be a whole number of kWh a year, between 100 and 100,000. You find it on your bill.";
    return;
  }
  el.removeAttribute("aria-invalid");
  startCheck(state.request, { elec_kwh: +el.value || null, note: $("note").value.trim() || null });
}

async function replay(name, maxGapMs = 1200) {
  resetForRun(); state.replay = true; setInputs(false);
  const r = await fetch(api.run(name));
  if (!r.ok) { handle({ type: "error", text: "no recorded run " + name }); return; }
  const run = await r.json();
  $("hint").textContent = `Replay of a recorded run · ${run.run_id}`;
  let prev = 0;
  for (const e of run.events) { await new Promise((ok) => setTimeout(ok, Math.min(maxGapMs, Math.max(40, (e.t - prev) * 1000)))); prev = e.t; handle(e); }
  state.live = false; $("traceDot").classList.remove("live"); $("panel").setAttribute("aria-busy", "false"); renderCard();
}

/* ---------------- search, tap and inputs ---------------- */
$("searchForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const q = $("addr").value.trim(); if (!q) return;
  $("err").style.display = "none";
  let ll = null;
  const nominatim = async (text, box = "") => { const j = await (await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&countrycodes=gb&limit=1&q=${encodeURIComponent(text)}${box}`)).json(); return j[0] ? [+j[0].lon, +j[0].lat] : null; };
  try {
    if (/^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/i.test(q)) {
      const j = await (await fetch(`https://api.postcodes.io/postcodes/${encodeURIComponent(q)}`)).json();
      if (j.result) ll = [j.result.longitude, j.result.latitude];
    } else {
      ll = await nominatim(q);
      // Nominatim finds nothing when the text holds only the first half of a postcode ("Laurier Road, London NW5"):
      // search again without it, inside that postcode district.
      const part = /\b([A-Z]{1,2}\d[A-Z\d]?)\b(?!\s*\d[A-Z]{2})/i.exec(q);
      if (!ll && part) {
        const o = await (await fetch(`https://api.postcodes.io/outcodes/${encodeURIComponent(part[1])}`)).json();
        const rest = q.replace(part[0], "").replace(/\s*,\s*(,|$)/g, "$1").replace(/\s{2,}/g, " ").trim();
        if (o.result && rest) { const x = o.result.longitude, y = o.result.latitude; ll = await nominatim(rest, `&viewbox=${x - 0.04},${y + 0.03},${x + 0.04},${y - 0.03}&bounded=1`); }
      }
    }
  } catch (e) { /* shown below */ }
  if (!ll) { $("err").style.display = "block"; $("err").textContent = "Could not find that place. Try a postcode."; return; }
  viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
  viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(ll[0], ll[1] - 0.0016, 230), orientation: { heading: 0, pitch: -45 * D2R, roll: 0 }, duration: 2 });
  tapMode = true; $("tap").classList.add("on");
};
$("factsToggle").onclick = () => openFacts($("facts").classList.contains("hid"));
$("noteToggle").onclick = () => { const open = $("noteBox").classList.toggle("hid") === false; $("noteToggle").setAttribute("aria-expanded", String(open)); };
$("noteSend").onclick = sendSaid;
$("elecForm").onsubmit = (ev) => { ev.preventDefault(); sendSaid(); };
$("traceToggle").onclick = () => { const closed = $("trace").classList.toggle("closed"); $("traceToggle").setAttribute("aria-expanded", String(!closed)); };
$("theme").onclick = () => {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch (e) { /* no storage */ }
};

async function examples() {
  const list = await (await fetch(api.examples())).json();
  $("examples").innerHTML = list.map((x, i) => `<button type="button" data-i="${i}" title="${esc(x.note)}" aria-pressed="false">${esc(x.label)}</button>`).join("");
  document.querySelectorAll("#examples button").forEach((b) => b.onclick = () => {
    document.querySelectorAll("#examples button").forEach((o) => { o.classList.toggle("on", o === b); o.setAttribute("aria-pressed", String(o === b)); });
    const x = list[+b.dataset.i];
    if (STATIC) { replay(x.file.replace(/\.json$/, "")); return; }
    startCheck(x.way ? { way: x.way, label: x.label } : { lat: x.lat, lon: x.lon, label: x.label });
  });
}

async function main() {
  examples();
  if (matchMedia("(max-width: 900px)").matches) { $("trace").classList.add("closed"); $("traceToggle").setAttribute("aria-expanded", "false"); }
  const fixedHouse = () => { $("searchForm").classList.add("hid"); $("here").classList.remove("hid"); $("here").textContent = "Pick an example house"; };
  if (STATIC) {
    fixedHouse(); $("elecForm").classList.add("hid"); $("noteToggle").classList.add("hid"); $("tap").classList.remove("on");
    $("hint").textContent = "Replays of recorded runs. Clone the repo to check any house.";
  } else {
    // Sample mode keeps the search: a house outside the snapshot is fetched from the public sources, still without keys.
    fetch("/api/mode").then((r) => r.json()).then((m) => { if (m.sample) $("hint").textContent = "Sample mode, no keys: pick an example or search any address in England"; }).catch(() => {});
  }
  const opts = { baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false, navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false, infoBox: false, selectionIndicator: false };
  if (window.GOOGLE_MAPS_API_KEY) {
    try {
      viewer = new Cesium.Viewer("map", { ...opts, baseLayer: false });
      viewer.scene.globe.show = false;
      viewer.scene.primitives.add(await Cesium.createGooglePhotorealistic3DTileset(window.GOOGLE_MAPS_API_KEY));
    } catch (e) {   // key set but refused: same page on the OSM map
      $("err").style.display = "block"; $("err").textContent = "Google 3D did not load, so the page uses the OpenStreetMap map. " + (e && e.message ? e.message : e);
      if (viewer) viewer.destroy();
      viewer = null; window.GOOGLE_MAPS_API_KEY = "";
    }
  }
  if (!viewer) {
    // No Google key (a fresh clone, or a judge's machine): OpenStreetMap tiles on a flat globe, same overlays.
    viewer = new Cesium.Viewer("map", { ...opts, baseLayer: new Cesium.ImageryLayer(new Cesium.OpenStreetMapImageryProvider({ url: "https://tile.openstreetmap.org/", maximumLevel: 19 })) });
    CLASSIFY = () => Cesium.ClassificationType.TERRAIN;
    if (!STATIC) $("hint").textContent = "Map: © OpenStreetMap contributors. Add a Google key for 3D.";
  }
  viewer.scene.screenSpaceCameraController.minimumZoomDistance = 25;
  viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(-0.135, 51.47, 9000), orientation: { heading: 0, pitch: -0.9, roll: 0 } });
  new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas).setInputAction((click) => {
    if (!tapMode) return;
    const p = (viewer.scene.pickPositionSupported && viewer.scene.pickPosition(click.position)) || viewer.camera.pickEllipsoid(click.position);  // flat map: the ellipsoid
    if (!p) return;
    const c = Cesium.Cartographic.fromCartesian(p);
    startCheck({ lat: c.latitude / D2R, lon: c.longitude / D2R, label: $("addr").value.trim() || null });   // a new house: inputs cleared
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
  const rp = new URLSearchParams(location.search).get("replay");
  if (rp) replay(rp);
}
main();
