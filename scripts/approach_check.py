"""Check every requirement in approach/requirements.yaml and write the scorecard.

Run: make approach            (Tiers 1 to 3; exit 1 on any gap)
     make approach-live       (also Tier 4: Zetaris, H-MEM, GitHub, files outside the repo)

Writes approach/report.md (grouped by judging criterion) and approach/report.json. One pytest run
answers every test check; a pending test (xfail, see tests/conftest.py) counts as a gap and names
the item it waits for. Manual items show their owner and evidence, and never fail the run.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQS = ROOT / "approach" / "requirements.yaml"
OUT_MD, OUT_JSON = ROOT / "approach" / "report.md", ROOT / "approach" / "report.json"
GATING = {"gap", "pending", "missing"}
ORDER = ["gap", "missing", "pending", "not_run", "manual_open", "manual_done", "na", "pass"]
LABEL = {"pass": "pass", "gap": "GAP", "pending": "pending", "missing": "test missing", "not_run": "not run",
         "manual_open": "manual (open)", "manual_done": "manual (done)", "na": "n/a"}


def sh(*cmd, cwd=ROOT, timeout=120, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(errors="replace") if p.exists() else ""


def py_files(*dirs: str) -> list[Path]:
    return [p for d in dirs for p in sorted((ROOT / d).rglob("*.py"))]


def ok(detail="") -> tuple[str, str]:
    return "pass", detail


def gap(detail) -> tuple[str, str]:
    return "gap", detail


# ------------------------------------------------------------------ Tier 1: repository

SECRETS = [
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("NVIDIA key", r"nvapi-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI or Anthropic style key", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    ("GitHub token", r"\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{30,}"),
    ("AWS key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("private key", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ("Slack token", r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    ("assigned secret", r"(?i)\b[A-Z_]*(?:API_KEY|TOKEN|PASSWORD|SECRET)\s*=\s*['\"]?[A-Za-z0-9_\-./+]{16,}"),
]
ALLOW = [("scripts/make_samples.py", "SECRET = re.compile")]   # the scan pattern itself


def secret_scan(**_):
    log = sh("git", "log", "--all", "-p", "--no-color", "--no-ext-diff", timeout=300).stdout
    hits, path = [], "?"
    for line in log.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for name, pat in SECRETS:
            if re.search(pat, line) and not any(path == p and s in line for p, s in ALLOW):
                hits.append(f"{name} in {path}")
    commits = sh("git", "rev-list", "--all", "--count").stdout.strip()
    return gap("; ".join(sorted(set(hits)))) if hits else ok(f"{commits} commits scanned, no secret found")


def secret_files(**_):
    tracked = sh("git", "ls-files").stdout.splitlines()
    bad = [f for f in tracked if re.search(r"(^|/)\.env$|\.env\.(?!example$)|\.pem$|\.key$|(^|/)(secrets|credentials)/", f)]
    ignore = read(".gitignore")
    missing = [p for p in (".env", ".env.*", "!.env.example", "*.pem", "*.key", "secrets/", "credentials/") if p not in ignore.split()]
    if bad or missing:
        return gap("; ".join(filter(None, [bad and f"tracked: {', '.join(bad)}", missing and f".gitignore lacks {', '.join(missing)}"])))
    return ok("no secret files tracked; .gitignore covers .env, .env.*, *.pem, *.key, secrets/, credentials/")


def env_example_placeholders(**_):
    bad = []
    for line in read(".env.example").splitlines():
        m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
        if m and re.search(r"KEY|TOKEN|PASSWORD|SECRET", m.group(1)):
            v = m.group(2).strip().strip("'\"")
            if v and not re.match(r"^(\$\{[A-Z0-9_]+\}|your[-_a-z]*|<[^>]+>|changeme|xxx+)$", v, re.I):
                bad.append(m.group(1))
    return gap("real looking values for " + ", ".join(bad)) if bad else ok("every key, token and password is empty or a placeholder")


def repo_size(max_pack_mb=5, max_file_mb=1, **_):
    stats = dict(l.split(": ") for l in sh("git", "count-objects", "-v").stdout.splitlines() if ": " in l)
    pack_mb = (int(stats.get("size-pack", 0)) + int(stats.get("size", 0))) / 1024
    files = [(os.path.getsize(ROOT / f), f) for f in sh("git", "ls-files").stdout.splitlines() if (ROOT / f).is_file()]
    big = [f"{f} ({s / 1e6:.1f} MB)" for s, f in files if s > max_file_mb * 1e6]
    heavy = [f for _, f in files if re.search(r"\.(zip|tar|gz|tgz|7z|mp4|mov|avi|pt|ckpt|h5|onnx|parquet|tif|tiff|las|laz)$", f, re.I)]
    largest = max(files)[1] if files else "-"
    detail = f"git objects {pack_mb:.1f} MB, largest tracked file {largest} ({max(files)[0] / 1e3:.0f} KB)" if files else ""
    if pack_mb > max_pack_mb or big or heavy:
        return gap("; ".join(filter(None, [detail, big and "over the limit: " + ", ".join(big), heavy and "heavy files: " + ", ".join(heavy)])))
    return ok(detail)


def files_exist(paths=(), **_):
    missing = [p for p in paths if not (ROOT / p).exists()]
    return gap("missing: " + ", ".join(missing)) if missing else ok(", ".join(paths))


def _sections(md: str) -> list[tuple[str, str]]:
    parts = re.split(r"^(#{1,6} .*)$", md, flags=re.M)
    return [(parts[i].lstrip("#").strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def readme_limitations(min=3, **_):
    sec = [(h, b) for h, b in _sections(read("README.md")) if re.search(r"limit", h, re.I)]
    if not sec:
        return gap("no limitations section in README.md")
    n = len(re.findall(r"^\s*[-*] ", sec[0][1], re.M))
    return ok(f"'{sec[0][0]}': {n} points") if n >= min else gap(f"'{sec[0][0]}' has {n} points, want {min}")


def readme_diagram(**_):
    md = read("README.md")
    blocks = re.findall(r"```mermaid\n(.*?)```", md, re.S)
    if not blocks:
        chain = "an ASCII chain" if re.search(r"─►|-->|->", md) else "no diagram"
        return gap(f"no Mermaid diagram (README has {chain})")
    b = "\n".join(blocks)
    loops = len(re.findall(r'--\s*"[^"]+"\s*-->|-->\|[^|]+\|', b))
    names = all(re.search(n, b, re.I) for n in ("evaluator", "analyst", "zetaris"))
    if loops < 2 or not names:
        return gap(f"Mermaid diagram has {loops} labelled edges (want 2 or more) and {'names' if names else 'does not name'} evaluator, analyst and Zetaris")
    return ok(f"Mermaid diagram with {loops} labelled edges")


def _readme_patterns(patterns: list[str]) -> tuple[str, str]:
    md = read("README.md")
    if not md:
        return gap("README.md missing")
    missing = [p for p in patterns if not re.search(p, md, re.I | re.M)]
    return gap("README.md lacks: " + "; ".join(missing)) if missing else ok(f"README.md matches {len(patterns)} patterns")


DATA_FIELDS = {"URL": r"url|link|source", "licence": r"licen[cs]e", "subset": r"subset|what we use|scope",
               "record count": r"record|rows|count", "Zetaris registration": r"zetaris", "regenerate": r"regenerat|refresh|rebuild",
               "limits": r"limit"}


def data_readme(**_):
    md = read("data/README.md")
    if not md:
        return gap("data/README.md missing")
    for table in re.findall(r"((?:^\|.*\|\s*\n)+)", md, re.M):
        rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in table.strip().splitlines()]
        head = rows[0]
        cols = {f: next((i for i, h in enumerate(head) if re.search(p, h, re.I)), None) for f, p in DATA_FIELDS.items()}
        if sum(c is not None for c in cols.values()) >= 4:
            missing = [f for f, c in cols.items() if c is None]
            body = [r for r in rows[2:] if any(r)]
            empty = [f"{r[0][:30]}: {f}" for r in body for f, c in cols.items() if c is not None and (c >= len(r) or not r[c])]
            if missing or empty:
                return gap("; ".join(filter(None, [missing and "source table has no column for " + ", ".join(missing), empty and "empty cells: " + ", ".join(empty[:6])])))
            return ok(f"{len(body)} sources, seven fields each")
    secs = [(h, b) for h, b in _sections(md) if h.lower() not in ("data sources", "data")]
    per = {h: [f for f, p in DATA_FIELDS.items() if not re.search(p, h + b, re.I)] for h, b in secs if re.search(r"https?://", b)}
    bad = {h: m for h, m in per.items() if m}
    if per and not bad:
        return ok(f"{len(per)} source sections, seven fields each")
    return gap("want one table with columns URL, licence, subset, records, Zetaris, regenerate, limits (or one section per source with all seven); "
               + ("; ".join(f"{h[:30]} lacks {', '.join(m)}" for h, m in list(bad.items())[:4]) if bad else "no source table found"))


WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14}


def _db_tables() -> int:
    return sum(len(re.findall(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?\w+", p.read_text(), re.I)) for p in sorted((ROOT / "db/init").glob("*.sql")))


def _cache_tables() -> int:
    con = sqlite3.connect(f"file:{ROOT / 'samples/cache.sqlite'}?mode=ro", uri=True)
    try:
        return con.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
    finally:
        con.close()


def table_counts(**_):
    db, cache = _db_tables(), _cache_tables()
    bad = []
    for rel in ("README.md", "data/README.md"):
        for m in re.finditer(r"\b(\d+|" + "|".join(WORDS) + r")\s+(?:\w+\s+)?tables\b", read(rel), re.I):
            n = int(m.group(1)) if m.group(1).isdigit() else WORDS[m.group(1).lower()]
            if n not in (db, cache):
                bad.append(f"{rel} says '{m.group(0)}'")
    detail = f"retrofit_pg has {db} tables (db/init), the sample snapshot {cache}"
    return gap(detail + "; " + "; ".join(bad)) if bad else ok(detail)


def no_gpu_deps(**_):
    bad = re.findall(r"^(torch|tensorflow|jax|cupy|nvidia-[\w-]+)\b", read("requirements.txt"), re.M | re.I)
    return gap("GPU packages: " + ", ".join(bad)) if bad else ok("no torch, tensorflow, jax or CUDA packages")


def _calls(path: Path):
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def timeouts(**_):
    bad, n = [], 0
    for p in py_files("retrofit"):
        for c in _calls(p):
            f = c.func
            name = f"{getattr(f.value, 'id', '')}.{f.attr}" if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if re.match(r"^(requests|httpx|session)\.(get|post|put|delete|request)$|^urlopen$", name):
                n += 1
                if not any(k.arg == "timeout" for k in c.keywords):
                    bad.append(f"{p.relative_to(ROOT)}:{c.lineno}")
    return gap("no timeout: " + ", ".join(bad)) if bad else ok(f"{n} HTTP calls in retrofit/, every one with a timeout")


def bounded_retries(**_):
    src = read("retrofit/agent/llm.py")
    m = re.search(r"def chat\([^)]*retries:\s*int\s*=\s*(\d+)", src, re.S)
    retries = int(m.group(1)) if m else None
    rounds = re.search(r"for round_no in \((\d+(?:,\s*\d+)*)\)", read("retrofit/agent/run.py"))
    loops = [f"{p.relative_to(ROOT)}" for p in py_files("retrofit") if re.search(r"^\s*while True\b", p.read_text(), re.M)]
    loops = [l for l in loops if l != "retrofit/server.py"]   # the event stream loop ends when the run ends
    problems = []
    if retries is None or retries > 2:
        problems.append(f"model retries {retries}")
    if not rounds or len(rounds.group(1).split(",")) > 2:
        problems.append("rewrite rounds not capped at 2")
    if loops:
        problems.append("while True in " + ", ".join(loops))
    return gap("; ".join(problems)) if problems else ok(f"model retries {retries}, rewrite rounds {rounds.group(1)}, no unbounded loops")


def no_saved_outputs(**_):
    bad = []
    for p in py_files("retrofit"):
        t = p.read_text()
        if "output_examples" in t:
            bad.append(f"{p.relative_to(ROOT)} reads output_examples/")
        if p.name not in ("server.py", "offline.py") and re.search(r"samples/[\w-]+\.json|SAMPLES\s*/", t):
            bad.append(f"{p.relative_to(ROOT)} reads a saved sample run")
    return gap("; ".join(bad)) if bad else ok("no agent code reads output_examples/ or saved runs (server.py serves labelled replays only)")


def no_runtime_installs(**_):
    bad = [f"{p.relative_to(ROOT)}" for p in py_files("retrofit") if re.search(r"pip install|npm install|urlretrieve|ensurepip", p.read_text())]
    return gap("installs at runtime: " + ", ".join(bad)) if bad else ok("no installs or downloads of packages in retrofit/")


def single_model_client(**_):
    hits = [f"{p.relative_to(ROOT)}" for p in py_files("retrofit") if re.search(r"chat/completions|^\s*(from openai|import openai)", p.read_text(), re.M)]
    base = re.search(r'env\("METERLESS_BASE_URL"', read("retrofit/agent/llm.py"))
    if hits != ["retrofit/agent/llm.py"] or not base:
        return gap(f"model clients: {hits or 'none'}; Nightshift base URL from METERLESS_BASE_URL: {bool(base)}")
    return ok("retrofit/agent/llm.py is the only model client, pointed at Nightshift (METERLESS_BASE_URL)")


def _pinned() -> tuple[str | None, str | None]:
    ex = re.search(r"^METERLESS_MODEL=(\S+)", read(".env.example"), re.M)
    code = re.search(r'env\("METERLESS_MODEL",\s*"([^"]+)"\)', read("retrofit/agent/llm.py"))
    return (ex.group(1) if ex else None), (code.group(1) if code else None)


def model_pinned(**_):
    ex, code = _pinned()
    if not ex or ex != code or "nemotron" not in ex.lower() or "auto" in ex.lower():
        return gap(f".env.example {ex!r}, code default {code!r}: want the same NVIDIA Nemotron id, not meterless/auto")
    return ok(f"pinned to {ex} in .env.example and retrofit/agent/llm.py")


def _logged_models() -> set[str]:
    out = set()
    for p in (ROOT / "samples").glob("*.json"):
        d = json.loads(p.read_text())
        if isinstance(d, dict):
            out |= {str(e.get("routed_model") or e.get("model")) for e in d.get("events", []) if e.get("type") == "model" and e.get("ok")}
    return out - {"None"}


def readme_model_matches_logs(**_):
    named = set(re.findall(r"nvidia/[\w.\-]+", read("README.md")))
    logged, (pinned, _) = _logged_models(), _pinned()
    if not named:
        return gap("README.md names no NVIDIA model id")
    extra = named - logged
    if extra or pinned not in named:
        return gap(f"README names {sorted(named)}; logs show {sorted(logged)}; pinned {pinned}")
    return ok(f"README names {', '.join(sorted(named))}, the model in the recorded receipts")


def sponsor_settings_from_env(**_):
    need = {"retrofit/zetaris.py": ["ZETARIS_REST_URL", "ZETARIS_API_KEY"], "retrofit/agent/llm.py": ["METERLESS_BASE_URL", "METERLESS_RUNTIME_TOKEN", "METERLESS_MODEL"],
            "retrofit/agent/memory.py": ["HMEM_URL"]}
    missing = [f"{f}: {v}" for f, vs in need.items() for v in vs if not re.search(rf"(env|getenv|environ(\.get)?)\(\s*[\"']{v}[\"']|environ\[[\"']{v}[\"']\]", read(f))]
    return gap("not read from the environment: " + ", ".join(missing)) if missing else ok("Zetaris, Nightshift and H-MEM settings all come from environment variables")


def sample_houses(min=21, **_):
    con = sqlite3.connect(f"file:{ROOT / 'samples/cache.sqlite'}?mode=ro", uri=True)
    try:
        have = {r[0] for r in con.execute("SELECT house_id FROM house")}
    finally:
        con.close()
    cases = json.loads(read("eval/cases.json") or "{}").get("cases", [])
    missing = [c["id"] for c in cases if c["id"] not in have]
    if len(have) < min or missing:
        return gap(f"{len(have)} houses in the snapshot (want {min}); {len(missing)} evaluation houses missing")
    return ok(f"{len(have)} houses, all {len(cases)} evaluation houses included")


def examples(min=3, **_):
    sys.path.insert(0, str(ROOT))
    from retrofit import schema
    ins, outs = sorted((ROOT / "input_examples").glob("*.json")), sorted((ROOT / "output_examples").glob("*.json"))
    problems = []
    for p in ins:
        body = json.loads(p.read_text())
        if not (body.get("way") or (body.get("lat") is not None and body.get("lon") is not None)):
            problems.append(f"{p.name}: no way or lat and lon")
    for p in outs:
        a = json.loads(p.read_text())
        bad = schema.check_answer(a)
        if bad:
            problems.append(f"{p.name}: {bad[0]}")
        elif not a.get("run_id"):
            problems.append(f"{p.name}: no run_id, so not a saved real run")
    if len(ins) < min or len(outs) < min or problems:
        return gap(f"{len(ins)} inputs, {len(outs)} outputs (want {min} each)" + ("; " + "; ".join(problems[:4]) if problems else ""))
    return ok(f"{len(ins)} inputs, {len(outs)} saved outputs, every output passes the answer contract")


SELF_SCORE = ["30 seconds", "who the user", "accessible data", "144 hours", "quickly and predictably", "real role",
              "more than once", "critique", "minute demo", "limitations"]
WORKSHEET = ["Selected track", "Problem statement", "Target user", "Decision supported", "Final output", "What we will build",
             "What we will not build", "Main demo scenario", "Pre-existing components", "Primary data source",
             "How it is registered in Zetaris", "Static data size", "Runtime API required", "Fallback sample mode", "Licensing"]


def worksheet(**_):
    md = read("approach/worksheet.md")
    if not md:
        return gap("approach/worksheet.md missing")
    empty = []
    for label in WORKSHEET:
        m = re.search(rf"{re.escape(label)}[^\n:|]*[:|]\s*(.*)", md, re.I)
        if not m or not m.group(1).strip(" |*_"):
            empty.append(label)
    return gap("empty or missing: " + ", ".join(empty)) if empty else ok(f"all {len(WORKSHEET)} fields of section 21 filled")


def self_score(min=16, **_):
    md = read("approach/worksheet.md")
    rows = [l for l in md.splitlines() if l.strip().startswith("|")]
    total, found, unlinked = 0, [], []
    for q in SELF_SCORE:
        row = next((r for r in rows if q.lower() in r.lower()), None)
        if not row:
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        score = next((int(c) for c in cells[1:] if re.fullmatch(r"[012]", c)), None)
        if score is None:
            continue
        found.append(q)
        total += score
        if not re.search(r"\]\(|`[^`]*[/.][^`]*`|https?://", row):
            unlinked.append(q)
    if len(found) < 10:
        return gap(f"self score table has {len(found)} of 10 questions with a 0 to 2 score")
    if total < min or unlinked:
        return gap(f"{total} of 20 (want {min})" + (f"; no evidence link: {', '.join(unlinked)}" if unlinked else ""))
    return ok(f"{total} of 20, every question with evidence")


# ------------------------------------------------------------------ Tier 2 and 3 helpers

def fresh_clone_sample_mode(**_):
    script = ("import json,sys,time\nfrom retrofit.offline import houses\nfrom retrofit.agent.run import Run\nfrom retrofit import schema\n"
              "t=time.time();out=[]\nfor h in houses():\n"
              "    w=int(h['house_id'].rsplit('-',1)[1]) if h['house_id'].startswith('osm-way-') else None\n"
              "    r=Run(offline=True).check(way=w,lat=None if w else h['lat'],lon=None if w else h['lon'])\n"
              "    out.append([h['label'],r['answer']['solar']['status'],schema.check_answer(r['answer'])])\n"
              "print(json.dumps({'seconds':round(time.time()-t,1),'houses':out}))\n")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "clone"
        c = sh("git", "clone", "-q", "--no-hardlinks", str(ROOT), str(dest), timeout=120)
        if c.returncode:
            return gap(f"git clone failed: {c.stderr[:200]}")
        env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "SAMPLE_MODE": "true", "LOG_STDOUT": "false"}
        started = time.time()
        r = sh(sys.executable, "-c", script, cwd=dest, timeout=300, env=env)
        if r.returncode:
            return gap(f"sample run failed in the clone: {(r.stderr or r.stdout).strip().splitlines()[-1][:200]}")
        res = json.loads(r.stdout.strip().splitlines()[-1])
    bad = [h for h in res["houses"] if h[2]]
    if bad or not res["houses"]:
        return gap(f"{len(bad)} answers break the contract: {bad[0][0]}: {bad[0][2][0]}" if bad else "no house answered")
    return ok(f"fresh clone of HEAD, empty environment: {len(res['houses'])} houses answered in {res['seconds']} s ({time.time() - started:.0f} s with startup)")


def eval_results(**_):
    cases = json.loads(read("eval/cases.json") or "{}")
    body = json.dumps(cases.get("cases", []), indent=1, sort_keys=True)
    if hashlib.sha256(body.encode()).hexdigest() != cases.get("sha256"):
        return gap("eval/cases.json no longer matches its frozen hash")
    res = json.loads(read("eval/results.json") or "{}")
    s = (res.get("summary") or {}).get("retrofit-check") or {}
    if s.get("measures") != ["solar"]:
        return gap("eval/results.json has no solar only summary yet (B6)")
    if s.get("right") != s.get("of") or s.get("confident_wrong"):
        return gap(f"Retrofit Check {s.get('right')} of {s.get('of')}, {s.get('confident_wrong')} confidently wrong")
    others = ", ".join(f"{k} {v['right']} of {v['of']}" for k, v in res["summary"].items() if k != "retrofit-check")
    return ok(f"Retrofit Check {s['right']} of {s['of']}, 0 confidently wrong; {others}; cases hash unchanged")


# ------------------------------------------------------------------ Tier 4: live and outside the repo

def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def local_file_mentions(path, patterns=(), **_):
    p = _expand(path)
    if not p.exists():
        return gap(f"{path} missing")
    t = p.read_text(errors="replace")
    missing = [x for x in patterns if not re.search(x, t, re.I)]
    return gap(f"{p.name} lacks: {', '.join(missing)}") if missing else ok(f"{p.name} names all {len(patterns)}")


def same_track_everywhere(**_):
    deck = _expand("~/Documents/hackathon/retrofit/deck/v3/project")
    texts = {"README.md": read("README.md"),
             "form.md": _expand("~/Documents/hackathon/retrofit/submission/form.md"),
             "video-script.md": _expand("~/Documents/hackathon/retrofit/submission/video-script.md")}
    texts = {k: (v.read_text(errors="replace") if isinstance(v, Path) and v.exists() else v if isinstance(v, str) else "") for k, v in texts.items()}
    texts["deck v3"] = " ".join(p.read_text(errors="replace") for p in deck.rglob("*") if p.suffix in (".html", ".js", ".json", ".md")) if deck.exists() else ""
    missing = [k for k, t in texts.items() if not re.search(r"Solving Fragmented Intelligence|Track 1\b", t)]
    return gap("track not named in: " + ", ".join(missing)) if missing else ok("README, deck, form and video script all name Track 1, Solving Fragmented Intelligence")


def video_duration(path, **_):
    p = _expand(path)
    if not p.exists():
        return gap(f"{path} missing")
    r = sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p))
    secs = float(r.stdout.strip() or 0)
    return ok(f"{secs:.0f} s") if 60 <= secs <= 240 else gap(f"{secs:.0f} s, want 60 to 240")


def video_script(path, **_):
    p = _expand(path)
    if not p.exists():
        return gap(f"{path} missing")
    t = p.read_text()
    segs = len(set(re.findall(r"\b[0-3]:[0-5]\d\b", t)))
    need = {"Hampstead": r"Hampstead", "electricity recall": r"electricity", "recording checklist": r"checklist", "no keys on screen": r"keys"}
    missing = [k for k, pat in need.items() if not re.search(pat, t, re.I)]
    if segs < 7 or missing:
        return gap(f"{segs} time marks (want the six segment bounds)" + (f"; lacks {', '.join(missing)}" if missing else ""))
    return ok(f"{segs} time marks, demo path and checklist present")


def repo_public(**_):
    url = sh("git", "remote", "get-url", "origin").stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    if not m:
        return gap("no GitHub origin")
    r = sh("gh", "repo", "view", m.group(1), "--json", "visibility", "-q", ".visibility")
    vis = r.stdout.strip() or r.stderr.strip()[:80]
    return ok(f"{m.group(1)} is public") if vis == "PUBLIC" else gap(f"{m.group(1)} is {vis or 'unknown'}")


def zetaris_live(**_):
    code = ("from retrofit.zetaris import Zetaris\nz=Zetaris()\n"
            "print(len(z.run('SELECT house_id FROM retrofit_pg.house LIMIT 5', purpose='approach check').rows))")
    r = sh(sys.executable, "-c", code, timeout=180)
    return ok(f"retrofit_pg answered through Zetaris ({r.stdout.strip()} rows)") if r.returncode == 0 else gap((r.stderr.strip().splitlines() or ["no output"])[-1][:200])


def hmem_conformance(**_):
    if not (ROOT / "hmem/node_modules").exists():
        return gap("hmem/node_modules missing: cd hmem && npm install && npm run setup")
    r = sh("npm", "run", "conformance", cwd=ROOT / "hmem", timeout=300)
    m = re.findall(r"(\d+)\s*/\s*(\d+)", r.stdout)
    detail = f"{m[-1][0]}/{m[-1][1]}" if m else (r.stdout.strip().splitlines() or ["?"])[-1][:120]
    return ok(f"conformance {detail}") if r.returncode == 0 else gap(f"conformance failed: {detail}")


FNS = {f.__name__: f for f in (secret_scan, secret_files, env_example_placeholders, repo_size, files_exist, readme_limitations,
                               readme_diagram, data_readme, table_counts, no_gpu_deps, timeouts, bounded_retries, no_saved_outputs,
                               no_runtime_installs, single_model_client, model_pinned, readme_model_matches_logs,
                               sponsor_settings_from_env, sample_houses, examples, worksheet, self_score, fresh_clone_sample_mode,
                               eval_results, local_file_mentions, same_track_everywhere, video_duration, video_script, repo_public,
                               zetaris_live, hmem_conformance)}


# ------------------------------------------------------------------ pytest, once

def run_pytest(live: bool) -> dict[str, tuple[str, str]]:
    """node id -> (outcome, message); outcome is passed, failed, skipped or pending."""
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "junit.xml"
        env = {**os.environ, "LOG_STDOUT": "false"}
        if not live:
            env["SAMPLE_MODE"] = "true"
        sh(sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}", "-o", "junit_family=xunit1", "tests", timeout=900, env=env)
        if not xml.exists():
            return {}
        out = {}
        for tc in ET.parse(xml).getroot().iter("testcase"):
            node = tc.get("file") or tc.get("classname", "").replace(".", "/") + ".py"
            nid = f"{node}::{tc.get('name')}"
            fail = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
            skip = tc.find("skipped")
            if fail is not None:
                out[nid] = ("failed", (fail.get("message") or "")[:160])
            elif skip is not None:
                msg = skip.get("message") or ""
                pend = re.search(r"pending (\S+)", msg)
                out[nid] = ("pending", pend.group(1)) if pend else ("skipped", msg[:160])
            else:
                out[nid] = ("passed", "")
        return out


def check_tests(ids: list[str], results: dict, tier) -> tuple[str, str]:
    picked = {}
    for t in ids:
        found = {k: v for k, v in results.items() if k == t or k.startswith(t + "::") or (t.endswith(".py") and k.split("::")[0] == t)}
        if not found:
            return "missing", f"{t} not found"
        picked.update(found)
    failed = [k.split("::")[-1] for k, v in picked.items() if v[0] == "failed"]
    pend = sorted({v[1] for v in picked.values() if v[0] == "pending"})
    skipped = [k.split("::")[-1] for k, v in picked.items() if v[0] == "skipped"]
    if failed:
        return "gap", "failed: " + ", ".join(failed)
    if pend:
        return "pending", "waits for " + ", ".join(pend)
    if skipped:
        return ("not_run" if str(tier) == "4" else "gap"), "skipped: " + "; ".join(sorted({results[k][1] for k in picked if results[k][0] == "skipped"}))[:160]
    return "pass", f"{len(picked)} tests pass"


def evaluate(r: dict, results: dict, live: bool) -> dict:
    c, tier = r["check"], r["tier"]
    if c == "manual":
        return {"status": "manual_done" if r.get("done") else "manual_open", "detail": r.get("evidence", "")}
    if c == "na":
        return {"status": "na", "detail": r.get("evidence", "")}
    if str(tier) == "4" and not live:
        return {"status": "not_run", "detail": "Tier 4: run make approach-live on this Mac"}
    outcomes = []
    if "test" in c:
        outcomes.append(check_tests(c["test"], results, tier))
    if "readme" in c:
        outcomes.append(_readme_patterns(c["readme"]))
    if "fn" in c:
        args = {k: v for k, v in c.items() if k not in ("fn", "test", "readme")}
        try:
            outcomes.append(FNS[c["fn"]](**args))
        except Exception as e:  # a broken check is a gap, never a crash
            outcomes.append(("gap", f"check {c['fn']} failed: {type(e).__name__}: {str(e)[:120]}"))
    status = min((o[0] for o in outcomes), key=ORDER.index)
    return {"status": status, "detail": "; ".join(o[1] for o in outcomes if o[1])}


# ------------------------------------------------------------------ report

def _commit() -> str:
    return sh("git", "rev-parse", "--short", "HEAD").stdout.strip() + (" (uncommitted changes)" if sh("git", "status", "--porcelain", "--untracked-files=no").stdout.strip() else "")


def _cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _yes(ids, by_id) -> bool:
    return all(by_id[i]["status"] in ("pass", "manual_done", "na") for i in ids)


def write_report(spec: dict, rows: list[dict], live: bool) -> None:
    by_id = {r["id"]: r for r in rows}
    gating = [r for r in rows if str(r["tier"]) in ("1", "2", "3") and r["status"] in GATING]
    md = ["# Approach scorecard", "",
          f"Commit {_commit()}, {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M')} UTC, {'with' if live else 'without'} Tier 4 (live). "
          f"Source: `approach/requirements.yaml`, run with `make approach{'-live' if live else ''}`.", "",
          f"**{len(gating)} gaps in Tiers 1 to 3.** " + ", ".join(f"{sum(r['status'] == s for r in rows)} {LABEL[s]}" for s in ORDER if any(r['status'] == s for r in rows)) + f" (of {len(rows)} requirements).", ""]
    md += ["| Criterion | Points | Pass | Gaps (Tiers 1 to 3) | Manual open | Not run |", "|---|---|---|---|---|---|"]
    for key, crit in spec["criteria"].items():
        rs = [r for r in rows if r["criterion"] == key]
        md.append(f"| {crit['name']} | {crit['points'] or 'gate'} | {sum(r['status'] in ('pass', 'manual_done') for r in rs)} of {len(rs)} | "
                  f"{sum(r in gating for r in rs)} | {sum(r['status'] == 'manual_open' for r in rs)} | {sum(r['status'] == 'not_run' for r in rs)} |")
    collab = spec["closing"]["collaboration_checklist"]
    md += ["", f"Collaboration design checklist (guide section 9): {sum(by_id[i]['status'] == 'pass' for i in collab)} of {len(collab)} proven by a passing check.", ""]
    for key, crit in spec["criteria"].items():
        rs = sorted([r for r in rows if r["criterion"] == key], key=lambda r: (ORDER.index(r["status"]), r["id"]))
        md += [f"## {crit['name']}" + (f" ({crit['points']} points)" if crit["points"] else ""), "",
               "| Id | Requirement | Tier | Status | Evidence or detail | Owner |", "|---|---|---|---|---|---|"]
        md += [f"| {r['id']} | {_cell(r['text'])} | {r['tier']} | {LABEL[r['status']]} | {_cell(r['detail'] or r['evidence'])} | {r['owner']} |" for r in rs]
        md.append("")
    pend = [r for r in rows if r["status"] == "pending"]
    if pend:
        md += ["## Waiting for the lead", ""] + [f"- {r['id']}: {r['detail']}" for r in pend] + [""]
    for title, key in (("Guide section 22: can we say yes to all five?", "guide_22"), ("What judges should be able to say", "judges_should_say")):
        md += [f"## {title}", ""]
        for s in spec["closing"][key]:
            open_ids = [i for i in s["ids"] if by_id[i]["status"] not in ("pass", "manual_done", "na")]
            md.append(f"- {'Yes' if _yes(s['ids'], by_id) else 'Not yet'}: \"{s['text']}\" ({', '.join(s['ids'])}" + (f"; open: {', '.join(open_ids)}" if open_ids else "") + ")")
        md.append("")
    OUT_MD.write_text("\n".join(md))
    OUT_JSON.write_text(json.dumps({"commit": _commit(), "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "live": live, "gaps_tier_1_to_3": len(gating),
                                    "requirements": [{k: r[k] for k in ("id", "criterion", "tier", "status", "detail", "owner", "text", "source", "evidence")} for r in rows]},
                                   indent=1, default=str))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="also run Tier 4 (Zetaris, H-MEM, GitHub, files outside the repo)")
    ap.add_argument("--only", help="comma separated requirement ids")
    args = ap.parse_args()
    spec = yaml.safe_load(REQS.read_text())
    reqs = [r for r in spec["requirements"] if not args.only or r["id"] in args.only.split(",")]
    need_tests = any(isinstance(r["check"], dict) and "test" in r["check"] for r in reqs)
    results = run_pytest(args.live) if need_tests else {}
    rows = [{**r, **evaluate(r, results, args.live)} for r in reqs]
    if not args.only:
        write_report(spec, rows, args.live)
    gating = [r for r in rows if str(r["tier"]) in ("1", "2", "3") and r["status"] in GATING]
    for r in sorted(rows, key=lambda r: (ORDER.index(r["status"]), r["id"])):
        if r["status"] != "pass":
            print(f"{r['id']:<4} {LABEL[r['status']]:<13} {r['text'][:70]:<70}  {r['detail'][:110]}")
    print(f"\n{len(rows) - len([r for r in rows if r['status'] != 'pass'])} pass, {len(gating)} gaps in Tiers 1 to 3" + ("" if args.only else f"; report: {OUT_MD.relative_to(ROOT)}"))
    return 1 if gating else 0


if __name__ == "__main__":
    sys.exit(main())
