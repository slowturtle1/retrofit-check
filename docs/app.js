/* Retrofit Check: the page. Talks to retrofit/server.py; every answer comes from a run of the agent. */

const $ = (id) => document.getElementById(id);
const D2R = Math.PI / 180, R = 6378137;
const C = (h, a = 1) => Cesium.Color.fromCssColorString(h).withAlpha(a);
const NAMES = { solar: "Solar panels", heat_pump: "Heat pump", wall_insulation: "Outside wall insulation" };
const ICON = { allowed: ["y", "✓"], allowed_with_conditions: ["c", "!"], needs_permission: ["n", "✕"], needs_consent: ["n", "✕"], check_with_council: ["c", "?"] };
const COMPASS = ["north", "north east", "east", "south east", "south", "south west", "west", "north west"];
const UNCERTAIN = {
  lidar_noisy: "More than a quarter of the roof reading is trees or chimneys, so the roof numbers are rough.",
  no_sunny_roof: "No roof plane faces between east and west.",
  article4_unknown: "An Article 4 direction covers this house and its contents are not on file.",
  lane_may_not_be_highway: "One wall faces a lane mapped as a service road. It is treated as a road to be safe. If it is your private drive, tell us.",
  heating_unknown: "Tell us how the house is heated: the grant depends on it.",
  bus_needs_fossil_heating: "The grant only helps if the heat pump replaces gas, oil, LPG or coal heating.",
  no_wall_away_from_road: "Every wall faces a road.",
  article4_coverage_unknown: "This council has not published Article 4 directions for conservation areas, so a missing record proves nothing. Ask the council.",
  listed_point_only: "The listing was found as a point, not an outline. Check with the council or Historic England's map.",
  article4_ended_but_listed: "An Article 4 here has ended but planning.data still lists it. We follow the council's decision.",
};

const STATIC = !!window.STATIC_SITE;   // docs/: replays recorded runs, no server
const api = {
  area: (e) => (STATIC ? `samples/areas/${e}.json` : `/api/area/${e}`),
  run: (n) => (STATIC ? `samples/${n}.json` : `/api/runs/${encodeURIComponent(n)}`),
  examples: () => (STATIC ? "samples/index.json" : "/api/examples"),
};
let viewer, state = { result: null, texts: {}, open: -1, houseId: null, label: null, request: null, memories: [] };
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
$("rl").onclick = () => { readHpr(); S.hpr.heading -= 30 * D2R; applyView(); };
$("rr").onclick = () => { readHpr(); S.hpr.heading += 30 * D2R; applyView(); };
$("zi").onclick = () => { readHpr(); S.hpr.range = Math.max(30, S.hpr.range * 0.75); applyView(); };
$("zo").onclick = () => { readHpr(); S.hpr.range = Math.min(1500, S.hpr.range * 1.33); applyView(); };
$("reset").onclick = () => { if (S.home) { S.hpr = Cesium.HeadingPitchRange.clone(S.home); viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(S.center, 12), { offset: S.hpr, duration: 1.2, complete: applyView }); } };

async function groundAt(lon, lat, fb) { if (!window.GOOGLE_MAPS_API_KEY) return Cesium.Cartesian3.fromDegrees(lon, lat, 0); try { const r = await viewer.scene.clampToHeightMostDetailed([Cesium.Cartesian3.fromDegrees(lon, lat, 800)]); if (r && r[0]) return r[0]; } catch (e) { /* fallback */ } return Cesium.Cartesian3.fromDegrees(lon, lat, fb); }

async function showHouse(h) {
  viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
  S.house.forEach((e) => viewer.entities.remove(e)); S.house = []; clearOverlay();
  S.coords = ring(h.coords);
  S.house.push(drape(S.coords, "#F0A23A", 0.62));
  S.center = await groundAt(h.lon, h.lat, 90);
  const size = Math.sqrt(Math.max(60, h.footprint_m2 || 120));
  S.home = new Cesium.HeadingPitchRange(0, -40 * D2R, Math.max(110, size * 9));
  S.hpr = Cesium.HeadingPitchRange.clone(S.home);
  viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(S.center, 12), { offset: S.hpr, duration: 2.2, complete: applyView });
}
function aimHome(az) { if (!S.home) return; S.home.heading = ((az + 180) % 360) * D2R; S.hpr = Cesium.HeadingPitchRange.clone(S.home); viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(S.center, 12), { offset: S.hpr, duration: 1.4, complete: applyView }); }

