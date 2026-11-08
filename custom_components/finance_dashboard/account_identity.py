"""Stable account identity across bank re-links.

Enable Banking issues a fresh account uid for every PSU session.  Treating
that uid as the account's identity meant a re-link of the same bank created
a second set of entities for the same real account, and left the previous
ones orphaned in the registry.

The identity of a payment account is its **IBAN**.  This module derives a
stable, non-identifying key from it and merges account records around that
key, so re-linking a bank updates the existing accounts instead of adding
copies.

The key is a truncated SHA-256 digest rather than the IBAN itself: it lands
in HA's entity registry and in entity settings UI, and the security model
forbids putting account numbers anywhere they are not strictly needed.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Fields the user owns. The bank has no say in them, so a re-link must not
# reset them — unless the wizard explicitly sent a new value.
_USER_OWNED_FIELDS = ("custom_name", "type", "person", "ha_users", "household_use")

_NON_IBAN_CHARS = re.compile(r"[^A-Z0-9]")


def normalize_iban(iban: str | None) -> str:
    """Return an IBAN stripped of formatting, upper-cased.

    Banks and users write the same IBAN with spaces, dashes or lower case.
    Comparing raw strings would treat those as different accounts.
    """
    if not iban:
        return ""
    return _NON_IBAN_CHARS.sub("", str(iban).upper())


def _fallback_material(account: dict[str, Any], institution: str) -> str:
    """Deterministic identity for accounts WITHOUT an IBAN (e.g. a DKB Visa).

    Never the session uid — that changes on every re-link, which is exactly
    the duplicate-entity bug this module exists to prevent.  Preference:

    1. ``account_id.other.identification`` (``identification``) or a masked
       PAN (``masked_pan`` / ``pan``) — what the bank itself calls the account;
    2. otherwise name + currency + account type, which is stable per product
       within a bank (two identical unnamed cards would collide, which is
       the lesser evil compared to duplicating on every re-link).
    """
    ident = _NON_IBAN_CHARS.sub(
        "",
        str(
            account.get("identification")
            or account.get("masked_pan")
            or account.get("pan")
            or ""
        ).upper(),
    )
    if ident:
        return f"acct|{institution}|{ident}"
    name = " ".join(str(account.get("name") or "").lower().split())
    currency = str(account.get("currency") or "").upper()
    kind = str(account.get("account_type") or account.get("product") or "").upper()
    if name or currency or kind:
        return f"prod|{institution}|{name}|{currency}|{kind}"
    # Nothing stable known at all — last resort so the record still gets a key.
    return f"uid|{institution}|{account.get('id', '')}"


def identity_key(account: dict[str, Any]) -> str:
    """Return the key derived purely from what identifies the account.

    Ignores any stored ``key``.  This is what makes two records recognisable
    as the same real account across sessions:

    * ``institution_id`` + normalized IBAN — the real identity.
    * Without an IBAN (card accounts): a deterministic fallback from the
      bank-given identification / masked PAN, or name + currency + type
      (see :func:`_fallback_material`).  Never the per-session uid, except as
      the last resort when the bank supplies nothing else.
    """
    institution = str(account.get("institution_id") or account.get("institution") or "")
    iban = normalize_iban(account.get("iban"))
    if iban:
        material = f"iban|{institution}|{iban}"
    else:
        material = _fallback_material(account, institution)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def account_key(account: dict[str, Any]) -> str:
    """Return the entity-facing key for an account record.

    A stored ``key`` is authoritative once assigned, so entity identity
    survives even if the bank later reformats the IBAN or the derivation
    changes.  Otherwise the derived identity is used.
    """
    stored = account.get("key")
    if stored:
        return str(stored)
    return identity_key(account)


def dedupe_accounts(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge a freshly linked bank's accounts into the stored set.

    Semantics:

    * Accounts of banks other than the incoming one are kept untouched.
    * An incoming account replaces the stored record with the same key —
      the fresh session uid wins, user-owned fields are carried over.
    * Stored accounts of the incoming bank that are absent from the payload
      are dropped: the bank no longer reports them (closed account).
    * Duplicates inside the incoming payload itself collapse to one.

    Args:
        existing: Accounts already stored in the config entry.
        incoming: Accounts just linked, all belonging to one institution.

    Returns:
        The merged account list. Every record carries a ``key``.
    """
    if not incoming:
        return [dict(acc, key=account_key(acc)) for acc in existing]

    incoming_institutions = {
        str(acc.get("institution_id") or acc.get("institution") or "") for acc in incoming
    }

    # Stored accounts are looked up by their derived identity, not by their
    # stored key: an incoming payload has no key yet, and a record whose key
    # was assigned earlier (or migrated from a legacy id) must still be
    # recognised as the same account.
    stored_by_identity: dict[str, dict[str, Any]] = {}
    untouched: list[dict[str, Any]] = []
    for acc in existing:
        institution = str(acc.get("institution_id") or acc.get("institution") or "")
        record = dict(acc)
        record["key"] = account_key(acc)
        if institution in incoming_institutions:
            stored_by_identity[identity_key(acc)] = record
        else:
            untouched.append(record)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for acc in incoming:
        record = dict(acc)
        identity = identity_key(record)
        if identity in seen:
            # Same real account listed twice by the API — keep the first.
            continue
        seen.add(identity)

        previous = stored_by_identity.get(identity)
        if previous is not None:
            # Carry over the stored key so an assigned identity is never
            # rewritten, then restore user-owned fields the payload omits.
            record["key"] = previous["key"]
            for field in _USER_OWNED_FIELDS:
                if not record.get(field) and previous.get(field):
                    record[field] = previous[field]
        else:
            record["key"] = account_key(record)
        merged.append(record)

    return untouched + merged


