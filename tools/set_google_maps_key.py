# Puts the Google Maps Platform API key from the clipboard into .env and tests it
# with one Photorealistic 3D Tiles root request. The key is never printed.
# Copy the key in Google Cloud > APIs & Services > Credentials first.
# Run: .venv/bin/python tools/set_google_maps_key.py

import re
import subprocess
from pathlib import Path

import requests

ENV = Path(__file__).resolve().parent.parent / ".env"
NAME = "GOOGLE_MAPS_API_KEY"
# The key is restricted to these referrers, so the test sends one of them.
REFERER = "http://localhost:5173/"

key = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
if not key:
    raise SystemExit("Clipboard is empty. Copy the API key in Google Cloud > Credentials first.")
if re.search(r"\s", key) or "://" in key or len(key) > 100:
    raise SystemExit("Clipboard does not look like an API key. Copy only the key, with the copy button.")
if not key.startswith("AIza"):
    print("Note: Google API keys usually start with AIza. Saving it anyway.")

lines = ENV.read_text(encoding="utf-8").splitlines()
if any(line.startswith(NAME + "=") for line in lines):
    lines = [f"{NAME}={key}" if line.startswith(NAME + "=") else line for line in lines]
else:
    lines += ["", "# Display only: Google Photorealistic 3D Tiles (Map Tiles API).", f"{NAME}={key}"]
ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
ENV.chmod(0o600)
print(f"Saved to .env ({len(key)} characters).")

response = requests.get(
    "https://tile.googleapis.com/v1/3dtiles/root.json",
    params={"key": key},
    headers={"Referer": REFERER},
    timeout=30,
)
if response.status_code == 200 and "root" in response.text[:2000]:
    print("Google accepted the key: Photorealistic 3D Tiles root loaded (1 root request used).")
else:
    try:
        message = response.json().get("error", {}).get("message", "")
    except ValueError:
        message = response.text[:300]
    message = message.replace(key, "[key]")
    print(f"Google answered {response.status_code}: {message}")
    if "not been used" in message or "disabled" in message:
        print("Enable Map Tiles API in this project, wait a minute, run again.")
    elif "billing" in message.lower():
        print("Link a billing account to this project, then run again.")
    elif "referer" in message.lower() or "referrer" in message.lower():
        print("Add http://localhost:5173/* and http://127.0.0.1:5173/* under Website restrictions.")
    elif "API" in message and "restrict" in message.lower():
        print("Under API restrictions, allow Map Tiles API.")
