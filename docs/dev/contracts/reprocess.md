# Contract: reprocess, freshness, import log

Buttons: "Neu importieren" = existing `POST /api/finance_dashboard/refresh` (live bank fetch + reprocessing, unchanged).
"Aktualisieren" = `POST /api/finance_dashboard/reprocess` (stored raw data only, never a bank call, never the fetch budget).

## POST /api/finance_dashboard/reprocess  (admin only)

No body. Replays the raw archive into a fresh ledger (forced), re-derives categories/transfers/recurring, pushes the coordinator. Serialised with live refreshes (waits for one in flight).

- 403 `{ok:false, error:"admin_required"}` for non-admins; 404 `{error:"Not configured"}`.
- 200 `{ok: bool, stats: {...}}`
  - `stats.outcome`: `rebuilt` | `empty` (archive has no snapshots) | `unavailable` (no archive / ledger read-only) | `error` (`reason:"raw_unreadable"`; old ledger kept)
  - `stats.version`: processing version, `stats.transactions`: transactions in the rebuilt ledger, `stats.transaction_count`: derived list size, plus `snapshots`, `windows`, `balances`, `skipped`, `carried` (counts).
  - `ok` is true for `rebuilt` / `empty`.
- 200 `{ok:false, reason:"error", message}` on an unexpected failure.

## GET /api/finance_dashboard/freshness  (cache read; auth required)

Non-admin: `{as_of, last_import}`.

Admin:
```json
{
  "as_of": "ISO ts of last successful bank refresh (now if none)",
  "last_import": "ISO ts | null  (newest non-failed import_* log entry)",
  "last_reprocess": "ISO ts | null (newest non-failed reprocess / processing_upgrade)",
  "processing_version": 2,
  "log": [ {"at","kind","banks":["DKB"],"new","total","processing_version","outcome","duration_ms"} ],
  "validity": [ {"month":"2026-02","account_name":"Giro","status":"ok|gap|unknown","diff":0.0} ],
  "derivation": {"ok": true, "diff": 0.0, "ledger_count": 650, "derived_count": 650},
  "data_quality": [{"account_name": "PayPal", "undated": 12, "total": 40}]
}
```
- `log`: newest first, at most 100 entries, persisted in the encrypted ledger meta. `kind`: `import_attended` | `import_scheduled` | `reprocess` | `processing_upgrade` (automatic rebuild at startup after a version bump). `banks`: titles of banks that answered (imports only). `new`: new transactions (imports); `total`: transactions after the run. `outcome`: `ok`, `partial`, `rate_limited`, `error` (imports) or `rebuilt`, `empty`, `unavailable`, `error` (reprocess). Debounced clicks and "current" no-op upgrade checks are not logged. No amounts, IBANs, counterparties.
- `validity`: per account and calendar month, newest first. For a month, first and last booked-balance snapshot inside it define a window; `diff` = (balance change) - (sum of bookings dated after the first snapshot day up to and including the last snapshot day), in EUR. `ok` when |diff| < 0.005, else `gap`; `unknown` (diff `null`) when fewer than two snapshots on different days fall in the month. Same-day bookings that reached the ledger after a snapshot can cause small false gaps.
- `derivation`: sum of booked amounts in ledger == derived list == sum over categories (missing category counts as `other`) + confirmed transfers. `diff` = ledger total minus categories+transfers (EUR); `ok:false` means money was lost in derivation.
- `data_quality` (admin): accounts whose booked lines carry no booking, value or transaction date (`tx_dates.effective_day` is None); such lines miss cycles and contracts, and the bank-side PayPal debit of the same purchase counts instead. Empty list = nothing to report. `transactionDate` is taken from the bank at import, so lines stored before 0.24.4 gain it only with the next "Neu importieren", not with "Aktualisieren".

Existing `GET /refresh_status` is unchanged.

## Ledger identity of PayPal rows (processing version 3)

A row with only a transaction date used to have no date in its fingerprint, so equal payments
collapsed. At start `Ledger.migrate_fingerprint_ids` gives such rows their new id before the replay;
one-off answers, labels, manual refund allocations and contract assignments follow the rename.
Transfer decisions stored under the old random chain ids point at nothing and are dropped; chain ids
are now derived from the member bookings. Replay also picks up the counterparty IBANs needed for the
own-account check; they stay in the encrypted ledger and leave no API.
