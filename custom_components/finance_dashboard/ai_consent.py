"""Per-purpose AI consent.

Consent is not one global switch: each purpose that sends data to an AI
provider is granted on its own, and says what it sends (see the endpoint
``/setup/ai/consents``).

* ``categorize``     (recurring) merchant + remittance text of unclassified bank
                     transactions; the answer is the category and a shared/personal
                     tendency (version 2: the purpose widened, so a version-1 grant
                     no longer counts and is asked again once). Stays granted until
                     revoked.
* ``sheet_analysis`` (once) names of budget-sheet positions local matching could
                     not place. Consumed by the first analysis that uses it.
* ``history_import`` (once) rows of an uploaded booking-history file the local
                     parser could not read, incl. amounts and dates, IBANs
                     masked locally. Consumed by the import that uses it.
* ``contract_query`` (recurring) the question typed into the contracts search plus
                     the names of categories, labels and persons (never amounts,
                     IBANs, dates or bookings). Stays granted until revoked.

Stored in its own HA store. First load without a store migrates the legacy
setup-wizard flag ``ai_opt_in`` into ``categorize``. Nothing here makes a call.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_KEY = f"{DOMAIN}.ai_consent"
STORAGE_VERSION = 1

PURPOSES: dict[str, dict[str, str]] = {
    "categorize": {"mode": "recurring", "version": 2},
    "sheet_analysis": {"mode": "once"},
    "history_import": {"mode": "once"},
    "contract_query": {"mode": "recurring"},
}


def _version(purpose: str) -> int:
    return int(PURPOSES[purpose].get("version", 1))


def _store(hass: HomeAssistant) -> Store:
    data = hass.data.setdefault(DOMAIN, {})
    store = data.get("_ai_consent_store")
    if store is None:
        store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        data["_ai_consent_store"] = store
    return store


def _entry(raw: Any, purpose: str) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    seen = raw.get("version") if isinstance(raw.get("version"), int) else 1
    # A grant given for an older, narrower purpose is void until asked again.
    stale = raw.get("granted") is True and seen < _version(purpose)
    return {
        "granted": raw.get("granted") is True and not stale,
        "reconsent": stale,
        "version": _version(purpose) if not stale else seen,
        "mode": PURPOSES[purpose]["mode"],
        "granted_at": raw.get("granted_at") if isinstance(raw.get("granted_at"), str) else None,
        "used_at": raw.get("used_at") if isinstance(raw.get("used_at"), str) else None,
    }


def _check(purpose: str) -> None:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown AI purpose: {purpose}")


async def _legacy_opt_in(hass: HomeAssistant) -> bool:
    from .setup_wizard import async_load_state

    try:
        return bool((await async_load_state(hass)).get("ai_opt_in"))
    except Exception:  # noqa: BLE001 - a broken wizard file must not block consent
        return False


async def _save(hass: HomeAssistant, state: dict[str, dict[str, Any]]) -> None:
    await _store(hass).async_save(state)


async def async_load(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Every purpose with its state; migrates the legacy opt-in on first use."""
    try:
        raw = await _store(hass).async_load()
    except Exception:  # noqa: BLE001
        raw = None
    if not isinstance(raw, dict):
        out = {p: _entry(None, p) for p in PURPOSES}
        if await _legacy_opt_in(hass):
            out["categorize"]["granted"] = True
            out["categorize"]["granted_at"] = dt_util.utcnow().isoformat()
            out["categorize"]["version"] = _version("categorize")
        await _save(hass, out)
        return out
    return {p: _entry(raw.get(p), p) for p in PURPOSES}


async def async_granted(hass: HomeAssistant, purpose: str) -> bool:
    _check(purpose)
    return bool((await async_load(hass))[purpose]["granted"])


async def async_set(hass: HomeAssistant, purpose: str, granted: bool) -> dict[str, dict[str, Any]]:
    _check(purpose)
    state = await async_load(hass)
    entry = state[purpose]
    if bool(granted) != entry["granted"] or (granted and entry.get("reconsent")):
        entry["granted"] = bool(granted)
        entry["reconsent"] = False
        entry["version"] = _version(purpose)
        entry["granted_at"] = dt_util.utcnow().isoformat() if granted else None
        if granted:
            entry["used_at"] = None
        await _save(hass, state)
    return state


async def async_mark_used(hass: HomeAssistant, purpose: str) -> None:
    """Record a use; a ``once`` purpose is consumed (granted -> False)."""
    _check(purpose)
    state = await async_load(hass)
    entry = state[purpose]
    entry["used_at"] = dt_util.utcnow().isoformat()
    if entry["mode"] == "once":
        entry["granted"] = False
    await _save(hass, state)
