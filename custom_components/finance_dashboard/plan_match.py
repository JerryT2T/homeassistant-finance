"""Which plan position a booking belongs to, and who owns it.

Ownership resolves in the fixed chain from CLAUDE.md: the account's owner is the
default, a matched plan position overrides it, a user correction overrides both.
Every view resolves it here (#175); the chain itself, with the source and
confidence of each answer, lives in ``ownership.resolve_owner_detail``.

Matching: the distinctive words (4+ letters) of a position name against the
booking's text. A booking matches at most one position, the most specific one:
more of the name's words found, then the longer words. A person's name or a
generic word in the position name is no evidence, so "Handy Anna" does not claim
every debit Anna is named on. Pure functions; no I/O.
"""

from __future__ import annotations

import re
from typing import Any

from .ownership import resolve_owner_detail

_TOKEN_RE = re.compile(r"[a-zäöüß]{4,}")
_GENERIC = frozenset({
    "kosten", "konto", "beitrag", "gebühr", "gebühren", "rate", "raten", "sonstiges",
    "sparen", "rücklage", "rücklagen", "gemeinsam", "haushalt", "person", "monat", "jahr",
    "euro", "zahlung", "abschlag",
})


def _haystack(tx: dict[str, Any]) -> str:
    return " ".join(
        str(tx.get(k) or "").lower()
        for k in ("remittanceInformationUnstructured", "creditorName", "debtorName")
    )


def position_tokens(name: str, persons: list[str] | None = None) -> list[str]:
    """Words of a position name that can identify a booking."""
    people = {w for p in persons or [] for w in _TOKEN_RE.findall(str(p).lower())}
    words = [w for w in _TOKEN_RE.findall(name.lower()) if w not in people]
    # A name of generic words only ("Abschlag") has nothing better to go by.
    return [w for w in words if w not in _GENERIC] or words


def best_position(
    tx: dict[str, Any], positions: list[Any], persons: list[str] | None = None
) -> Any | None:
    """The single position ``tx`` belongs to, or None. Ties go to the first."""
    hay = _haystack(tx)
    best, best_score = None, (0, 0)
    for pos in positions:
        hits = [t for t in position_tokens(pos.name, persons) if t in hay]
        score = (len(hits), sum(len(t) for t in hits))
        if score > best_score:
            best, best_score = pos, score
    return best


def assign_positions(
    transactions: list[dict[str, Any]], positions: list[Any], persons: list[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Position id -> its bookings; each booking lands in at most one position."""
    out: dict[str, list[dict[str, Any]]] = {}
    for tx in transactions:
        pos = best_position(tx, positions, persons)
        if pos is not None:
            out.setdefault(pos.id, []).append(tx)
    return out


def resolve_owner(tx: dict[str, Any], position: Any | None, correction: str | None = None) -> str:
    """Owner of an expense (the one chain, see ``ownership``): a person, shared or open."""
    return resolve_owner_detail(tx, position, correction)[0]