const mapLabel = (text) => viewer.entities.add({ position: Cesium.Cartesian3.fromDegrees(+state.result.house.lon, +state.result.house.lat, window.GOOGLE_MAPS_API_KEY ? 70 : 5), label: {
  text, font: "600 15px IBM Plex Sans, sans-serif", fillColor: Cesium.Color.WHITE, showBackground: true, backgroundColor: C("#13202B", 0.9),
  backgroundPadding: new Cesium.Cartesian2(10, 6), pixelOffset: new Cesium.Cartesian2(0, -30), disableDepthTestDistance: Number.POSITIVE_INFINITY } });

/* What each answer looks like on the house */
async function overlayFor(v) {
  clearOverlay();
  if (!v || !S.coords) return;
  const res = state.result, o = S.coords[0], L = local(o), pts = S.coords.map(L.to), c0 = centroid(pts);
  if (v.measure === "solar" && v.numbers && v.numbers.facing) {
    const plane = (res.planes || []).find((p) => p.facing === v.numbers.facing);
    const az = plane ? +plane.azimuth_deg : 180, n = [Math.sin(az * D2R), Math.cos(az * D2R)];
    const rel = pts.map((p) => [p[0] - c0[0], p[1] - c0[1]]);
    const sunny = clipHalf(rel, n), other = clipHalf(rel, [-n[0], -n[1]]);
    if (sunny.length > 2) S.overlay.push(drape(sunny.map((p) => L.back([p[0] + c0[0], p[1] + c0[1]])), "#FFD24A", 0.75));
    S.overlay.push(mapLabel(`Indicative: ${plane ? plane.facing : ""} roof slope for panels`));
    if (other.length > 2) S.overlay.push(drape(other.map((p) => L.back([p[0] + c0[0], p[1] + c0[1]])), "#C9C2B2", 0.45));
    aimHome(az);
  } else if (v.measure === "heat_pump") {
    const walls = res.walls || [];
    walls.forEach((w) => {
      const i = +w.wall_no, a = pts[i], b = pts[(i + 1) % pts.length];
      if (!a || !b) return;
      const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy); if (len < 1) return;
      const az = (+w.facing_deg) * D2R, nx = Math.sin(az), ny = Math.cos(az), d = 2.2;
      const strip = [a, b, [b[0] + nx * d, b[1] + ny * d], [a[0] + nx * d, a[1] + ny * d]].map(L.back);
      const road = String(w.fronts_highway) === "true", party = String(w.adjoins) === "true";
      S.overlay.push(drape(strip, road ? "#E5533D" : party ? "#8A98A3" : "#3CCB8F", 0.85));
    });
    S.overlay.push(mapLabel("Indicative: green walls away from the road, red walls facing it"));
    const ok = walls.filter((w) => String(w.fronts_highway) !== "true" && String(w.adjoins) !== "true");
    if (ok.length) aimHome(+ok.sort((a, b) => b.length_m - a.length_m)[0].facing_deg);
  } else if (v.measure === "wall_insulation" || v.status === "needs_consent") {
    const area = (res.areas || []).find((a) => (v.status === "needs_consent" ? /listed/.test(a.dataset) : a.dataset === "conservation-area" || a.dataset.includes("outstanding") || a.dataset === "national-park"));
    if (!area || !area.entity) return;
    try {
      const g = await (await fetch(api.area(area.entity))).json();
      if (state.result !== res || state.open < 0) return;
      if (v.status !== "needs_consent") S.overlay.push(...drapeGeo(g.fill, "#D0654A", 0.28));
      S.overlay.push(viewer.entities.add({ position: Cesium.Cartesian3.fromDegrees(+state.result.house.lon, +state.result.house.lat, 60), label: {
        text: v.status === "needs_consent" ? "Listed building" : `Inside ${g.name}${/conservation area/i.test(g.name || "") ? "" : " Conservation Area"}`,
        font: "600 16px IBM Plex Sans, sans-serif", fillColor: Cesium.Color.WHITE, showBackground: true, backgroundColor: C("#13202B", 0.9),
        backgroundPadding: new Cesium.Cartesian2(10, 6), pixelOffset: new Cesium.Cartesian2(0, -30), disableDepthTestDistance: Number.POSITIVE_INFINITY, heightReference: Cesium.HeightReference.NONE } }));
      S.overlay.push(...drapeGeo(v.status === "needs_consent" ? g.fill : g.edge, "#E5533D", v.status === "needs_consent" ? 0.55 : 0.9));
      if (v.status !== "needs_consent") { S.hpr = new Cesium.HeadingPitchRange(S.hpr.heading, -58 * D2R, 520); viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(S.center, 12), { offset: S.hpr, duration: 1.8, complete: applyView }); }
    } catch (e) { trace({ type: "error", text: "area outline did not load: " + e }); }
  }
}

