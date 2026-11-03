"""Whose account is on the other side of a booking?

A payment to an account holder's own name or to an IBAN of a linked account is
money moved, not money spent (#171). Only the side that names the counterparty
decides: the creditor of a debit, the debtor of a credit. Banks fill the other
side with the holder's own name, which says nothing.

Pure functions; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .text_norm import is_processor_only


def is_own_name(creditor: str, own_names: set[str] | frozenset[str]) -> bool:
    """Every word of an own name appears in the creditor ("Jeremy Tim Treder")."""
    words = set(creditor.replace(",", " ").split())
    return any(name and set(name.split()) <= words for name in own_names)


def own_account_names(accounts: list[dict[str, Any]]) -> frozenset[str]:
    """Normalised account holder names ("Jeremy Treder und X" -> both parts)."""
    names: set[str] = set()
    for acc in accounts or []:
        raw = " ".join(str(acc.get("name") or acc.get("account_name") or "").lower().split())
        institution = " ".join(str(acc.get("institution") or "").lower().split())
        for part in raw.replace(" und ", ",").replace(" & ", ",").split(","):
            part = part.strip()
            # a full name, never a bare bank or product word
            if len(part.split()) >= 2 and part not in institution:
                names.add(part)
    return frozenset(names)


def normalize_iban(value: Any) -> str:
    return "".join(str(value or "").split()).upper()


def own_ibans(accounts: list[dict[str, Any]]) -> frozenset[str]:
    return frozenset(iban for a in accounts or [] if (iban := normalize_iban(a.get("iban"))))


@dataclass(frozen=True)
class OwnAccounts:
    """The household's holder names and linked IBANs."""

    names: frozenset[str] = frozenset()
    ibans: frozenset[str] = frozenset()

    @classmethod
    def of(cls, accounts: list[dict[str, Any]]) -> OwnAccounts:
        return cls(own_account_names(accounts), own_ibans(accounts))

    def matches(self, tx: dict[str, Any]) -> bool:
        """The counterparty of ``tx`` is an account of the household."""
        try:
            amount = float((tx.get("transactionAmount") or {}).get("amount", 0) or 0)
        except (TypeError, ValueError):
            return False
        if amount == 0:
            return False
        name_key, account_key = (
            ("creditorName", "creditorAccount") if amount < 0 else ("debtorName", "debtorAccount")
        )
        iban = normalize_iban((tx.get(account_key) or {}).get("iban"))
        if iban and iban in self.ibans:
            return True
        name = " ".join(str(tx.get(name_key) or "").lower().split())
        # A processor carries the merchant in its text; PayPal is settled by the mirror.
        return bool(name) and not is_processor_only(name) and is_own_name(name, self.names)
