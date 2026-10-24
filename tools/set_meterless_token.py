# Puts the Nightshift Runtime API key from the clipboard into .env and tests it.
# Copy the key in Nightshift > Console > API key first. The key is never printed.
# Run: .venv/bin/python tools/set_meterless_token.py

import re
import subprocess
from pathlib import Path

import requests

ENV = Path(__file__).resolve().parent.parent / ".env"
NAME = "METERLESS_RUNTIME_TOKEN"

token = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
if not token:
    raise SystemExit("Clipboard is empty. Copy the API key in Nightshift > Console first.")
if re.search(r"\s", token) or "://" in token or len(token) > 200:
    raise SystemExit("Clipboard does not look like an API key. Copy only the key, with the copy button.")

lines = ENV.read_text(encoding="utf-8").splitlines()
lines = [f"{NAME}={token}" if line.startswith(NAME + "=") else line for line in lines]
ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
ENV.chmod(0o600)
print(f"Saved to .env ({len(token)} characters).")

base = "http://127.0.0.1:8088/v1"
for line in lines:
    if line.startswith("METERLESS_BASE_URL="):
        base = line.split("=", 1)[1].strip().rstrip("/")
response = requests.get(
    base + "/models",
    headers={"Authorization": "Bearer " + token, "meterless-app": "open-agent-hack"},
    timeout=30,
)
if response.status_code == 200:
    ids = [m.get("id") for m in response.json().get("data", [])]
    print(f"Nightshift accepted the key. {len(ids)} routes, for example: {', '.join(ids[:6])}")
elif response.status_code in (401, 403):
    print("Nightshift still says unauthorized. This is not the Console API key, or it changed after copying.")
else:
    print(f"Nightshift answered {response.status_code}. Is Nightshift running?")
