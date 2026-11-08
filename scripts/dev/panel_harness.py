"""Dev harness: the Finance frontend in a plain browser with demo data (not shipped).

Serves custom_components/finance_dashboard/frontend/ under /finance_dashboard_static/
and answers /api/finance_dashboard/* from the integration's demo generators, so a
component can be checked in light/dark, de/en, admin/member and at any width
without a Home Assistant instance. Writes (POST/PUT/DELETE) return {"ok": true}.

    python scripts/dev/panel_harness.py [--port 8765]
    http://localhost:8765/?el=fd-home            # Start (Heute/Woche/Zyklus/Jahr)
    http://localhost:8765/?el=fd-benchmark       # any other fd-* element
    &admin=0 &lang=en &theme=dark &width=375     # preset the toggles

Never loaded by the integration; nothing here talks to a bank.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "custom_components" / "finance_dashboard" / "frontend"
sys.path.insert(0, str(ROOT))

for _mod in ("fcntl", "resource"):  # POSIX-only stdlib modules some HA imports touch on Windows
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            sys.modules[_mod] = types.ModuleType(_mod)


def api(method: str, path: str, query: dict[str, list[str]]):
    """Answer one API call from the demo generators; unknown reads give {}."""
    from custom_components.finance_dashboard import demo

    q = {k: v[0] for k, v in query.items()}
    if path == "home" and method == "GET":
        view = q.get("view", "person")
        return demo.generate_demo_home(
            person="Anna" if view == "person" else None, view=view,
            horizon=q.get("horizon", "cycle"), include_recent=q.get("admin", "1") == "1",
        )
    if path == "review" and method == "GET":
        return demo.generate_demo_review()
    if path == "review/report" and method == "GET":
        return demo.generate_demo_report()
    if path == "benchmark" and method == "GET":
        return demo.generate_demo_benchmark()
    if path == "assignments" and method == "GET":
        return _demo_assignments()
    if method != "GET":
        return {"ok": True}
    return {}


def _demo_assignments() -> dict:
    """Settings → Konten: two invented persons and three invented accounts, one per owner set."""
    persons = [
        {"name": "Anna", "display_name": "Anna", "ha_users": ["u-anna"]},
        {"name": "Ben", "display_name": "Ben", "ha_users": ["u-ben"]},
    ]
    users = [
        {"id": f"u-{p['name'].lower()}", "name": p["name"], "is_admin": p["name"] == "Anna",
         "suggested": True, "reason": "person"}
        for p in persons
    ]
    accounts = [
        {"key": "demo-giro-anna", "name": "Girokonto Anna", "institution": "Demo Bank",
         "iban_last4": "0001", "owner": "Anna", "household": True, "owner_kind": "person_household",
         "card_owners": {}},
        {"key": "demo-giro-ben", "name": "Girokonto Ben", "institution": "Demo Bank",
         "iban_last4": "0002", "owner": "Ben", "household": False, "owner_kind": "person",
         "card_owners": {}},
        {"key": "demo-joint", "name": "Gemeinschaftskonto", "institution": "Demo Bank",
         "iban_last4": "0003", "owner": "shared", "household": False, "owner_kind": "household",
         "card_owners": {"1111": "Anna", "2222": "Ben"}},
    ]
    return {"persons": persons, "ha_users": users, "accounts": accounts, "plan_persons": ["Anna", "Ben"]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method: str) -> None:
        u = urlparse(self.path)
        if u.path.startswith("/api/finance_dashboard/"):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            try:
                out = api(method, u.path[len("/api/finance_dashboard/"):].strip("/"), parse_qs(u.query))
                self._send(200, json.dumps(out, default=str).encode(), "application/json")
            except Exception as err:  # noqa: BLE001 - a dev tool: show the cause in the page
                self._send(500, json.dumps({"error": repr(err)}).encode(), "application/json")
            return
        if u.path.startswith("/finance_dashboard_static/"):
            f = (FRONTEND / u.path[len("/finance_dashboard_static/"):]).resolve()
            if FRONTEND in f.parents and f.is_file():
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                if ctype.startswith("text") or "javascript" in ctype or ctype.endswith("json"):
                    ctype += "; charset=utf-8"
                self._send(200, f.read_bytes(), ctype)
                return
        if u.path in ("/", "/index.html"):
            page = Path(__file__).with_name("panel_harness.html").read_text(encoding="utf-8")
            self._send(200, page.encode(), "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain")

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def log_message(self, fmt, *args) -> None:  # quiet
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    port = ap.parse_args().port
    print(f"Finance harness on http://localhost:{port}/?el=fd-home")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
