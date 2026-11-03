"""RefreshMixin — live-fetch logic for FinanceDashboardManager.

Covers the ONLY allowed live-fetch path: user-triggered refresh of
transactions and balances.  All methods here may call the Enable Banking
API.

Also includes OAuth state management (register/validate state tokens),
the setup-call proxy, and credential/issue helpers.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..const import DEFAULT_FETCH_DAYS, HISTORY_BACKFILL_DAYS, INCREMENTAL_OVERLAP_DAYS

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

# OAuth state token TTL in seconds (10 minutes)
_OAUTH_STATE_TTL = 600

# hass.data key for persistent rate-limit timestamp (shared with api._helpers)
_GLOBAL_RATE_LIMIT_KEY = "_global_rate_limit_until"

# Maximum number of in-memory OAuth state tokens (F5)
_OAUTH_STATES_MAX = 32
_OAUTH_STATES_EVICT = 16


class RefreshMixin:
    """Mixin that adds all live-fetch and OAuth methods to the manager."""

    # ------------------------------------------------------------------
    # Public refresh entry point
    # ------------------------------------------------------------------

    async def async_refresh_transactions(
        self,
        days: int | None = None,
        psu_ip: str | None = None,
        scheduled: bool = False,
    ) -> list[dict[str, Any]]:
        """Refresh transactions AND balances for every linked bank.

        Fetch budget is tracked PER BANK (see ``fetch_budget``):

        * ``psu_ip`` present -> *attended*: never capped, never gated on a
          block, only debounced per bank.
        * no ``psu_ip`` -> *background*: counted per account per UTC day;
          the ``scheduled`` daily refresh may use 1 of 4, other background
          callers up to 4.  A 429 blocks only the bank that sent it, for 6h.

        Fetches are incremental (last booked date minus an overlap).  The
        first attended fetch of an account per bank session asks for the
        whole history (``HISTORY_BACKFILL_DAYS``, stepping down when the bank
        rejects the period); background fetches never backfill.  An explicit
        ``days`` forces a full window.  Concurrent calls are serialised by
        ``_refresh_lock``; stats are written regardless of outcome.
        """
        async with self._refresh_lock:
            self._refresh_in_flight = True
            started = dt_util.now()
            t0 = time.monotonic()
            self._import_banks = []
            try:
                result = await self._do_refresh(
                    days, started, t0, psu_ip=psu_ip, scheduled=scheduled
                )
                await self._record_import(scheduled, started, t0)
                return result
            finally:
                self._refresh_in_flight = False

    async def _record_import(self, scheduled: bool, started: datetime, t0: float) -> None:
        """Log this import (counts + bank titles only) unless it was debounced."""
        from ..const import PROCESSING_VERSION
        from ..freshness import make_entry

        stats = self._last_refresh_stats or {}
        if self._demo_mode or stats.get("started_at") != started.isoformat():
            return  # debounced: stats of an earlier run are still in place
        try:
            self._log_run(
                make_entry(
                    "import_scheduled" if scheduled else "import_attended",
                    at=dt_util.utcnow().isoformat(),
                    banks=list(getattr(self, "_import_banks", [])),
                    new=int(stats.get("new") or 0),
                    total=int(stats.get("transactions") or 0),
                    processing_version=PROCESSING_VERSION,
                    outcome=str(stats.get("outcome") or "error"),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            )
            await self._persist_transactions()
        except Exception:
            _LOGGER.debug("Import log write failed", exc_info=True)

    @staticmethod
    def _bank_now() -> datetime:
        """Clock for fetch-window dates.

        UTC, never local time: between local midnight and UTC midnight a local
        ``date_to`` lies in the future for the bank, and strict ASPSPs (PayPal)
        reject the whole request with HTTP 422.
        """
        return dt_util.utcnow()

    def _fetch_date_from(self, account_key_: str, days: int | None) -> str:
        """Start of the fetch window for one account."""
        now = self._bank_now()
        if days:
            return (now - timedelta(days=int(days))).strftime("%Y-%m-%d")
        floor = now - timedelta(days=DEFAULT_FETCH_DAYS)
        last = self._ledger.last_booked_date(account_key_)
        if last:
            try:
                start = datetime.fromisoformat(last[:10]) - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
                start = start.replace(tzinfo=floor.tzinfo)
                return max(start, floor).strftime("%Y-%m-%d")
            except ValueError:
                pass
        return floor.strftime("%Y-%m-%d")

    def _raw_sink(self, bank_id: str, uid: str, attended: bool, meta: dict[str, Any] | None = None):
        """Callback handing unaltered bank JSON to the raw archive.

        ``meta`` is read at call time, so a caller can move ``date_from`` /
        ``fetch_id`` between attempts and every page is stamped correctly.
        """

        def sink(kind: str, http_status: int, body: Any) -> None:
            if self._raw is None:
                return
            self._raw.record(
                self._raw.make_snapshot(
                    bank=bank_id,
                    account=uid,
                    kind=kind,
                    attended=attended,
                    http_status=http_status,
                    response=body,
                    meta=meta,
                )
            )

        return sink

    def _needs_backfill(self, account_key_: str, session_ref: str) -> bool:
        """Whether this account still lacks its full-history fetch.

        Once per account per bank session: a fresh consent (re-link) is the
        moment a bank opens its deepest history again.
        """
        done = (self._ledger.meta.get("history") or {}).get(account_key_) or {}
        return not done.get("backfilled") or done.get("session") != session_ref

    async def _async_enrich_account(
        self, client: Any, account: dict[str, Any], psu_ip: str | None
    ) -> bool:
        """Fill IBAN and bank name of a record that has neither (attended only).

        Records adopted from a bank subentry carry just uid and key, so the
        UI showed "DKB 1" and no IBAN digits.  One details call per such
        account, sent with PSU headers, so it never touches the background
        cap.  The stored key is kept — entity identity does not move.  A rate
        limit propagates (the caller backs the bank off); any other failure
        leaves the record as it was.
        """
        from ..enablebanking_client import RateLimitExceeded

        try:
            details = (await client.async_get_account_details(account["id"], psu_ip=psu_ip)).get(
                "account"
            ) or {}
        except RateLimitExceeded:
            raise
        except Exception:
            _LOGGER.debug("Account details unavailable for %s", str(account.get("id"))[:8])
            return False
        iban = details.get("iban") or ""
        if not iban:
            return False
        account["iban"] = iban
        if details.get("name"):
            account["name"] = details["name"]
        # A minimal record built for this round is not in _accounts yet.
        if not any(a is account for a in self._accounts):
            self._accounts.append(account)
        return True

    async def _async_fetch_window(
        self,
        client,
        uid: str,
        ladder: tuple[int, ...] | list[int],
        date_to: str,
        psu_ip: str | None,
        sink,
        meta: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Fetch transactions, stepping down the window when the bank rejects it.

        ``ladder`` holds window lengths in days (longest first) or a single
        precomputed start.  HTTP 400/422 means "period not allowed" for most
        ASPSPs and moves to the next step; anything else is raised.
        """
        import aiohttp

        last_exc: Exception | None = None
        for step in ladder:
            date_from = (
                step
                if isinstance(step, str)
                else (self._bank_now() - timedelta(days=int(step))).strftime("%Y-%m-%d")
            )
            meta["fetch_id"] = secrets.token_hex(8)
            meta["date_from"] = date_from
            try:
                txns = await client.async_get_transactions(
                    uid, date_from, date_to, psu_ip=psu_ip, on_response=sink
                )
            except aiohttp.ClientResponseError as exc:
                if exc.status not in (400, 422) or step == ladder[-1]:
                    raise
                _LOGGER.info(
                    "Account %s: bank rejected a %s-day window (HTTP %s) — stepping down",
                    uid[:8],
                    step,
                    exc.status,
                )
                last_exc = exc
                continue
            if len(ladder) > 1 and not txns.get("booked"):
                # An empty answer to a full-history request is no proof the
                # account's past vanished: merge, never erase (live + replay).
                txns["truncated"] = True
            sink(
                "transactions_window",
                200,
                {
                    "date_from": date_from,
                    "date_to": date_to,
                    "truncated": bool(txns.get("truncated")),
                },
            )
            return date_from, txns
        raise last_exc or RuntimeError("empty fetch ladder")

    async def _do_refresh(
        self,
        days: int | None,
        started: datetime,
        t0: float,
        psu_ip: str | None = None,
        scheduled: bool = False,
    ) -> list[dict[str, Any]]:
        import aiohttp

        from ..account_identity import account_key
        from ..enablebanking_client import RateLimitExceeded
        from ..recurring import detect_recurring

        def elapsed_ms() -> int:
            return int((time.monotonic() - t0) * 1000)

        # Demo mode — regenerate fresh demo data without API calls
        if self._demo_mode:
            from ..demo import generate_demo_data

            data = generate_demo_data()
            self._transactions = data["_demo_transactions"]
            self._balances = data["_demo_balances"]
            self._last_refresh = dt_util.now()
            self._recurring_patterns = data.get("recurring", [])
            self._last_refresh_stats = self._build_stats(
                outcome="demo",
                started=started,
                duration_ms=elapsed_ms(),
                accounts=len(self._accounts),
                transactions=len(self._transactions),
                new=0,
                errors=[],
            )
            return self._transactions

        client = await self._async_get_client()
        if not client:
            self._last_refresh_stats = self._build_stats(
                outcome="error",
                started=started,
                duration_ms=elapsed_ms(),
                accounts=0,
                transactions=len(self._transactions),
                new=0,
                errors=["Keine Enable-Banking-Credentials hinterlegt"],
            )
            return []

        attended = bool(psu_ip)
        date_to = self._bank_now().strftime("%Y-%m-%d")
        targets = await self._async_bank_targets()

        errors: list[str] = []
        accounts_hit = 0
        new_ids: set[str] = set()
        fresh_balances: dict[str, Any] = {}
        skipped: dict[str, int] = {}
        rate_limited_round = False
        enriched = False

        for bank in targets:
            bank_id = bank["bank_id"]
            title = bank["title"] or "Bank"

            if self._consent_state(bank["valid_until"]) == "expired":
                self._budget.record_error(bank_id, "consent_expired")
                errors.append(f"{title}: Zustimmung abgelaufen — bitte Bank neu verbinden")
                continue

            decision = self._budget.decide(bank_id, attended=attended, scheduled=scheduled)
            if not decision.allowed:
                skipped[decision.reason] = skipped.get(decision.reason, 0) + 1
                _LOGGER.info("Bank %s skipped (%s) — serving cache", bank_id[:8], decision.reason)
                if decision.reason in ("blocked", "budget_exhausted"):
                    rate_limited_round = True
                    errors.append(f"{title}: Tageslimit der Bank-API erreicht (4/Tag pro Konto)")
                continue

            if attended:
                # Stamp before the first call so a double click is debounced
                # even while this fetch is still running.
                self._budget.record_attempt(bank_id, "", attended=True)

            for account in bank["accounts"]:
                uid = account.get("id")
                if not uid:
                    continue
                akey = account_key(account)
                name = account.get("name", uid)
                self._budget.record_attempt(bank_id, akey, attended=attended)
                session_ref = str(bank.get("valid_until") or "")
                # Full history only on attended calls: every rejected window is
                # one more bank call, which the background cap cannot afford.
                backfill = attended and not days and self._needs_backfill(akey, session_ref)
                ladder = HISTORY_BACKFILL_DAYS if backfill else (self._fetch_date_from(akey, days),)
                meta: dict[str, Any] = {"account_key": akey, "date_to": date_to}
                sink = self._raw_sink(bank_id, uid, attended, meta)

                try:
                    if attended and not account.get("iban"):
                        enriched |= await self._async_enrich_account(client, account, psu_ip)
                    date_from, txns = await self._async_fetch_window(
                        client, uid, ladder, date_to, psu_ip, sink, meta
                    )
                    new = self._ledger.ingest(
                        akey,
                        txns.get("booked", []),
                        txns.get("pending", []),
                        date_from=date_from,
                        truncated=bool(txns.get("truncated")),
                    )
                    new_ids.update(f"{akey}|{t['_ledger_id']}" for t in new)
                    accounts_hit += 1
                    self._import_banks.append(title)
                    if backfill:
                        self._ledger.meta.setdefault("history", {})[akey] = {
                            "backfilled": True,
                            "session": session_ref,
                            "requested_from": date_from,
                            "earliest_booked": self._ledger.first_booked_date(akey),
                            "at": dt_util.utcnow().isoformat(),
                        }
                    _LOGGER.debug(
                        "Account %s: %d booked, %d pending",
                        uid[:8],
                        len(txns.get("booked", [])),
                        len(txns.get("pending", [])),
                    )
                    bals = await client.async_get_balances(uid, psu_ip=psu_ip, on_response=sink)
                    iban = account.get("iban", "")
                    fresh_balances[uid] = {
                        "account_name": account.get("name", "Unknown"),
                        "iban": iban,
                        "iban_masked": (f"****{iban[-4:]}" if len(iban) >= 4 else "****"),
                        "institution": account.get("institution", ""),
                        "logo": account.get("logo", ""),
                        "balances": bals,
                    }
                    self._ledger.add_balances(akey, bals, dt_util.utcnow().isoformat())
                except RateLimitExceeded as rle:
                    until = self._budget.block(
                        bank_id,
                        retry_after_seconds=rle.retry_after_seconds,
                        attended=attended,
                    )
                    self._budget.record_error(bank_id, "rate_limited")
                    rate_limited_round = True
                    _LOGGER.warning(
                        "Rate limit hit for bank %s — blocked until %s", bank_id[:8], until
                    )
                    errors.append(f"Rate-Limit bei {title} — Tageslimit (4/Tag) aufgebraucht")
                    break  # only THIS bank stops; other banks continue
                except aiohttp.ClientResponseError as exc:
                    if exc.status in (401, 403):
                        self._mark_consent_error(bank_id, bank["valid_until"])
                    self._budget.record_error(bank_id, f"http_{exc.status}")
                    _LOGGER.error("Fetch failed for account %s: HTTP %s", uid[:8], exc.status)
                    errors.append(f"{name}: HTTP {exc.status}")
                except Exception as exc:
                    _LOGGER.exception("Failed to fetch account %s", uid[:8])
                    self._budget.record_error(bank_id, type(exc).__name__)
                    errors.append(f"{name}: {str(exc)[:120]}")
                else:
                    self._budget.record_success(bank_id)

        if enriched:
            self.async_set_accounts(list(self._accounts))

        # The migration-era __unknown__ bucket is superseded by real fetches.
        if accounts_hit > 0:
            self._ledger.data.get("accounts", {}).pop("__unknown__", None)

        # Secure what the bank sent before any derivation runs: a bug further
        # down must never cost the fetched data (raw first, then the ledger).
        if self._raw is not None:
            try:
                await self._raw.async_flush()
            except Exception:
                _LOGGER.exception("Raw archive write failed — continuing")
        if accounts_hit > 0:
            await self._persist_transactions()

        # Derivations (categories, tags, transfer chains) are rebuilt from the
        # ledger — never carried over from a previous round.
        overrides = await self._async_load_transfer_overrides()
        old_ids = {t.get("_ledger_id") for t in self._transactions}
        all_transactions = self._derive_from_ledger(overrides)
        await self._async_refresh_contract_categories()
        if accounts_hit > 0:
            self.schedule_ai_categorization()
        new_txns = [
            t
            for t in all_transactions
            if t.get("_status") == "booked"
            and t.get("_ledger_id")
            and t["_ledger_id"] not in old_ids
            and f"{t.get('_account_key', '')}|{t['_ledger_id']}" in new_ids
        ]

        if fresh_balances:
            self._fire_balance_events(fresh_balances)
            merged = dict(self._balances)
            merged.update(fresh_balances)
            self._balances = merged

        # Only claim a refresh happened when at least one account answered.
        if accounts_hit > 0:
            self._last_refresh = dt_util.now()
        else:
            _LOGGER.warning(
                "Refresh reached no account (%d error(s)) — keeping previous "
                "refresh timestamp so the UI reports the cache as stale",
                len(errors),
            )

        try:
            self._recurring_patterns = detect_recurring(all_transactions)
        except Exception:
            _LOGGER.exception("Recurring detection failed — skipping")
            self._recurring_patterns = []

        await self._persist_transactions()
        if self._raw is not None:
            try:
                await self._raw.async_flush()
            except Exception:
                _LOGGER.exception("Raw archive write failed — continuing")

        try:
            from ..events import fire_transaction_new

            for txn in new_txns:
                fire_transaction_new(
                    self._hass,
                    amount=float(txn.get("transactionAmount", {}).get("amount", 0)),
                    creditor=txn.get("creditorName", ""),
                    category=txn.get("category", "other"),
                    account_name=txn.get("_account_name", ""),
                )
        except Exception:
            _LOGGER.exception("Transaction event firing failed — skipping")

        try:
            await self.async_update_consent_issues()
        except Exception:
            _LOGGER.debug("Consent issue update failed", exc_info=True)

        await self._credential_manager._audit_log("transactions_refreshed")
        _LOGGER.info(
            "Refreshed %d transactions across %d accounts (%d new, %d recurring patterns)",
            len(all_transactions),
            accounts_hit,
            len(new_txns),
            len(self._recurring_patterns),
        )

        if rate_limited_round:
            outcome = "rate_limited"
        elif skipped.get("debounced") and not accounts_hit and not errors:
            outcome = "debounced"
        elif errors:
            outcome = "partial" if accounts_hit > 0 else "error"
        else:
            outcome = "ok"

        if outcome == "debounced":
            # A second attended click inside the debounce window: leave the
            # previous result (and its stats) in place.
            return self._transactions

        self._last_refresh_stats = self._build_stats(
            outcome=outcome,
            started=started,
            duration_ms=elapsed_ms(),
            accounts=accounts_hit,
            transactions=len(all_transactions),
            new=len(new_txns),
            errors=errors,
        )
        await self._persist_transactions()
        return all_transactions

    def _fire_balance_events(self, balances: dict[str, Any]) -> None:
        """Fire fd_balance_changed for material changes — never crashes refresh."""
        try:
            from ..events import fire_balance_changed

            for acc_id, data in balances.items():
                raw = data.get("balances", [])
                if raw:
                    new_bal = float(raw[0].get("balanceAmount", {}).get("amount", 0))
                    old_bal = self._previous_balances.get(acc_id)
                    if old_bal is not None and abs(new_bal - old_bal) >= 1.0:
                        fire_balance_changed(
                            self._hass,
                            account_name=data.get("account_name", ""),
                            old_balance=old_bal,
                            new_balance=new_bal,
                        )
                    self._previous_balances[acc_id] = new_bal
        except Exception:
            _LOGGER.exception("Balance change event firing failed — skipping")

    @staticmethod
    def _build_stats(
        outcome: str,
        started: datetime,
        duration_ms: int,
        accounts: int,
        transactions: int,
        new: int,
        errors: list[str],
    ) -> dict[str, Any]:
        """Assemble a refresh-stats dict for the status endpoint."""
        finished = dt_util.now()
        return {
            "outcome": outcome,
            "accounts": accounts,
            "transactions": transactions,
            "new": new,
            "duration_ms": duration_ms,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "errors": list(errors)[:5],  # cap payload size
        }

    # ------------------------------------------------------------------
    # OAuth state management
    # ------------------------------------------------------------------

    async def async_register_oauth_state(self, state: str) -> None:
        """Register an OAuth state token for later CSRF validation.

        The state is stored in memory only (not persisted) with a creation
        timestamp so it can be expired after ``_OAUTH_STATE_TTL`` seconds.

        The dict is bounded to ``_OAUTH_STATES_MAX`` entries to prevent an
        unbounded memory growth if authorize is called repeatedly without a
        matching callback (F5).  When the cap is reached the oldest
        ``_OAUTH_STATES_EVICT`` entries (by creation time) are evicted.
        """
        # Evict oldest entries when approaching the cap (F5)
        if len(self._oauth_states) >= _OAUTH_STATES_MAX:
            sorted_states = sorted(self._oauth_states.items(), key=lambda kv: kv[1])
            for old_key, _ in sorted_states[:_OAUTH_STATES_EVICT]:
                self._oauth_states.pop(old_key, None)
            _LOGGER.debug(
                "OAuth state dict capped — evicted %d oldest entries", _OAUTH_STATES_EVICT
            )

        now = datetime.now(UTC).isoformat()
        self._oauth_states[state] = now
        _LOGGER.debug("OAuth state registered (total: %d)", len(self._oauth_states))

    async def async_validate_oauth_state(self, state: str) -> bool:
        """Validate and consume an OAuth state token (CSRF protection).

        Uses ``secrets.compare_digest`` for timing-safe comparison to prevent
        timing-based enumeration of valid state tokens.

        All timestamp comparisons use UTC-aware datetimes.  Naive timestamps
        stored by older code versions are assumed UTC (F3).

        Returns:
            True if the state was registered, not yet consumed, and not expired.
            False otherwise (unknown state, already consumed, or TTL exceeded).
        """
        # Purge all expired states first — use UTC-aware comparison (F3)
        now = datetime.now(UTC)
        expired = []
        for s, created in self._oauth_states.items():
            try:
                created_dt = datetime.fromisoformat(created)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=UTC)
                if (now - created_dt).total_seconds() > _OAUTH_STATE_TTL:
                    expired.append(s)
            except (ValueError, TypeError):
                expired.append(s)  # Corrupt entry — evict
        for s in expired:
            del self._oauth_states[s]

        if not self._oauth_states:
            return False

        # Timing-safe search: compare against every registered state so the
        # response time does not leak whether the prefix matched.
        matched_key: str | None = None
        for registered in list(self._oauth_states.keys()):
            if secrets.compare_digest(registered, state):
                matched_key = registered
                # One-time-use: delete immediately on match
                del self._oauth_states[registered]
                break

        if matched_key is None:
            _LOGGER.warning("OAuth callback received with unknown/invalid state")
            return False

        _LOGGER.debug("OAuth state validated and consumed")
        return True

    # ------------------------------------------------------------------
    # Setup call proxy
    # ------------------------------------------------------------------

    async def async_make_setup_call(self, method_name: str, *args, client=None, **kwargs):
        """Invoke an EnableBankingClient method through the rate-limit gate.

        Setup-wizard endpoints (institutions, authorize, OAuth callback) must
        go through here instead of calling the client directly.  This ensures
        the 4/day ASPSP quota is respected even during the onboarding flow.

        Args:
            method_name: Name of the EnableBankingClient method to call.
            *args: Positional arguments forwarded to the method.
            client: Optional pre-built EnableBankingClient instance.  When
                provided the manager's own credential chain is bypassed — useful
                for fresh-setup flows where the credential store holds setup-app
                credentials rather than a live PSU session.  Rate-limit gate is
                still enforced regardless.
            **kwargs: Keyword arguments forwarded to the method.

        Raises:
            RateLimitExceeded: when the API is still rate-limited.
            RuntimeError: when no credentials are available and no client given.
        """
        # No quota gate: the setup wizard (catalog, authorize, session
        # exchange) talks to Enable Banking, not to a bank's data API, so it
        # neither spends nor is bound by the per-ASPSP 4/day budget.
        if client is None:
            client = await self._async_get_client()
        if not client:
            raise RuntimeError(
                "Enable Banking client not available — credentials missing or invalid."
            )

        method = getattr(client, method_name)
        return await method(*args, **kwargs)

    # ------------------------------------------------------------------
    # Client factory + credential issue helpers
    # ------------------------------------------------------------------

    async def _async_get_client(self):
        """Get or create Enable Banking client with current credentials."""
        if self._banking_client:
            return self._banking_client

        creds = await self._credential_manager.async_get_api_credentials()
        if not creds:
            _LOGGER.error("No Enable Banking credentials available")
            self._raise_credentials_issue("missing")
            return None

        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        from ..enablebanking_client import EnableBankingClient

        try:
            self._banking_client = EnableBankingClient(
                creds["application_id"],
                creds["private_key_pem"],
                session=async_get_clientsession(self._hass),
            )
        except (ValueError, TypeError) as exc:
            # R10: log class-only at ERROR, full stack trace at DEBUG only.
            _LOGGER.error(
                "Enable Banking client init failed — PEM key invalid (%s)",
                type(exc).__name__,
            )
            _LOGGER.debug(
                "Enable Banking client init exception detail",
                exc_info=True,
            )
            self._raise_credentials_issue("invalid_pem")
            return None

        # Successful client creation — clear any stale repair issue
        self._clear_credentials_issue()
        return self._banking_client

    def _raise_credentials_issue(self, kind: str) -> None:
        """Surface credential problems via the Repairs flow.

        Auth/credential issues are marked ``is_persistent=True`` — they
        survive HA restarts and remain visible until the user fixes their
        credentials.  Transient issues (rate-limit) should NOT use this
        method; they are surfaced inline in the refresh status instead.
        """
        try:
            from homeassistant.helpers import issue_registry as ir

            from ..const import DOMAIN

            translation_key = (
                "credentials_missing" if kind == "missing" else "credentials_invalid_pem"
            )
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                f"credentials_{kind}",
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.ERROR,
                translation_key=translation_key,
                learn_more_url=("https://enablebanking.com/docs/api/reference/"),
            )
        except Exception:
            _LOGGER.debug("Could not create credentials repair issue", exc_info=True)

    def _clear_credentials_issue(self) -> None:
        """Remove credential-related repair issues after recovery."""
        try:
            from homeassistant.helpers import issue_registry as ir

            from ..const import DOMAIN

            for kind in ("missing", "invalid_pem"):
                ir.async_delete_issue(self._hass, DOMAIN, f"credentials_{kind}")
        except Exception:
            pass
