/* ?demo=1: a captioned walk through the recorded runs, for screen recording. Uses the same page functions; nothing is staged.
   Captions read the numbers from each run's answer, so they stay true when the runs are recorded again. */

(function () {
  if (!new URLSearchParams(location.search).has("demo")) return;
  const css = document.createElement("style");
  css.textContent = `
    #stageOv { position: fixed; inset: 0; z-index: 20; display: none; align-items: center; justify-content: center; background: var(--bg); }
    #stageOv.on { display: flex; }
    #stageOv .sc { max-width: 980px; padding: 40px; }
    #stageOv .ey { display: inline-block; background: var(--ink); color: var(--surface); font: 600 14px "IBM Plex Mono", monospace; letter-spacing: 2px; padding: 8px 18px; border-radius: 999px; }
    #stageOv h2 { font-size: 54px; line-height: 1.1; margin: 18px 0 18px; font-weight: 800; }
    #stageOv p { font-size: 22px; color: var(--muted); margin: 0 0 10px; line-height: 1.45; font-weight: 500; }
    #stageOv .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px 22px; margin-top: 22px; }
    #stageOv .grid div { font-size: 18px; color: var(--muted); line-height: 1.4; background: var(--surface); border: 2.5px solid var(--ink); border-radius: 22px; padding: 14px 18px; }
    #stageOv .grid b { color: var(--ink); display: block; font-size: 20px; font-weight: 800; }
    #caption { position: fixed; left: 16px; right: 480px; top: 130px; z-index: 15; display: none; background: var(--surface); border: 2.5px solid var(--ink); border-radius: 22px; padding: 14px 20px; font-size: 21px; line-height: 1.45; font-weight: 500; max-width: 900px; }
    #caption.on { display: block; }
    #caption .sp { display: inline-block; background: var(--ink); color: var(--surface); font: 600 12px "IBM Plex Mono", monospace; letter-spacing: 1.5px; padding: 4px 12px; border-radius: 999px; margin-bottom: 8px; }
    #caption .tx { display: block; }`;
  document.head.appendChild(css);
  document.body.insertAdjacentHTML("beforeend", `<div id="stageOv"></div><div id="caption" role="status"><span class="sp" id="capLabel">RETROFIT CHECK</span><span class="tx" id="capText"></span></div>`);

  const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));
  const stage = (html) => { const s = document.getElementById("stageOv"); s.classList.toggle("on", !!html); s.innerHTML = html ? `<div class="sc">${html}</div>` : ""; };
  const say = (text, label = "RETROFIT CHECK") => { const c = document.getElementById("caption"); c.classList.toggle("on", !!text); document.getElementById("capText").textContent = text || ""; document.getElementById("capLabel").textContent = label; };
  const openCard = async (ms) => { if (!state.answer) return; state.open = true; renderCard(); await overlayFor(true); document.getElementById("card").scrollIntoView({ block: "nearest", behavior: "smooth" }); await wait(ms); };
  const closeCard = () => { state.open = false; renderCard(); clearOverlay(); };
  const traceOpen = (open) => { document.getElementById("trace").classList.toggle("closed", !open); document.getElementById("traceToggle").setAttribute("aria-expanded", String(open)); };
  const runOf = async (key) => (await (await fetch(STATIC ? "samples/index.json" : "/api/samples")).json()).find((x) => x.key === key);
  const play = async (key) => { const x = await runOf(key); if (x) await replay(STATIC ? x.file.replace(/\.json$/, "") : x.key, 350); };
  const solar = () => (state.answer ? state.answer.solar : null);
  const money = (s) => { const n = s.numbers || {}; return n.cost_gbp ? ` Rough cost ${gbp(n.cost_gbp[0])} to ${gbp(n.cost_gbp[1])}, pays back in ${n.payback_years[0]} to ${n.payback_years[1]} years.` : ""; };

  async function demo() {
    await wait(1500);
    stage(`<span class="ey">RETROFIT CHECK · SOLAR</span><h2>Is my house eligible for solar panels?</h2><p>Today the answer is spread across seven sources: the listing, the conservation area, Article 4, the roads, the roof, the sun and what you use. And it depends.</p>`);
    await wait(7000);
    stage(null);

    say("A corner house in Dartmouth Park, London. The agent finds it and reads every fact through Zetaris: listing, conservation area, Article 4, the roads around it, the roof from LIDAR and the sun from PVGIS.", "1 · AN ORDINARY HOUSE");
    await play("dartmouth"); await wait(2500);
    let s = solar();
    if (s) {
      say(`${s.status_text}. ${s.lines.one} → ${s.recommendation}.${money(s)}`, "THE ANSWER");
      await openCard(9000);
      say(`Why: ${s.lines.why}`, "WHY THIS ANSWER");
      await wait(9000);
      say(s.usage ? `${s.usage.text} Meterless H-MEM keeps that with the date, so next time the agent does not ask again, and a correction changes the card.`
        : "The owner adds their yearly electricity use from the bill. Meterless H-MEM keeps it with the date, the card compares it with what the roof makes, and the next visit recalls it.", "WHAT YOU TOLD US");
      openFacts(true); document.getElementById("facts").scrollIntoView({ block: "nearest", behavior: "smooth" });
      await wait(8000); openFacts(false); closeCard();
    }

    say("In Hampstead, planning.data still lists a 2010 Article 4 that needed permission for solar panels. Camden ended it on 9 June 2026. The evaluator challenges the record, the analyst asks Zetaris again, and the answer follows the council.", "2 · THE AGENT CATCHES A CONFLICT");
    await play("hampstead"); traceOpen(true); await wait(10000);
    s = solar(); if (s) { say(`${s.status_text}. ${s.confidence.text || ""}`, "HAMPSTEAD"); await openCard(7000); closeCard(); }

    say("10 Downing Street is Grade I listed. The planner stops early: panels need listed building consent, so it does not measure the roof.", "3 · A LISTED BUILDING");
    await play("downing"); await wait(5000);
    s = solar(); if (s) { say(`${s.status_text} → ${s.recommendation}. ${s.next_step}`, "10 DOWNING STREET"); await openCard(7000); closeCard(); }

    say("How we checked: every step names the agent that acted and how it went. Zetaris queries with their SQL, each challenge and second query, each Nemotron call with its Nightshift receipt, and what H-MEM remembered.", "HOW WE CHECKED");
    traceOpen(true); await wait(9000); say(null);

    stage(`<span class="ey">HOW IT WORKS</span><h2>The rules decide in code. The agents plan, challenge the evidence and explain.</h2>
      <div class="grid"><div><b>Zetaris</b>planning.data and PVGIS as REST tables, house facts from OpenStreetMap and LIDAR in Postgres, dated rules and prices: one SQL layer.</div>
      <div><b>Evaluator</b>No Article 4 on record is not proof, a noisy roof reading, cost sources that disagree: each challenge goes back to Zetaris.</div>
      <div><b>NVIDIA Nemotron via Meterless Nightshift</b>Rewrites each answer in plain words; a critic checks nothing changed. Every call has a receipt.</div>
      <div><b>Meterless H-MEM</b>Remembers what the owner told us, with the date, and does not ask again.</div></div>`);
    await wait(12000);
    stage(`<span class="ey">RETROFIT CHECK</span><h2>Know what’s possible, what it costs and what to do next, for your house.</h2><p>Rules for England, demo data for London. Not legal or financial advice.</p>`);
  }
  window.addEventListener("load", () => setTimeout(demo, 800));
})();
