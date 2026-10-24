/* ?demo=1: a captioned walk through the recorded runs, for screen recording. Uses the same page functions; nothing is staged. */

(function () {
  if (!new URLSearchParams(location.search).has("demo")) return;
  const css = document.createElement("style");
  css.textContent = `
    #stage { position: fixed; inset: 0; z-index: 20; display: none; align-items: center; justify-content: center; background: rgba(19,32,43,.86); }
    #stage.on { display: flex; }
    #stage .sc { max-width: 980px; padding: 40px; }
    #stage .ey { font: 600 14px "IBM Plex Mono", monospace; letter-spacing: 2px; color: var(--amber); }
    #stage h2 { font-size: 50px; line-height: 1.12; margin: 14px 0 18px; font-weight: 600; }
    #stage p { font-size: 21px; color: var(--soft); margin: 0 0 10px; line-height: 1.45; }
    #stage .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 28px; margin-top: 18px; }
    #stage .grid div { font-size: 18px; color: var(--soft); line-height: 1.4; }
    #stage .grid b { color: var(--paper); display: block; font-size: 19px; }
    #caption { position: fixed; left: 16px; right: 470px; bottom: 90px; z-index: 15; display: none; background: rgba(19,32,43,.96); border: 1px solid var(--line);
      border-radius: 14px; padding: 14px 18px; font-size: 20px; line-height: 1.45; max-width: 900px; }
    #caption.on { display: block; }
    #caption .sp { display: block; font: 600 12px "IBM Plex Mono", monospace; color: var(--amber); letter-spacing: 1px; margin-bottom: 4px; }`;
  document.head.appendChild(css);
  document.body.insertAdjacentHTML("beforeend", `<div id="stage"></div><div id="caption"><span class="sp" id="capLabel">RETROFIT CHECK</span><span id="capText"></span></div>`);

  const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));
  const stage = (html) => { const s = document.getElementById("stage"); s.classList.toggle("on", !!html); s.innerHTML = html ? `<div class="sc">${html}</div>` : ""; };
  const say = (text, label = "RETROFIT CHECK") => { const c = document.getElementById("caption"); c.classList.toggle("on", !!text); document.getElementById("capText").textContent = text || ""; document.getElementById("capLabel").textContent = label; };
  const openRow = async (measure, ms) => {
    const i = state.result.verdicts.findIndex((v) => v.measure === measure);
    state.open = i; renderRows(); await overlayFor(state.result.verdicts[i]);
    document.querySelectorAll(".row")[i]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    await wait(ms);
  };
  const closeRows = () => { state.open = -1; renderRows(); clearOverlay(); };
  const trace = (open) => document.getElementById("trace").classList.toggle("closed", !open);
  const runOf = async (key) => (await (await fetch(STATIC ? "samples/index.json" : "/api/samples")).json()).find((x) => x.key === key);
  const play = async (key) => { const x = await runOf(key); await replay(STATIC ? x.file.replace(/\.json$/, "") : x.key, 350); };

  async function demo() {
    await wait(1500);
    stage(`<div class="ey">RETROFIT CHECK</div><h2>“Which energy upgrades is my house eligible for?”</h2><p>Solar panels, a heat pump, outside wall insulation. Every house in England has different rules, and the answers are spread across five public sources.</p>`);
    await wait(7000);
    stage(null);

    say("A corner house in Dartmouth Park, London. The agent finds it, recalls what the owner told it last time, and reads every fact through Zetaris.", "1 · AN ORDINARY HOUSE");
    await play("dartmouth"); await wait(2500);
    say("Solar: allowed. The south slope makes about 2,900 kWh a year. Worth getting quotes: it pays back in 8 to 19 years.", "SOLAR PANELS");
    await openRow("solar", 8000);
    say("Heat pump: allowed, but only on the east wall. The other two walls face a road, and this is a conservation area. With this gas use it mainly makes sense when the boiler needs replacing.", "HEAT PUMP");
    await openRow("heat_pump", 9000);
    say("Outside wall insulation: needs planning permission. The red line is the Dartmouth Park Conservation Area. Inside it, cladding walls is not permitted development. Insulating from the inside is.", "OUTSIDE WALL INSULATION");
    await openRow("wall_insulation", 10000);
    closeRows();

    say("600 metres away, the same kind of house sits outside the conservation area. Here the walls are allowed too, if the finish looks the same.", "2 · SAME STREET TYPE, DIFFERENT RULES");
    await play("lady-somerset"); await wait(3000);
    await openRow("wall_insulation", 6000); closeRows();

    say("In Hampstead, planning.data still lists a 2010 rule that needed permission for solar panels. Camden ended it in June 2026. The agent shows both sources and follows the council.", "3 · THE AGENT CATCHES A CONFLICT");
    await play("hampstead"); trace(true); await wait(9000); trace(false);

    say("10 Downing Street is Grade I listed. The planner stops early: every upgrade needs listed building consent, so it does not measure the roof.", "4 · A LISTED BUILDING");
    await play("downing"); await wait(7000);

    say("Every step is in the trace: the Zetaris queries with their SQL, the evaluator's challenges and re-checks, each Nemotron call with its Nightshift receipt, and what H-MEM remembered.", "HOW IT WORKED");
    trace(true); await wait(8000); trace(false); say(null);

    stage(`<div class="ey">HOW IT WORKS</div><h2>The rules decide. The agents plan, challenge the evidence and explain.</h2>
      <div class="grid"><div><b>Zetaris</b>planning.data and PVGIS as REST tables, OSM and LIDAR facts in a Postgres datasource, dated rules and prices: one SQL layer.</div>
      <div><b>Evaluator</b>“No Article 4 on record is not proof”, noisy LIDAR, cost sources that disagree: each challenge goes back to Zetaris.</div>
      <div><b>NVIDIA Nemotron via Meterless Nightshift</b>Rewrites each answer in plain words; a critic checks nothing changed. Every call has a receipt.</div>
      <div><b>Meterless H-MEM</b>Remembers what the owner said, cites it as “you, date”, and does not ask again.</div></div>`);
    await wait(12000);
    stage(`<div class="ey">RETROFIT CHECK</div><h2>Know what’s possible, what it costs and what to do next, for your house.</h2><p>Rules for England, data checked for London. Not legal or financial advice.</p>`);
  }
  window.addEventListener("load", () => setTimeout(demo, 800));
})();
