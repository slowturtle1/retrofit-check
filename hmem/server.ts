// H-MEM for Retrofit Check: what the homeowner tells us, remembered with provenance.
// The Meterless reference engine runs unchanged from vendor/hmem; this file only adds HTTP.
//
//   POST /remember  {houseId, kind, content, label}       -> new memory; supersedes the last one of the same kind
//   POST /recall    {houseId, query}                      -> memories for this house, ranked by the engine
//   POST /feedback  {id, kind: helpful|not_helpful|wrong} -> engine feedback deltas
//   GET  /audit/:id                                       -> append-only ledger history
//
// State persists in .state/ (gitignored).

import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { HMEM } from "./vendor/hmem/src/index.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.HMEM_PORT ?? 8790);
const hmem = new HMEM({ persistDir: path.resolve(here, process.env.HMEM_STATE ?? ".state"), actor: "retrofit-check" });

type Json = Record<string, any>;

function body(req: http.IncomingMessage): Promise<Json> {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      try { resolve(raw ? JSON.parse(raw) : {}); } catch (e) { reject(e); }
    });
  });
}

const tag = (houseId: string) => `house:${houseId}`;
const live = (houseId: string) => hmem.store.all().filter((m: any) => m.tags?.includes(tag(houseId)) && !m.supersededBy);
const view = (m: any) => ({ id: m.id, content: m.content, kind: m.tags.find((t: string) => t.startsWith("kind:"))?.slice(5), confidence: m.confidence, learnedAt: new Date(m.provenance?.learnedAt ?? m.timestamp).toISOString(), label: m.provenance?.label, supersedes: m.supersedes ?? null });

async function route(req: http.IncomingMessage): Promise<[number, Json]> {
  const url = new URL(req.url ?? "/", "http://x");
  if (req.method === "GET" && url.pathname === "/health") return [200, { ok: true, memories: hmem.store.all().length }];
  if (req.method === "POST" && url.pathname === "/remember") {
    const b = await body(req);
    if (!b.houseId || !b.kind || !b.content) return [400, { error: "houseId, kind and content are required" }];
    const previous = live(b.houseId).find((m: any) => m.tags.includes(`kind:${b.kind}`));
    if (previous && previous.content === b.content) return [200, { memory: view(previous), unchanged: true }];
    const record = hmem.add({
      content: b.content,
      type: b.kind === "outcome" ? "factual" : "personal",
      tags: [tag(b.houseId), `kind:${b.kind}`],
      confidence: b.kind === "outcome" ? 0.8 : 0.95,
      source: b.kind === "outcome" ? "retrofit-check:agent" : "retrofit-check:homeowner",
      provenance: { origin: b.kind === "outcome" ? "decision" : "user_explicit", learnedAt: Date.now(), label: b.label ?? (b.kind === "outcome" ? "the agent's last check" : "you told us") },
      supersedes: previous?.id,
    });
    if (previous) hmem.store.update(previous.id, { supersededBy: record.id }); // kept and penalised in ranking, never deleted
    return [200, { memory: view(record), superseded: previous ? view(previous) : null }];
  }
  if (req.method === "POST" && url.pathname === "/recall") {
    const b = await body(req);
    const own = new Set(live(b.houseId).map((m: any) => m.id));
    const result = hmem.query(b.query ?? "heating ownership corrections last check", { topN: 20, threshold: 0 });
    const hits = result.memories.filter((r: any) => own.has(r.memory.id)).map((r: any) => ({ ...view(r.memory), relevance: Number(r.relevance.toFixed(3)) }));
    const missing = [...own].filter((id) => !hits.some((h) => h.id === id)).map((id) => view(hmem.store.get(id)));
    return [200, { memories: [...hits, ...missing], strategy: result.trace.strategy }];
  }
  if (req.method === "POST" && url.pathname === "/feedback") {
    const b = await body(req);
    hmem.feedback(b.id, b.kind);
    return [200, { memory: view(hmem.store.get(b.id)) }];
  }
  if (req.method === "GET" && url.pathname.startsWith("/audit/")) {
    return [200, { history: hmem.ledger.history(url.pathname.slice(7)) }];
  }
  return [404, { error: "not found" }];
}

http.createServer(async (req, res) => {
  let status = 500, out: Json = {};
  try { [status, out] = await route(req); } catch (e: any) { out = { error: String(e?.message ?? e) }; }
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(out));
}).listen(PORT, "127.0.0.1", () => console.log(`H-MEM (Meterless reference, unchanged) on http://127.0.0.1:${PORT}, ${hmem.store.all().length} memories`));
