"""Client for the H-MEM service (hmem/server.ts, Meterless reference engine)."""

from __future__ import annotations

import requests

from ..config import env


def _url(path: str) -> str:
    return env("HMEM_URL", "http://127.0.0.1:8790") + path


def available() -> bool:
    try:
        return requests.get(_url("/health"), timeout=3).ok
    except requests.RequestException:
        return False


def remember(house_id: str, kind: str, content: str, label: str | None = None) -> dict:
    r = requests.post(_url("/remember"), json={"houseId": house_id, "kind": kind, "content": content, "label": label}, timeout=10)
    r.raise_for_status()
    return r.json()


def recall(house_id: str, query: str = "electricity use heating gas oil ownership corrections road lane last check") -> list[dict]:
    r = requests.post(_url("/recall"), json={"houseId": house_id, "query": query}, timeout=10)
    r.raise_for_status()
    return r.json()["memories"]


def feedback(memory_id: str, kind: str) -> dict:
    r = requests.post(_url("/feedback"), json={"id": memory_id, "kind": kind}, timeout=10)
    r.raise_for_status()
    return r.json()
