"""Rebuild the processed ledger from the raw archive.

The raw archive keeps every bank response unaltered.  When the processing
(normalisation, ingest, transaction identity) changes, ``PROCESSING_VERSION``
is bumped and the ledger is replayed from it — no bank call, so this works
while the bank's rate limit is exhausted.

Replay runs archived pages through the same code a live fetch uses
(:meth:`EnableBankingClient.parse_transaction_page`, :meth:`Ledger.ingest`).
History the archive does not cover (a legacy import, months archived before
lifelong retention) is carried over from the previous ledger, so a rebuild
never shortens the history.
"""

from __future__ import annotations

from typing import Any

from .data_store import Ledger, reported_from
from .enablebanking_client import EnableBankingClient
from .tx_dates import effective_date_str

WINDOW_KIND = "transactions_window"


def _key_for(snap: dict[str, Any], uid_to_key: dict[str, str]) -> str | None:
    meta = snap.get("meta") or {}
    return meta.get("account_key") or uid_to_key.get(str(snap.get("account") or ""))


def replay(  # noqa: PLR0912, PLR0915
    snapshots: list[dict[str, Any]], uid_to_key: dict[str, str]
) -> tuple[dict[str, Any], dict[str, str], dict[str, int]]:
    """Replay archived snapshots (oldest first) into fresh ledger accounts.

    Returns ``(accounts, coverage, stats)``: ``coverage`` maps an account key
    to the earliest date the archive is evidence for.

    * Snapshots with a ``fetch_id`` are grouped into one fetch window; the
      closing ``transactions_window`` snapshot supplies ``truncated``.  A
      window that never closed (crash mid-fetch) counts as truncated.
    * Legacy snapshots (no meta) map their uid through ``uid_to_key`` and are
      merged page by page as truncated — absence proves nothing.
    * Snapshots whose account cannot be resolved are skipped and counted.
    """
    ledger = Ledger(None)
    coverage: dict[str, str] = {}
    stats = {"snapshots": len(snapshots), "windows": 0, "balances": 0, "skipped": 0}

    windows: dict[str, dict[str, Any]] = {}
    events: list[tuple[str, int, str, Any]] = []  # (at, seq, kind, payload)

    for seq, snap in enumerate(snapshots):
        kind = snap.get("kind")
        if snap.get("http_status", 200) != 200 and kind != WINDOW_KIND:
            continue
        key = _key_for(snap, uid_to_key)
        if not key:
            stats["skipped"] += 1
            continue
        at = str(snap.get("fetched_at") or "")
        meta = snap.get("meta") or {}
        fetch_id = meta.get("fetch_id")

        if kind == "transactions":
            if fetch_id:
                win = windows.get(fetch_id)
                if win is None:
                    win = windows[fetch_id] = {
                        "key": key,
                        "date_from": meta.get("date_from"),
                        "pages": [],
                        "truncated": True,
                    }
                    events.append((at, seq, "window", fetch_id))
                win["pages"].append(snap.get("response"))
            else:
                events.append(
                    (at, seq, "window_inline", {"key": key, "pages": [snap.get("response")]})
                )
        elif kind == WINDOW_KIND and fetch_id:
            win = windows.get(fetch_id)
            if win is not None:
                resp = snap.get("response") or {}
                win["truncated"] = bool(resp.get("truncated"))
                win["date_from"] = resp.get("date_from") or win["date_from"]
        elif kind == "balances":
            events.append((at, seq, "balances", {"key": key, "response": snap.get("response")}))

    events.sort(key=lambda e: (e[0], e[1]))
    for at, _seq, kind, payload in events:
        if kind == "balances":
            ledger.add_balances(
                payload["key"], EnableBankingClient.parse_balances(payload["response"]), at
            )
            stats["balances"] += 1
            continue
        if kind == "window":
            win = windows[payload]
            key, date_from, truncated = win["key"], win["date_from"], win["truncated"]
        else:
            key, date_from, truncated = payload["key"], None, True
            win = payload
        booked: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        for page in win["pages"]:
            b, p, _ = EnableBankingClient.parse_transaction_page(page)
            booked.extend(b)
            pending.extend(p)
        ledger.ingest(key, booked, pending, date_from=date_from, truncated=truncated)
        stats["windows"] += 1
        start = reported_from(date_from, booked)
        if start and (key not in coverage or start < coverage[key]):
            coverage[key] = start

    return ledger.data["accounts"], coverage, stats


def merge_uncovered(
    old_accounts: dict[str, Any],
    new_accounts: dict[str, Any],
    coverage: dict[str, str],
) -> int:
    """Carry history the archive does not cover from the old ledger.

    Per account: booked transactions dated before the archive's coverage,
    and balance points older than the first archived balance.  An account
    the archive does not know at all is kept whole.  Returns the number of
    transactions carried over.
    """
    carried = 0
    for key, old in old_accounts.items():
        old_txs = list(old.get("transactions") or [])
        old_bal = list(old.get("balances") or [])
        if key not in new_accounts:
            new_accounts[key] = {"transactions": old_txs, "balances": old_bal}
            carried += len(old_txs)
            continue
        new = new_accounts[key]
        start = coverage.get(key)
        ids = {t.get("_ledger_id") for t in new["transactions"]}
        for tx in old_txs:
            if tx.get("_status") != "booked" or tx.get("_ledger_id") in ids:
                continue
            bdate = effective_date_str(tx)
            # imported history (#121) is never rebuilt from the archive: always carried
            if tx.get("_source") or start is None or (bdate and bdate < start):
                new["transactions"].append(tx)
                carried += 1
        new["transactions"].sort(key=effective_date_str, reverse=True)

        first_at = min((p.get("at", "") for p in new["balances"]), default=None)
        older = [p for p in old_bal if first_at is None or p.get("at", "") < first_at]
        if older:
            new["balances"] = sorted(older + new["balances"], key=lambda p: p.get("at", ""))
    return carried
