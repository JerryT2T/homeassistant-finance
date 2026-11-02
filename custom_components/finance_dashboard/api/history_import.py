"""Booking-history import endpoints (admin only, no bank call).

View classes (registered via ``VIEWS``):

* ``FinanceDashboardHistoryImportView``         ``GET  /api/finance_dashboard/history_import``
* ``FinanceDashboardHistoryImportPreviewView``  ``POST /api/finance_dashboard/history_import/preview``
* ``FinanceDashboardHistoryImportCommitView``   ``POST /api/finance_dashboard/history_import/commit``
* ``FinanceDashboardHistoryImportUndoView``     ``POST /api/finance_dashboard/history_import/undo``

The preview parses the upload locally (CSV / XLSX). Only when the user asks
for it (``use_ai: true``) and the one-time ``history_import`` consent is
granted does the masked file content go to the AI. The validated rows wait
in memory (never persisted) until the commit names the preview id; the commit
stores them as one tagged batch that the undo removes as a whole.
"""

from __future__ import annotations

import base64
import binascii
import logging
import secrets
import time

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.util import dt as dt_util

from .. import ai_consent, ai_provider
from .. import history_import as hi
from ..const import DOMAIN
from ._helpers import _get_manager, admin_denied

_LOGGER = logging.getLogger(__name__)

PREVIEW_TTL_SECONDS = 30 * 60
MAX_PREVIEWS = 3
PREVIEW_ROWS_SHOWN = 1500
INVALID_SHOWN = 200
_STORE_KEY = "_history_import_previews"


def _previews(hass) -> dict[str, dict]:
    store = hass.data.setdefault(DOMAIN, {}).setdefault(_STORE_KEY, {})
    now = time.monotonic()
    for pid in [p for p, v in store.items() if now - v["at"] > PREVIEW_TTL_SECONDS]:
        store.pop(pid, None)
    return store


