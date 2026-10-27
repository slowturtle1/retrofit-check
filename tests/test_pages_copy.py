"""GitHub Pages serves docs/, the replay site judges open first. Its page code must be the app's own code in web/:
only index.html differs (no server, so STATIC_SITE and the Pages key).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pages_runs_the_same_page_code_as_the_app():
    for name in ("app.js", "app.css", "demo.js"):
        assert (ROOT / "docs" / name).read_bytes() == (ROOT / "web" / name).read_bytes(), f"docs/{name} differs from web/{name}: copy it over"


def test_pages_page_is_the_static_replay_site():
    page = (ROOT / "docs" / "index.html").read_text()
    assert "window.STATIC_SITE = true" in page
    assert 'window.GOOGLE_MAPS_API_KEY = ""' in page, "the Pages key is added by the workflow from a secret, never committed"


def test_pages_has_a_link_preview_picture():
    page = (ROOT / "docs" / "index.html").read_text()
    assert '<meta property="og:image" content="https://slowturtle1.github.io/retrofit-check/og.jpg">' in page
    assert (ROOT / "docs" / "og.jpg").read_bytes() == (ROOT / "media" / "og.jpg").read_bytes()