/* ---------------- panel ---------------- */
const fmtDate = (iso) => { if (!iso) return ""; const d = new Date(String(iso).slice(0, 10)); return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function context(res) {
  const bits = [];
  const listed = (res.areas || []).find((a) => a.dataset === "listed-building" && a.grade) || (res.areas || []).find((a) => a.dataset.startsWith("listed"));
  bits.push(listed ? `Listed${listed.grade ? " grade " + listed.grade : ""} since ${fmtDate(listed.start_date)}` : "Not listed");
  const ca = (res.areas || []).filter((a) => a.dataset === "conservation-area");
  bits.push(ca.length ? ca.map((a) => `${a.name}${/conservation area/i.test(a.name) ? "" : " Conservation Area"} (since ${fmtDate(a.start_date)})`).join(", ") : "not in a conservation area");
  return bits.join(" · ");
}

function reasonChain(v, res) {
  if (v.status === "needs_permission" && v.rules.includes("ewi-art23")) {
    const ca = (res.areas || []).find((a) => a.dataset === "conservation-area") || {};
    const r = res.rules["ewi-art23"] || {};
    return `<div class="reason"><b>Why not without permission.</b> Your house is inside ${esc(ca.name || "a conservation area")}${/conservation area/i.test(ca.name || "") ? "" : " Conservation Area"}, the red line on the map. Inside it, the national rule that normally lets you clad walls does not apply.
      <div class="chain">house → ${esc(ca.name || "conservation area")} (${esc(ca.reference || "")}, since ${fmtDate(ca.start_date)}) → ${esc(r.clause || "")} → planning permission</div></div>`;
  }
  if (v.status === "needs_consent") {
    const l = (res.areas || []).find((a) => a.dataset === "listed-building") || (res.areas || []).find((a) => a.dataset.startsWith("listed")) || {};
    return `<div class="reason"><b>Why consent.</b> The building is listed${l.grade ? " grade " + esc(l.grade) : ""} since ${fmtDate(l.start_date)}. Any change to how it looks needs listed building consent, even work that is normally free to do.
      <div class="chain">house → listed (${esc(l.reference || "")}) → listed building consent</div></div>`;
  }
  return "";
}

function sources(v, res) {
  const ids = [...v.rules, ...v.conditions, ...v.alternatives];
  const rules = ids.filter((k) => res.rules[k]).map((k) => { const r = res.rules[k]; return `<a class="src" href="${esc(r.source_url)}" target="_blank" rel="noopener" title="${esc(r.plain)}">${esc(r.clause)} · in force ${fmtDate(r.in_force)}${r.amended_by ? " · last change " + esc(r.amended_by) : ""}</a>`; });
  const grants = v.grants.filter((k) => res.grants[k]).map((k) => { const g = res.grants[k]; return `<a class="src" href="${esc(g.source_url)}" target="_blank" rel="noopener">${esc(k)} · checked ${fmtDate(g.checked_on)}</a>`; });
  const facts = v.facts.filter((f) => f.fact !== "listed" || f.value !== "no").map((f) => `<span class="src" title="${esc(f.value)}">${esc(f.fact)}: ${esc(f.source)}</span>`);
  return `<div class="srcs">${[...rules, ...grants, ...facts].join("")}</div>`;
}

const gbp = (n) => "£" + Number(n).toLocaleString("en-GB");
const REC_CLASS = { "Worth getting quotes": "go", "Ask the council first": "ask", "Probably not worth it for this house": "no", "Can't tell yet: add your gas use": "add", "Worth it mainly if your boiler needs replacing soon": "ask" };
const KIND = { official: "official", consumer_survey: "Which?", advice_body: "advice" };

function moneyBlock(v, res) {
  const m = (res.money || {})[v.measure]; if (!m || (!m.cost && !m.why)) return "";
  const rows = [];
  if (v.measure === "solar" && m.cost) {
    rows.push(["Rough cost", `${gbp(m.cost[0])} to ${gbp(m.cost[1])}`], ["Value a year", `${gbp(m.value_year[0])} to ${gbp(m.value_year[1])}`], ["Pays back in", `${m.payback_years[0]} to ${m.payback_years[1]} years`]);
  }
  if (v.measure === "heat_pump" && m.cost) {
    rows.push(["Rough cost", `${gbp(m.cost_before_grant[0])} to ${gbp(m.cost_before_grant[1])}`], ["After the grant", `${gbp(m.cost[0])} to ${gbp(m.cost[1])} (typical ${gbp(m.median_after_grant)})`]);
    if (m.saving_year) rows.push(["Saving a year", `${gbp(m.saving_year[0])} to ${gbp(m.saving_year[1])} on ${Number(m.gas_kwh).toLocaleString("en-GB")} kWh of gas`]);
    if (m.payback_years) rows.push(["Pays back in", `${m.payback_years[0]} to ${m.payback_years[1]} years`]);
    if (m.extra_over_boiler !== undefined) rows.push(["Instead of a new boiler", `about ${gbp(m.extra_over_boiler)} more, back in about ${m.extra_payback_years} years`]);
  }
  const used = (m.uses || []).filter((k) => res.prices && res.prices[k]).map((k) => { const p = res.prices[k];
    return p.kind === "assumption" ? `<span class="src" title="${esc(p.plain)}">assumption: ${esc(p.plain.toLowerCase())}</span>` : `<a class="src" href="${esc(p.source_url)}" target="_blank" rel="noopener" title="${esc(p.plain)}">${esc(k)} · ${esc(KIND[p.kind] || p.kind)} · ${p.valid_to ? fmtDate(p.valid_from) + " to " + fmtDate(p.valid_to) : fmtDate(p.valid_from)}</a>`; }).join("");
  return `<div class="money">${rows.length ? `<div class="m">${rows.map(([a, b]) => `<span>${a}</span><span>${b}</span>`).join("")}</div>` : ""}
    ${m.why ? `<p class="warn">${esc(m.why)}</p>` : ""}${m.note ? `<div class="est">${esc(m.note)}</div>` : ""}
    <div class="est">Estimates from dated sources, not financial advice.</div><div class="srcs">${used}</div></div>`;
}

function rec(v, res) { const r = ((res.money || {})[v.measure] || {}).recommendation; return r ? `<div class="rec ${REC_CLASS[r] || ""}">${esc(r)}</div>` : ""; }

function renderRows() {
  const res = state.result; if (!res) return;
  $("rows").innerHTML = res.verdicts.map((v, i) => {
    const t = state.texts[v.measure] || {}, [k, ic] = ICON[v.status] || ["c", "?"];
    const warns = v.uncertain.map((u) => `<p class="warn">${esc(UNCERTAIN[u] || u)}</p>`).join("");
    const getLabel = v.status === "needs_permission" || v.status === "needs_consent" ? "What you can do" : "What you get";
    const who = t.writer === "nemotron" ? `<div class="who nem">Explained by Nemotron via Nightshift · checked by ${esc(t.checked_by || "code")}</div>` : `<div class="who">Written from the rules${state.live ? " · Nemotron is rewriting this…" : ""}</div>`;
    return `<div class="row ${i === state.open ? "open" : ""}">
      <button class="rh" data-i="${i}"><span class="ic ${k}">${ic}</span>
        <span><div class="nm">${NAMES[v.measure]}</div><div class="st ${k}">${esc(v.headline)}</div><div class="one">${esc(t.one)}</div>${rec(v, res)}</span></button>
      <div class="rb">${reasonChain(v, res)}${warns}<p><b>Why.</b> ${esc(t.why)}</p><p><b>${getLabel}.</b> ${esc(t.get)}</p>${moneyBlock(v, res)}<p><b>Help with cost.</b> ${esc(t.cost)}</p>
        <p class="sure">${v.status.startsWith("allowed") ? "For certainty: apply for a Lawful Development Certificate, or ask the council." : "Before you apply: ask the council's planning team for pre application advice."}</p>${sources(v, res)}${who}</div>
    </div>`;
  }).join("");
  document.querySelectorAll(".rh").forEach((b) => b.onclick = () => { const i = +b.dataset.i; state.open = state.open === i ? -1 : i; renderRows(); overlayFor(state.open >= 0 ? state.result.verdicts[state.open] : null); if (state.open < 0) $("reset").onclick(); });
}

function renderMemories() {
  const m = state.memories.filter((x) => x.kind !== "outcome");
  const last = state.memories.find((x) => x.kind === "outcome");
  $("mem").innerHTML = (m.length ? "Remembered: " + m.map((x) => `<b>${esc(x.content)}</b> (you, ${fmtDate(x.learnedAt)})`).join(", ") + ". " : "") + (last ? `Last check ${fmtDate(last.learnedAt)}.` : "");
}

/* ---------------- trace ---------------- */
function trace(e) {
  evCount++; $("traceCount").textContent = `${evCount} steps`;
  let k = "tool", txt = "", extra = "";
  switch (e.type) {
    case "start": k = "tool"; txt = `run ${e.run_id}`; break;
    case "tool_start": txt = `${e.tool} → ${e.source}`; break;
    case "tool_end": k = e.ok ? "tool" : "err"; txt = `${e.tool} ${e.ok ? "done" : "failed: " + (e.error || "")}${e.seconds !== undefined ? ` (${e.seconds} s)` : ""}`; break;
    case "house": txt = `house ${e.house_id}`; break;
    case "zetaris": k = e.error ? "err" : "zetaris"; txt = `${e.purpose || "query"} · ${e.rows ?? "-"} rows · ${e.seconds} s`; extra = `<details><summary>SQL</summary><pre>${esc(e.sql)}${e.error ? "\n\nERROR " + esc(e.error) : ""}</pre></details>`; break;
    case "model": k = e.ok ? "model" : "err"; txt = `${e.role} · ${e.ok ? (e.routed_model || e.model) + " · " + e.seconds + " s · receipt " + (e.receipt_id || "-") : "failed after " + e.seconds + " s: " + (e.error || "").slice(0, 90)}`; break;
    case "critic": k = "critic"; txt = e.measure === "roof" ? `roof check after measuring again: ${e.ok ? "accepted" : e.problems.join("; ")}` : `critic ${e.measure} round ${e.round}: ${e.ok ? "accepted" : "rejected · " + e.problems.join("; ")}`; break;
    case "memory_recall": k = "memory"; txt = `H-MEM recall: ${e.memories.length ? e.memories.map((m) => m.content).join(" · ") : "nothing yet"}`; break;
    case "memory_write": k = "memory"; txt = `H-MEM remember ${e.kind}: ${e.content}${e.result && e.result.superseded ? " (replaces: " + e.result.superseded.content + ")" : ""}`; break;
    case "intake": k = "model"; txt = `understood your note: ${JSON.stringify(e.understood)}`; break;
    case "note": txt = e.text; break;
    case "decision": k = "decision"; txt = e.text; break;
    case "challenge": k = "critic"; txt = `${e.by} challenges the ${e.about} finding: ${e.text}`; break;
    case "requery": k = e.ok ? "zetaris" : "warn"; txt = `${e.by} checked ${e.about} again: ${e.text}`; break;
    case "thought": k = e.level === "warn" ? "warn" : "tool"; txt = e.text; break;
    case "answer": txt = "answer from the rules: " + e.result.verdicts.map((v) => `${NAMES[v.measure]} ${v.headline}`).join(" · "); break;
    case "answer_update": k = "model"; txt = `${NAMES[e.measure]}: Nemotron's explanation passed the checks`; break;
    case "done": txt = `done in ${e.seconds} s`; break;
    case "error": k = "err"; txt = e.text; break;
    default: txt = e.type;
  }
  const label = { tool: "step", zetaris: "zetaris", model: "nemotron", memory: "h-mem", warn: "note", critic: "critic", err: "error", decision: "decision" }[k];
  const div = document.createElement("div"); div.className = "ev";
  div.innerHTML = `<span class="t">${(+e.t || 0).toFixed(1)}s</span><span class="k ${k}">${label}</span><span>${esc(txt)}${extra}</span>`;
  $("traceBody").appendChild(div); $("traceBody").scrollTop = $("traceBody").scrollHeight;
}

/* ---------------- runs ---------------- */
function handle(e) {
  trace(e);
  if (e.type === "house") { state.houseId = e.house_id; $("houseBox").classList.remove("hid"); $("place").textContent = e.label; $("ctx").textContent = "Checking…"; showHouse({ ...e, footprint_m2: null }); }
  if (e.type === "memory_recall") { state.memories = e.memories; renderMemories(); const h = e.memories.find((m) => m.kind === "heating"); if (h && !$("heating").value) $("heating").value = h.content.split(":")[1].trim().split(",")[0];
    const g = e.memories.find((m) => m.kind === "gas_use"); if (g && !$("gas").value) $("gas").value = parseInt(g.content.split(":")[1], 10) || ""; }
  if (e.type === "memory_write") { state.memories = state.memories.filter((m) => m.kind !== e.kind); if (e.result && e.result.memory) state.memories.unshift(e.result.memory); renderMemories(); }
  if (e.type === "answer") { state.result = e.result; state.texts = e.texts; $("ctx").textContent = context(e.result); renderRows(); $("foot").textContent = `Checked ${fmtDate(e.result.today)}. Rules for England; demo data checked for London, and local data quality varies. The rules decide each status in code; the agents plan, challenge the evidence and explain. Not legal advice.`; }
  if (e.type === "answer_update") { state.texts[e.measure] = e.text; renderRows(); }
  if (e.type === "done" || e.type === "error") { state.live = false; $("traceDot").classList.remove("live"); renderRows(); }
  if (e.type === "error") { $("err").style.display = "block"; $("err").textContent = e.text; }
}

function resetForRun() {
  if (source) source.close();
  state = { ...state, result: null, texts: {}, open: -1, memories: [], live: true };
  $("rows").innerHTML = ""; $("mem").innerHTML = ""; $("err").style.display = "none"; $("traceBody").innerHTML = ""; evCount = 0;
  $("traceDot").classList.add("live"); $("tap").classList.remove("on"); tapMode = false; clearOverlay();
}

async function startCheck(body) {
  resetForRun();
  state.request = body;
  const payload = { ...body, heating: $("heating").value || null, note: $("note").value.trim() || null, gas_kwh: +$("gas").value || null };
  const r = await fetch("/api/check", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
  if (!r.ok) { handle({ type: "error", text: (await r.text()).slice(0, 200) }); return; }
  const { run_id } = await r.json();
  source = new EventSource(`/api/runs/${run_id}/events`);
  source.onmessage = (m) => handle(JSON.parse(m.data));
  source.addEventListener("end", () => { source.close(); state.live = false; renderRows(); });
}

async function replay(name, maxGapMs = 1200) {
  resetForRun();
  const r = await fetch(api.run(name));
  if (!r.ok) { handle({ type: "error", text: "no recorded run " + name }); return; }
  const run = await r.json();
  $("hint").textContent = `Replay of a recorded live run · ${run.run_id}`;
  let prev = 0;
  for (const e of run.events) { await new Promise((ok) => setTimeout(ok, Math.min(maxGapMs, Math.max(40, (e.t - prev) * 1000)))); prev = e.t; handle(e); }
  state.live = false; renderRows();
}

/* ---------------- search and tap ---------------- */
$("searchForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const q = $("addr").value.trim(); if (!q) return;
  $("err").style.display = "none";
  let ll = null;
  try {
    if (/^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/i.test(q)) {
      const j = await (await fetch(`https://api.postcodes.io/postcodes/${encodeURIComponent(q)}`)).json();
      if (j.result) ll = [j.result.longitude, j.result.latitude];
    } else {
      const j = await (await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&countrycodes=gb&limit=1&q=${encodeURIComponent(q)}`)).json();
      if (j[0]) ll = [+j[0].lon, +j[0].lat];
    }
  } catch (e) { /* shown below */ }
  if (!ll) { $("err").style.display = "block"; $("err").textContent = "Could not find that place. Try a postcode."; return; }
  viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
  viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(ll[0], ll[1] - 0.0016, 230), orientation: { heading: 0, pitch: -45 * D2R, roll: 0 }, duration: 2 });
  tapMode = true; $("tap").classList.add("on");
};
$("noteToggle").onclick = () => $("noteBox").classList.toggle("hid");
$("noteSend").onclick = () => { if (state.request) startCheck(state.request); };
$("heating").onchange = () => { if (state.request && !state.live) startCheck(state.request); };
$("gas").onchange = () => { if (state.request && !state.live) startCheck(state.request); };
$("traceToggle").onclick = () => $("trace").classList.toggle("closed");

async function examples() {
  const list = await (await fetch(api.examples())).json();
  $("examples").innerHTML = list.map((x, i) => `<button data-i="${i}" title="${esc(x.note)}">${esc(x.label)}</button>`).join("");
  document.querySelectorAll("#examples button").forEach((b) => b.onclick = () => {
    document.querySelectorAll("#examples button").forEach((o) => o.classList.toggle("on", o === b));
    const x = list[+b.dataset.i];
    if (STATIC) { replay(x.file.replace(/\.json$/, "")); return; }
    startCheck(x.way ? { way: x.way, label: x.label } : { lat: x.lat, lon: x.lon, label: x.label });
  });
}

async function main() {
  examples();
  if (STATIC) {
    $("searchForm").classList.add("hid");
    document.querySelector(".you").classList.add("hid");
    $("tap").classList.remove("on");
    $("hint").textContent = "Replays of recorded live runs. Clone the repo to check any house.";
  } else {
    fetch("/api/mode").then((r) => r.json()).then((m) => { if (m.sample) { $("hint").textContent = "Sample mode: the agent runs on cached data, no keys needed"; $("searchForm").classList.add("hid"); } }).catch(() => {});
  }
  const opts = { baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false, navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false, infoBox: false, selectionIndicator: false };
  if (window.GOOGLE_MAPS_API_KEY) {
    viewer = new Cesium.Viewer("map", { ...opts, baseLayer: false });
    viewer.scene.globe.show = false;
    try { viewer.scene.primitives.add(await Cesium.createGooglePhotorealistic3DTileset(window.GOOGLE_MAPS_API_KEY)); }
    catch (e) { $("err").style.display = "block"; $("err").textContent = "Google 3D did not load: " + (e && e.message ? e.message : e); return; }
  } else {
    // No Google key (a fresh clone, or a judge's machine): OpenStreetMap tiles on a flat globe, same overlays.
    viewer = new Cesium.Viewer("map", { ...opts, baseLayer: new Cesium.ImageryLayer(new Cesium.OpenStreetMapImageryProvider({ url: "https://tile.openstreetmap.org/" })) });
    CLASSIFY = () => Cesium.ClassificationType.TERRAIN;
    $("hint").textContent = "Map: © OpenStreetMap contributors. Add a Google key for 3D.";
  }
  viewer.scene.screenSpaceCameraController.minimumZoomDistance = 25;
  viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(-0.135, 51.47, 9000), orientation: { heading: 0, pitch: -0.9, roll: 0 } });
  new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas).setInputAction((click) => {
    if (!tapMode) return;
    const p = viewer.scene.pickPosition(click.position); if (!p) return;
    const c = Cesium.Cartographic.fromCartesian(p);
    startCheck({ lat: c.latitude / D2R, lon: c.longitude / D2R, label: $("addr").value.trim() || null });
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
  const rp = new URLSearchParams(location.search).get("replay");
  if (rp) replay(rp);
}
main();