def _decode(content_base64: str) -> bytes:
    raw = (content_base64 or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    if len(raw) > hi.MAX_FILE_BYTES * 4 // 3 + 4:
        raise hi.ImportFileError("too_large", "The file is larger than 5 MB")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as err:
        raise hi.ImportFileError("unreadable", "The upload could not be read") from err


async def _ai_status(hass, manager) -> dict:
    cfg = await ai_provider.async_load_config(hass)
    creds = getattr(manager, "_credential_manager", None)
    services = hass.services
    usable = ai_provider.provider_usable(
        cfg,
        has_key=bool(ai_provider.read_key(cfg, creds)),
        has_ai_task=services.has_service("ai_task", "generate_data"),
        has_conversation=services.has_service("conversation", "process"),
    )
    usage = ai_provider.usage_view(cfg, dt_util.now().date())
    consent = await ai_consent.async_granted(hass, "history_import")
    return {"usable": usable, "consented": consent, "remaining": usage["remaining"]}


async def _refresh_coordinator(hass) -> None:
    domain_data = hass.data.get(DOMAIN, {})
    entry = domain_data.get("entry")
    coordinator = domain_data.get(f"{entry.entry_id}_coordinator") if entry else None
    if coordinator:
        try:
            await coordinator.async_refresh()
        except Exception:
            _LOGGER.exception("Coordinator refresh after history import failed")


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class FinanceDashboardHistoryImportView(HomeAssistantView):
    """Accounts to import into, imported batches, AI readiness."""

    url = f"/api/{DOMAIN}/history_import"
    name = f"api:{DOMAIN}:history_import"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        return self.json(
            {
                "allowed": manager.history_import_allowed(),
                "accounts": manager.history_accounts(),
                "batches": manager.history_batches(),
                "ai": await _ai_status(hass, manager),
            }
        )


class FinanceDashboardHistoryImportPreviewView(HomeAssistantView):
    """Parse an upload and show what would be imported; saves nothing."""

    url = f"/api/{DOMAIN}/history_import/preview"
    name = f"api:{DOMAIN}:history_import_preview"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Body ``{"content_base64", "account_key", "use_ai"?: bool}``."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        if not manager.history_import_allowed():
            return self.json({"error": "import_unavailable"}, status_code=409)
        body = await _json_body(request)
        key = str(body.get("account_key") or "")
        if key not in {a["key"] for a in manager.history_accounts()}:
            return self.json({"error": "unknown_account"}, status_code=400)
        try:
            table = hi.read_table(_decode(str(body.get("content_base64") or "")))
            candidates, mapping = hi.rows_from_table(table)
            method = "local"
            if mapping is None:
                chunks = hi.ai_chunks(table)
                ai = await _ai_status(hass, manager)
                if body.get("use_ai") is not True:
                    return self.json(
                        {"needs_ai": True, "calls": len(chunks), "ai": ai, "preview_id": None}
                    )
                blocked = self._blocked(ai, len(chunks))
                if blocked:
                    return self.json({"error": blocked}, status_code=400)
                candidates, error = await self._ask_ai(hass, manager, ai, chunks)
                if error:
                    return self.json({"error": error}, status_code=502)
                method = "ai"
        except hi.ImportFileError as err:
            return self.json({"error": err.code, "detail": str(err)}, status_code=400)

        valid, invalid = hi.validate_rows(candidates, today=dt_util.now().date())
        rows, summary = hi.classify_rows(valid, manager.history_ledger_transactions(key))
        store = _previews(hass)
        while len(store) >= MAX_PREVIEWS:
            store.pop(min(store, key=lambda p: store[p]["at"]))
        pid = secrets.token_urlsafe(12)
        store[pid] = {"at": time.monotonic(), "key": key, "rows": rows, "method": method}
        return self.json(
            {
                "preview_id": pid,
                "needs_ai": False,
                "method": method,
                "summary": {**summary, "invalid": len(invalid), "total": len(candidates)},
                "rows": rows[:PREVIEW_ROWS_SHOWN],
                "rows_truncated": len(rows) > PREVIEW_ROWS_SHOWN,
                "invalid": invalid[:INVALID_SHOWN],
            }
        )

    @staticmethod
    def _blocked(ai: dict, calls: int) -> str | None:
        if not ai["consented"]:
            return "consent_required"
        if not ai["usable"]:
            return "no_provider"
        if ai["remaining"] < calls:
            return "budget_exhausted"
        return None

    @staticmethod
    async def _ask_ai(hass, manager, ai: dict, chunks: list[str]):
        answers, error = await ai_provider.async_extract_history(
            hass,
            credentials=getattr(manager, "_credential_manager", None),
            prompts=[hi.build_import_prompt(c) for c in chunks],
            max_tokens=hi.AI_MAX_TOKENS,
            today=dt_util.now().date(),
            usable=ai["usable"],
        )
        if error:
            return [], error
        await ai_consent.async_mark_used(hass, "history_import")  # once: consumed
        rows: list = []
        for answer in answers or []:
            parsed = hi.parse_ai_answer(answer)
            if parsed is None:
                return [], "unparsable"
            rows.extend(parsed)
        # a sequential line number per AI row so the preview can point at it
        for n, row in enumerate(rows, start=1):
            if isinstance(row, dict):
                row["line"] = n
        return rows, None


class FinanceDashboardHistoryImportCommitView(HomeAssistantView):
    """Store a previewed import as one batch."""

    url = f"/api/{DOMAIN}/history_import/commit"
    name = f"api:{DOMAIN}:history_import_commit"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Body ``{"preview_id"}``. Only rows classified ``new`` are stored."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        if not manager.history_import_allowed():
            return self.json({"error": "import_unavailable"}, status_code=409)
        body = await _json_body(request)
        preview = _previews(hass).pop(str(body.get("preview_id") or ""), None)
        if preview is None:
            return self.json({"error": "preview_expired"}, status_code=404)
        rows = [r for r in preview["rows"] if r["status"] == "new"]
        if not rows:
            return self.json({"error": "nothing_to_import"}, status_code=400)
        batch_id = secrets.token_hex(6)
        info = {
            "at": dt_util.utcnow().isoformat(),
            "method": preview["method"],
            **hi.batch_summary(rows),
        }
        added = await manager.async_commit_history_import(
            preview["key"], batch_id, hi.to_ledger_transactions(rows, batch_id), info
        )
        await _refresh_coordinator(hass)
        return self.json({"ok": True, "batch_id": batch_id, "added": added})


class FinanceDashboardHistoryImportUndoView(HomeAssistantView):
    """Remove an imported batch as a whole."""

    url = f"/api/{DOMAIN}/history_import/undo"
    name = f"api:{DOMAIN}:history_import_undo"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Body ``{"batch_id"}``."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _json_body(request)
        batch_id = str(body.get("batch_id") or "")
        if batch_id not in {b.get("id") for b in manager.history_batches()}:
            return self.json({"error": "unknown_batch"}, status_code=404)
        removed = await manager.async_undo_history_import(batch_id)
        await _refresh_coordinator(hass)
        return self.json({"ok": True, "removed": removed})


VIEWS = [
    FinanceDashboardHistoryImportView,
    FinanceDashboardHistoryImportPreviewView,
    FinanceDashboardHistoryImportCommitView,
    FinanceDashboardHistoryImportUndoView,
]
