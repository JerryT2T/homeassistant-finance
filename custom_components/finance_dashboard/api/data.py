"""Data read endpoints for Finance.

Cache-read endpoints — never hit the banking API. Unbounded calls safe.

Provides:
- BalancesView        — per-account balance data (booked + available)
- BankStatusView      — per-bank consent / fetch budget / errors
- SettingsView        — panel options (show_household)
- TransactionsView    — admin: filtered + paged list; non-admin: aggregate summary
- SummaryView         — monthly spending summary
- TransferChainsView  — transfer chain detection + confirmation
"""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ..const import DOMAIN
from ..labels import booking_key
from ._helpers import _get_manager, visible_account_ids

_LOGGER = logging.getLogger(__name__)

_BOOKED_TYPES = ("CLBD", "CLOSINGBOOKED", "ITBD", "INTERIMBOOKED", "OPBD", "OPENINGBOOKED")
_AVAILABLE_TYPES = ("ITAV", "INTERIMAVAILABLE", "CLAV", "CLOSINGAVAILABLE", "XPCD", "FWAV")

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 500


def _pick_balance(balances: list, wanted: tuple[str, ...]) -> dict | None:
    """First balance whose type is in ``wanted`` (priority order), as a small dict."""
    by_type = {str(b.get("balanceType", "")).upper(): b for b in balances or []}
    for kind in wanted:
        bal = by_type.get(kind)
        if bal:
            amount = bal.get("balanceAmount") or {}
            return {
                "amount": amount.get("amount"),
                "currency": amount.get("currency", "EUR"),
                "type": bal.get("balanceType", ""),
            }
    return None


def _account_keys_by_uid(manager) -> dict[str, str]:
    """Map the (per-session) account uid to its stable IBAN-based key."""
    out: dict[str, str] = {}
    for acc in getattr(manager, "_accounts", None) or []:
        if isinstance(acc, dict) and acc.get("id") and acc.get("key"):
            out[str(acc["id"])] = str(acc["key"])
    return out


def _last_update(manager, key: str | None) -> str | None:
    """Timestamp of the newest stored balance point for an account."""
    if not key:
        return None
    try:
        series = manager.get_balance_history(key)
    except Exception:  # noqa: BLE001 - a history problem must not break the read
        return None
    stamps = [p.get("at") for p in series or [] if p.get("at")]
    return max(stamps) if stamps else None


def _is_admin(request: web.Request) -> bool:
    user = request.get("hass_user")
    return bool(user and user.is_admin)


