"""Build docs/: a static replay page of the recorded sample runs, for GitHub Pages. No server, no keys in git:
.github/workflows/pages.yml adds the Google 3D key from the repository secret PAGES_GOOGLE_MAPS_API_KEY when it deploys.

Run: .venv/bin/python scripts/build_static.py   (then: python3 -m http.server -d docs 5176)
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrofit.server import area  # noqa: E402  same area outline and edge band as the app

ROOT = Path(__file__).resolve().parent.parent
WEB, SAMPLES, OUT = ROOT / "web", ROOT / "samples", ROOT / "docs"


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "samples" / "areas").mkdir(parents=True)
    html = (WEB / "index.html").read_text()
    html = html.replace('<script src="/config.js"></script>', '<script>window.GOOGLE_MAPS_API_KEY = ""; window.STATIC_SITE = true;</script>')
    html = html.replace("/static/", "")
    html = html.replace("<title>Retrofit Check</title>", "<title>Retrofit Check</title>\n<meta name=\"description\" content=\"Can I put solar panels on my house, and where? Replays of recorded agent runs.\">")
    (OUT / "index.html").write_text(html)
    for f in ("app.js", "app.css", "demo.js"):
        shutil.copy(WEB / f, OUT / f)
    index = json.loads((SAMPLES / "index.json").read_text())
    (OUT / "samples" / "index.json").write_text(json.dumps(index, indent=1))
    entities = set()
    for x in index:
        run = json.loads((SAMPLES / x["file"]).read_text())
        (OUT / "samples" / x["file"]).write_text(json.dumps(run))
        entities |= {a["entity"] for a in run["result"].get("areas", []) if a.get("entity")}
    for e in sorted(entities):
        (OUT / "samples" / "areas" / f"{e}.json").write_text(json.dumps(area(int(e))))
    (OUT / ".nojekyll").write_text("")
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"docs/: {len(index)} runs, {len(entities)} areas, {size // 1024} KB")


if __name__ == "__main__":
    main()