# ---------------------------------------------------------------------------
# Entity registry reconciliation
# ---------------------------------------------------------------------------

BALANCE_UNIQUE_ID_SUFFIX = "_balance"


def balance_unique_id(domain: str, account: dict[str, Any]) -> str:
    """Return the balance sensor's unique_id for an account."""
    return f"{domain}_{account_key(account)}{BALANCE_UNIQUE_ID_SUFFIX}"


def _legacy_balance_unique_id(domain: str, account: dict[str, Any]) -> str:
    """Return the pre-key unique_id, derived from the session uid."""
    return f"{domain}_{account.get('id', '')}{BALANCE_UNIQUE_ID_SUFFIX}"


async def async_reconcile_account_entities(hass, entry, domain: str) -> dict[str, int]:
    """Align the entity registry with the accounts currently linked.

    Two jobs, both consequences of the uid-as-identity mistake:

    * **Migrate** — an account whose entity still carries the old
      uid-derived unique_id is rewritten to its stable key, so the user
      keeps the same entity_id, history and dashboard cards.
    * **Remove** — balance entities that belong to no linked account are
      leftovers from earlier re-links.  They can never receive data again;
      leaving them means the duplicate entities the user complained about
      stay in every entity picker forever.

    Removal is skipped entirely when the entry lists no accounts: that state
    means "unknown", not "all orphaned", and deleting there would destroy
    history HA cannot restore.

    Removal is skipped entirely when the entry lists no accounts: that state
    means "unknown", not "all orphaned", and deleting there would destroy
    history HA cannot restore.

    Returns:
        ``{"migrated": n, "removed": n}`` — for logging and tests.
    """
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    accounts = entry.data.get("accounts", [])

    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    by_unique_id = {e.unique_id: e for e in entries}

    # An empty account list means "we do not know what is linked", not "every
    # entity is an orphan".  It happens legitimately — a half-configured
    # setup, a storage-recovery round, a re-auth that cleared the list before
    # failing — and removing entities there would destroy history that HA
    # cannot restore.  Nothing to migrate onto either, so return early.
    if not accounts:
        _LOGGER.debug("No linked accounts — skipping entity reconciliation")
        return {"migrated": 0, "removed": 0}

    # An empty account list means "we do not know what is linked", not "every
    # entity is an orphan".  It happens legitimately — a half-configured
    # setup, a storage-recovery round, a re-auth that cleared the list before
    # failing — and removing entities there would destroy history that HA
    # cannot restore.  Nothing to migrate onto either, so return early.
    if not accounts:
        _LOGGER.debug("No linked accounts — skipping entity reconciliation")
        return {"migrated": 0, "removed": 0}

    wanted: set[str] = set()
    migrated = 0

    for account in accounts:
        target = balance_unique_id(domain, account)
        wanted.add(target)

        if target in by_unique_id:
            continue
        legacy = _legacy_balance_unique_id(domain, account)
        stale = by_unique_id.get(legacy)
        if stale is None:
            continue
        registry.async_update_entity(stale.entity_id, new_unique_id=target)
        # Re-index under the new id AND drop the legacy one: leaving it in
        # place makes the cleanup pass below delete the entity we just
        # migrated, because the legacy id is not in `wanted`.
        by_unique_id.pop(legacy, None)
        by_unique_id[target] = stale
        migrated += 1
        _LOGGER.info(
            "Migrated %s to a stable account identity — history preserved",
            stale.entity_id,
        )

    # Entities carried through migration are live accounts — never remove
    # them, whatever else still points at their old id.
    protected = {e.entity_id for uid, e in by_unique_id.items() if uid in wanted}

    removed = 0
    for unique_id, registry_entry in list(by_unique_id.items()):
        if not unique_id.endswith(BALANCE_UNIQUE_ID_SUFFIX):
            continue
        if unique_id in wanted or registry_entry.entity_id in protected:
            continue
        registry.async_remove(registry_entry.entity_id)
        removed += 1
        _LOGGER.info(
            "Removed %s — no linked account owns it any more (duplicate from an "
            "earlier bank re-link)",
            registry_entry.entity_id,
        )

    return {"migrated": migrated, "removed": removed}