class FinanceDashboardBalanceView(HomeAssistantView):
    """API endpoint for account balances (cache read)."""

    url = f"/api/{DOMAIN}/balances"
    name = f"api:{DOMAIN}:balances"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Get balances for all linked accounts."""
        hass = request.app["hass"]
        manager = _get_manager(hass)

        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        balances = await manager.async_get_balance()
        keys = _account_keys_by_uid(manager)
        visible = visible_account_ids(manager, request)  # non-admin: own + shared only

        sanitized = {}
        for account_id, data in balances.items():
            if visible is not None and str(account_id) not in visible:
                continue
            raw = data.get("balances", [])
            key = keys.get(str(account_id))
            sanitized[account_id] = {
                "account_key": key or "",
                "account_name": data.get("account_name", "Unknown"),
                "iban_masked": data.get("iban_masked", "****"),
                "institution": data.get("institution", ""),
                "logo": data.get("logo", ""),
                "balances": raw,
                "booked": _pick_balance(raw, _BOOKED_TYPES),
                "available": _pick_balance(raw, _AVAILABLE_TYPES),
                "last_update": _last_update(manager, key),
            }

        return self.json(sanitized)


class FinanceDashboardBankStatusView(HomeAssistantView):
    """Per-bank health: consent, fetch budget, block, last error.

    Cache read, readable by every authenticated user: it carries no secrets,
    no IBANs and no transactions - only the class-level state of each link.
    """

    url = f"/api/{DOMAIN}/bank_status"
    name = f"api:{DOMAIN}:bank_status"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"banks": [], "configured": False})

        banks = []
        for b in manager.get_bank_status():
            banks.append(
                {
                    "bank_id": b.get("bank_id", ""),
                    "title": b.get("title", ""),
                    "budget_used_today": b.get("budget_used_today", 0),
                    "budget_limit": b.get("budget_limit", 4),
                    "blocked_until": b.get("blocked_until"),
                    "last_success": b.get("last_success"),
                    "last_error": b.get("last_error"),
                    "last_attended_at": b.get("last_attended_at"),
                    "consent_valid_until": b.get("consent_valid_until"),
                    "consent_state": b.get("consent_state", "ok"),
                }
            )
        return self.json({"banks": banks, "configured": True})


class FinanceDashboardSettingsView(HomeAssistantView):
    """Panel-relevant integration options (no secrets)."""

    url = f"/api/{DOMAIN}/settings"
    name = f"api:{DOMAIN}:settings"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        entry = getattr(manager, "_entry", None) if manager else None
        options = dict(getattr(entry, "options", None) or {})
        return self.json(
            {
                # Default on: existing installs keep the household features.
                "show_household": bool(options.get("show_household", True)),
                "is_admin": _is_admin(request),
            }
        )


def _tx_matches(txn: dict, needle: str) -> bool:
    haystack = " ".join(
        str(txn.get(k) or "")
        for k in (
            "remittanceInformationUnstructured",
            "creditorName",
            "debtorName",
            "_account_name",
        )
    ).lower()
    return needle in haystack


def _int_param(request: web.Request, name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(request.query.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


async def _resolve_page(request: web.Request, manager, page: list[dict]) -> dict[str, dict]:
    """Contract link and labels for one page of bookings (#113); never fails the list."""
    from ..labels import async_get_label_store, resolve_bookings
    from .contracts import _contracts_for

    try:
        _store, contracts = await _contracts_for(request, manager)
        labels = await async_get_label_store(request.app["hass"])
        return resolve_bookings(page, contracts, labels.bookings)
    except Exception:  # noqa: BLE001 - labels are an addition, the list must still load
        _LOGGER.warning("Label resolution failed", exc_info=True)
        return {}


class FinanceDashboardTransactionsView(HomeAssistantView):
    """API endpoint for transactions (cache read).

    PRIVACY-FIRST: Individual transaction details are only returned
    to HA admin users. Non-admin users receive only aggregated
    category summaries - no individual transaction data.

    Admin query params (all optional, server-side): ``q`` free text,
    ``account`` account key, ``from`` / ``to`` booking date (YYYY-MM-DD,
    inclusive), ``limit`` (default 50, max 500), ``offset``.
    """

    url = f"/api/{DOMAIN}/transactions"
    name = f"api:{DOMAIN}:transactions"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Get transactions (admin-only detail view)."""
        hass = request.app["hass"]
        manager = _get_manager(hass)

        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        if not _is_admin(request):
            summary = await manager.async_get_monthly_summary()
            return self.json(
                {
                    "privacy": "aggregate_only",
                    "message": "Individual transactions require admin access.",
                    "categories": summary.get("categories", {}),
                    "total_income": summary.get("total_income", 0),
                    "total_expenses": summary.get("total_expenses", 0),
                    "transaction_count": summary.get("transaction_count", 0),
                }
            )

        q = (request.query.get("q") or "").strip().lower()
        account = (request.query.get("account") or "").strip()
        date_from = (request.query.get("from") or "").strip()
        date_to = (request.query.get("to") or "").strip()
        limit = _int_param(request, "limit", DEFAULT_PAGE_LIMIT, 1, MAX_PAGE_LIMIT)
        offset = _int_param(request, "offset", 0, 0, 10**9)

        rows = manager.get_cached_transactions(limit=10**9)
        filtered = []
        for txn in rows:
            if account and txn.get("_account_key") != account:
                continue
            day = str(txn.get("bookingDate") or txn.get("valueDate") or "")
            if date_from and day < date_from:
                continue
            if date_to and day > date_to:
                continue
            if q and not _tx_matches(txn, q):
                continue
            filtered.append(txn)
        filtered.sort(
            key=lambda t: str(t.get("bookingDate") or t.get("valueDate") or ""), reverse=True
        )

        page = filtered[offset : offset + limit]
        resolved = await _resolve_page(request, manager, page)
        sanitized = []
        for txn in page:
            entry = {
                "date": txn.get("bookingDate") or txn.get("valueDate") or "",
                "amount": txn.get("transactionAmount", {}).get("amount", "0"),
                "currency": txn.get("transactionAmount", {}).get("currency", "EUR"),
                "description": txn.get("remittanceInformationUnstructured", ""),
                "creditor": txn.get("creditorName", ""),
                "debtor": txn.get("debtorName", ""),
                "category": txn.get("category", "other"),
                "status": txn.get("_status", "booked"),
                "account_name": txn.get("_account_name", ""),
                "account_key": txn.get("_account_key", ""),
            }
            # Contract link, inherited category and labels (#113)
            key = booking_key(txn) or ""
            info = resolved.get(key)
            if info:
                entry["ledger_id"] = key
                entry["own_category"] = entry["category"]
                entry.update(info)

            # Transfer chain metadata
            chain_id = txn.get("_transfer_chain_id")
            if chain_id:
                entry["transfer_chain_id"] = chain_id
                entry["transfer_role"] = txn.get("_transfer_role", "")
                entry["transfer_confidence"] = txn.get("_transfer_confidence")
                entry["transfer_confirmed"] = txn.get("_transfer_confirmed")

            # Refund metadata
            refund_id = txn.get("_refund_pair_id")
            if refund_id:
                entry["refund_pair_id"] = refund_id
                entry["refund_role"] = txn.get("_refund_role", "")

            sanitized.append(entry)

        return self.json(
            {
                "privacy": "admin_full",
                "transactions": sanitized,
                "total": len(filtered),
                "limit": limit,
                "offset": offset,
            }
        )


class FinanceDashboardTransferChainsView(HomeAssistantView):
    """API endpoint for transfer chain data.

    Returns detected cascading transfer chains for the frontend.
    Supports confirming/rejecting chains via POST.
    """

    url = f"/api/{DOMAIN}/transfer_chains"
    name = f"api:{DOMAIN}:transfer_chains"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Get all detected transfer chains."""
        hass = request.app["hass"]
        manager = _get_manager(hass)

        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        if not _is_admin(request):
            return self.json(
                {"error": "Admin access required"},
                status_code=403,
            )

        chains = manager.get_transfer_chains()
        return self.json({"chains": chains})

    async def post(self, request: web.Request) -> web.Response:
        """Confirm or reject a transfer chain."""
        hass = request.app["hass"]
        manager = _get_manager(hass)

        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        if not _is_admin(request):
            return self.json(
                {"error": "Admin access required"},
                status_code=403,
            )

        try:
            body = await request.json()
        except Exception:
            return self.json({"error": "Invalid JSON body"}, status_code=400)

        chain_id = body.get("chain_id", "")
        confirmed = body.get("confirmed")

        if not chain_id or confirmed is None:
            return self.json(
                {"error": "chain_id and confirmed required"},
                status_code=400,
            )

        await manager.async_confirm_transfer_chain(chain_id, bool(confirmed))
        return self.json({"success": True, "chain_id": chain_id})


class FinanceDashboardSummaryView(HomeAssistantView):
    """API endpoint for monthly summary."""

    url = f"/api/{DOMAIN}/summary"
    name = f"api:{DOMAIN}:summary"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Get monthly spending summary."""
        hass = request.app["hass"]
        manager = _get_manager(hass)

        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        summary = await manager.async_get_monthly_summary()
        return self.json(summary)
