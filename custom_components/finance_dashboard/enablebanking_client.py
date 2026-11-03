"""Enable Banking Open Banking API client.

Handles communication with the Enable Banking API for PSD2-compliant
bank account data access. Replaces the GoCardless client while normalizing
all response data to GoCardless-compatible field names so downstream
consumers (manager.py, categorizer.py, api.py) remain unchanged.

SECURITY:
- All API communication over HTTPS only
- JWT signed per-request with RSA private key (no long-lived tokens in memory)
- No credentials logged or cached beyond request scope
- Private key held only in memory, never written to disk by this module
"""

from __future__ import annotations

import logging
import re
import secrets
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import aiohttp
import jwt
from cryptography.hazmat.primitives import serialization

from .const import ENABLEBANKING_BASE_URL, TRANSACTION_MAX_PAGES, VERSION
from .text_norm import repair_mojibake

# Type alias for optional injected session
_SessionType = aiohttp.ClientSession | None

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Log sanitizer — strips PII from error response bodies before any logging.
# ---------------------------------------------------------------------------

_RE_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7,25}\b")
_RE_ACCOUNT_ID = re.compile(r"\b\d{16,19}\b")
_RE_AMOUNT = re.compile(r"\b\d+[.,]\d{2}\s*(?:EUR|€)\b", re.IGNORECASE)


def _sanitize_log(text: str) -> str:
    """Return *text* with IBANs, long numeric account IDs and amounts masked.

    Applied to all banking response bodies before they reach the log sink so
    that a misconfigured log shipper cannot exfiltrate financial PII.

    Examples:
        "DE89370400440532013000" → "***IBAN***"
        "1234567890123456"       → "***ACCOUNT***"
        "1234.56 EUR"            → "***AMOUNT***"
    """
    text = _RE_IBAN.sub("***IBAN***", text)
    text = _RE_ACCOUNT_ID.sub("***ACCOUNT***", text)
    text = _RE_AMOUNT.sub("***AMOUNT***", text)
    return text


class RateLimitExceeded(Exception):
    """Raised when the banking API returns HTTP 429 (daily quota exhausted).

    Attributes:
        retry_after_seconds: Value from the ``Retry-After`` response header
            (seconds), or ``None`` when the header was absent/unparseable.
            Callers should use ``min(midnight, now + retry_after_seconds)``
            as the rate-limit reset time when this value is set.
    """

    def __init__(self, message: str = "", retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds: int | None = retry_after_seconds


class EnableBankingClient:
    """Client for Enable Banking Open Banking API.

    SECURITY:
    - All API communication over HTTPS only
    - JWT signed per-request (no long-lived tokens in memory)
    - No credentials logged or cached beyond request scope
    """

    def __init__(
        self,
        application_id: str,
        private_key_pem: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize with Enable Banking credentials.

        Args:
            application_id: Enable Banking application ID (used as JWT kid).
            private_key_pem: RSA private key in PEM format for JWT signing.
            session: Optional shared aiohttp ClientSession.  When provided the
                caller is responsible for lifecycle management (HA-owned sessions
                must not be closed by this client).  When omitted a private
                session is created lazily on first request and closed on
                ``async_close()``.
        """
        self._application_id = application_id
        pem_bytes = (
            private_key_pem.encode() if isinstance(private_key_pem, str) else private_key_pem
        )
        try:
            self._private_key = serialization.load_pem_private_key(pem_bytes, password=None)
        except (ValueError, TypeError):
            # PEM may have lost newlines — try to reconstruct
            _LOGGER.debug("PEM load failed, attempting newline reconstruction")
            pem_str = pem_bytes.decode() if isinstance(pem_bytes, bytes) else pem_bytes
            pem_str = self._reconstruct_pem(pem_str)
            self._private_key = serialization.load_pem_private_key(pem_str.encode(), password=None)
        # Session management: injected → caller-owned; None → we own it.
        self._session: aiohttp.ClientSession | None = session
        self._session_owner: bool = session is None  # True → we must close

    async def async_close(self) -> None:
        """Close the private session if we own it.

        No-op when an external session was injected at construction time.
        """
        if self._session_owner and self._session is not None:
            await self._session.close()
            self._session = None

    @staticmethod
    def _reconstruct_pem(raw: str) -> str:
        """Reconstruct PEM with proper line breaks.

        C9: Marker-type detection (PKCS1 vs PKCS8) is performed BEFORE
        stripping the markers so the check is not confused by partial or
        escaped header text.
        """
        # Normalize escaped newlines first so marker strings are intact.
        raw = raw.replace("\\n", "\n")
        # C9: detect key type BEFORE stripping markers — once the header
        # lines are removed the type information is gone.
        is_pkcs1 = "RSA PRIVATE KEY" in raw or "BEGIN RSA PRIVATE KEY" in raw
        # Strip all known PEM header/footer lines.
        for marker in (
            "-----BEGIN PRIVATE KEY-----",
            "-----END PRIVATE KEY-----",
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----END RSA PRIVATE KEY-----",
        ):
            raw = raw.replace(marker, "")
        body = raw.replace("\n", "").replace("\r", "").replace(" ", "")
        if is_pkcs1:
            h = "-----BEGIN RSA PRIVATE KEY-----"
            f = "-----END RSA PRIVATE KEY-----"
        else:
            h = "-----BEGIN PRIVATE KEY-----"
            f = "-----END PRIVATE KEY-----"
        lines = [body[i : i + 64] for i in range(0, len(body), 64)]
        return f"{h}\n" + "\n".join(lines) + f"\n{f}"

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def async_test_connection(self) -> bool:
        """Test API connection by listing institutions.

        Returns True if the API responds successfully, False otherwise.
        """
        try:
            institutions = await self.async_get_institutions("DE")
            return isinstance(institutions, list)
        except Exception:
            _LOGGER.exception("Enable Banking connection test failed")
            return False

    async def async_get_institutions(self, country: str = "DE") -> list[dict[str, Any]]:
        """Get available banks (ASPSPs) for a country.

        Args:
            country: ISO 3166-1 alpha-2 country code (default: DE).

        Returns:
            List of institution dicts with keys: id, name, bic, logo, countries
            (normalized from Enable Banking ASPSP format).
        """
        result = await self._async_request("GET", f"/aspsps?country={country}")
        aspsps = result if isinstance(result, list) else result.get("aspsps", [])
        return [self._normalize_institution(a) for a in aspsps]

    async def async_create_auth(
        self,
        aspsp_name: str,
        aspsp_country: str,
        redirect_url: str,
        valid_until: str | None = None,
        psu_type: str = "personal",
        state: str = "",
    ) -> dict[str, Any]:
        """Initiate bank authorization (PSU redirect flow).

        Args:
            aspsp_name: Bank name as returned by async_get_institutions.
            aspsp_country: ISO 3166-1 alpha-2 country code.
            redirect_url: URL to redirect the user back to after auth.
            valid_until: RFC3339 datetime with timezone for access validity.
            psu_type: Payment service user type (default: personal).
            state: Arbitrary string for request tracking (required by API).

        Returns:
            Dict with keys: url (authorization URL), auth_id.
        """
        payload: dict[str, Any] = {
            "aspsp": {
                "name": aspsp_name,
                "country": aspsp_country,
            },
            "redirect_url": redirect_url,
            "psu_type": psu_type,
            "state": state or str(uuid.uuid4()),
        }
        if valid_until:
            payload["access"] = {"valid_until": valid_until}

        result = await self._async_request("POST", "/auth", json=payload)
        return {
            "url": result.get("url", ""),
            "auth_id": result.get("authorization_id", result.get("auth_id", "")),
        }

    async def async_create_session(self, auth_code: str) -> dict[str, Any]:
        """Exchange authorization code for a session.

        Args:
            auth_code: Authorization code received from the redirect callback.

        Returns:
            Dict with keys:
            - session_id: Enable Banking session identifier
            - accounts: list of {id, iban, name, currency}
        """
        result = await self._async_request("POST", "/sessions", json={"code": auth_code})

        session_id = result.get("session_id", result.get("id", ""))
        raw_accounts = result.get("accounts", [])

        accounts = []
        for acct in raw_accounts:
            # IBAN can be nested in account_id object or flat
            account_id_obj = acct.get("account_id", {})
            iban = (
                account_id_obj.get("iban", "")
                if isinstance(account_id_obj, dict)
                else acct.get("iban", "")
            )
            other = account_id_obj.get("other") if isinstance(account_id_obj, dict) else None
            record = {
                "id": acct.get("uid", acct.get("id", "")),
                "iban": iban,
                "name": acct.get("account_name", acct.get("name", "")),
                "currency": acct.get("currency", "EUR"),
            }
            # Identity inputs for IBAN-less products (card accounts).  Only
            # added when the bank supplies them, so IBAN records are unchanged.
            if isinstance(other, dict) and other.get("identification"):
                record["identification"] = str(other["identification"])
            if acct.get("cash_account_type"):
                record["account_type"] = str(acct["cash_account_type"])
            accounts.append(record)

        return {"session_id": session_id, "accounts": accounts}

    async def async_get_account_details(
        self, account_id: str, psu_ip: str | None = None
    ) -> dict[str, Any]:
        """Get account metadata.

        Args:
            account_id: Enable Banking account ID.
            psu_ip: Optional PSU IP address from the originating user request.

        Returns:
            Dict normalized to GoCardless format:
            {account: {iban, name, currency, ...}}
        """
        # Enable Banking has no bare /accounts/{id} resource (404); the
        # metadata lives under /details, with the IBAN nested in account_id.
        result = await self._async_request(
            "GET", f"/accounts/{account_id}/details", psu_ip=psu_ip, psu_ua=self._PSU_UA
        )
        acct = result if "iban" in result or "account_id" in result else result.get("account", result)
        account_ref = acct.get("account_id")
        iban = account_ref.get("iban", "") if isinstance(account_ref, dict) else ""
        return {
            "account": {
                "iban": iban or acct.get("iban", ""),
                "name": acct.get("account_name", acct.get("name", "")),
                "currency": acct.get("currency", "EUR"),
                "product": acct.get("product", ""),
                "ownerName": acct.get("owner_name", ""),
            }
        }

    # Canonical PSU user-agent for user-triggered live calls.
    # Set once at class level so all instances share the same string.
    _PSU_UA: str = f"HomeAssistant-Finance-Dashboard/{VERSION}"
    # Pagination follows continuation_key until the bank stops sending one.
    # The only bound is a loop guard against a misbehaving ASPSP.
    _MAX_TRANSACTION_PAGES: int = TRANSACTION_MAX_PAGES

    async def async_get_balances(
        self,
        account_id: str,
        psu_ip: str | None = None,
        on_response: Callable[[str, int, Any], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Get account balances.

        ``on_response(kind, http_status, body)`` receives the unaltered bank
        JSON (raw-archive hook).

        Args:
            account_id: Enable Banking account ID.
            psu_ip: Optional PSU IP address from the originating user request.

        Returns:
            List normalized to GoCardless format:
            [{balanceAmount: {amount, currency}, balanceType, referenceDate}]
        """
        result = await self._async_request(
            "GET",
            f"/accounts/{account_id}/balances",
            psu_ip=psu_ip,
            psu_ua=self._PSU_UA,
        )
        if on_response:
            on_response("balances", 200, result)
        return self.parse_balances(result)

    async def async_get_transactions(
        self,
        account_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        psu_ip: str | None = None,
        on_response: Callable[[str, int, Any], None] | None = None,
    ) -> dict[str, Any]:
        """Get account transactions.

        Args:
            account_id: Enable Banking account ID.
            date_from: Start date (YYYY-MM-DD, optional).
            date_to: End date (YYYY-MM-DD, optional).
            psu_ip: Optional PSU IP address from the originating user request.

        Returns:
            Dict normalized to GoCardless format:
            {booked: [...], pending: [...]}
            Each transaction has: transactionId, bookingDate,
            transactionAmount: {amount, currency},
            remittanceInformationUnstructured, creditorName.

        The real Enable Banking response is ``{"transactions": [...],
        "continuation_key": "..."}`` — a flat LIST with a per-transaction
        ``status``, not pre-sorted booked/pending buckets. The buckets are
        rebuilt here from each transaction's own status so that everything
        downstream (which filters on ``_status``) keeps working.

        Pagination is followed via ``continuation_key``. Each page is one API
        call against the 4/day/ASPSP budget, so the number of pages is capped
        and a truncation is logged rather than silently swallowed.
        """
        params = []
        if date_from:
            params.append(f"date_from={date_from}")
        if date_to:
            params.append(f"date_to={date_to}")

        booked: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        continuation_key: str | None = None
        seen_keys: set[str] = set()
        pages = 0
        truncated = False

        while True:
            page_params = list(params)
            if continuation_key:
                page_params.append(f"continuation_key={quote(continuation_key, safe='')}")
            query = f"?{'&'.join(page_params)}" if page_params else ""

            result = await self._async_request(
                "GET",
                f"/accounts/{account_id}/transactions{query}",
                psu_ip=psu_ip,
                psu_ua=self._PSU_UA,
            )
            pages += 1
            if on_response:
                on_response("transactions", 200, result)

            page_booked, page_pending, continuation_key = self.parse_transaction_page(result)
            booked.extend(page_booked)
            pending.extend(page_pending)

            if not continuation_key:
                break
            # Loop guard: a repeated key or an absurd page count means the
            # ASPSP is cycling — stop instead of burning calls forever.
            if continuation_key in seen_keys or pages >= self._MAX_TRANSACTION_PAGES:
                _LOGGER.warning(
                    "Transaction pagination for account %s stopped after %d page(s) "
                    "(%s) — result is incomplete",
                    account_id[:8],
                    pages,
                    "repeated continuation key"
                    if continuation_key in seen_keys
                    else "page limit reached",
                )
                truncated = True
                break
            seen_keys.add(continuation_key)

        return {"booked": booked, "pending": pending, "truncated": truncated}

    @classmethod
    def parse_transaction_page(
        cls, result: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        """Normalise one raw ``/transactions`` page into (booked, pending, key).

        Pure: the raw-archive replay runs archived pages through exactly the
        code a live fetch uses.
        """
        booked: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        raw_transactions, continuation_key = cls._extract_transaction_page(result)
        for raw in raw_transactions:
            if not isinstance(raw, dict):
                continue
            normalized = cls._normalize_transaction(raw)
            (pending if cls._is_pending(raw) else booked).append(normalized)
        return booked, pending, continuation_key

    @classmethod
    def parse_balances(cls, result: Any) -> list[dict[str, Any]]:
        """Normalise one raw ``/balances`` response (pure, see above)."""
        balances = result if isinstance(result, list) else (result or {}).get("balances", [])
        return [cls._normalize_balance(b) for b in balances if isinstance(b, dict)]

    @staticmethod
    def _extract_transaction_page(
        result: Any,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Pull the transaction list and continuation key out of one response.

        Tolerates three shapes: the documented ``{"transactions": [...]}``,
        a bare list, and the legacy ``{"booked": [...], "pending": [...]}``
        buckets some sandboxes still return.
        """
        if isinstance(result, list):
            return (result, None)
        if not isinstance(result, dict):
            return ([], None)

        continuation_key = result.get("continuation_key") or None

        raw = result.get("transactions")
        if isinstance(raw, list):
            return (raw, continuation_key)
        if isinstance(raw, dict):
            # Legacy bucketed shape nested under "transactions".
            return (
                list(raw.get("booked") or []) + list(raw.get("pending") or []),
                continuation_key,
            )
        if "booked" in result or "pending" in result:
            return (
                list(result.get("booked") or []) + list(result.get("pending") or []),
                continuation_key,
            )
        return ([], continuation_key)

    @staticmethod
    def _is_pending(txn: dict[str, Any]) -> bool:
        """Whether a transaction is not yet booked.

        Enable Banking sends ISO 20022 style codes (``BOOK``, ``PDNG``); some
        ASPSPs send the long forms. Anything unrecognised counts as booked,
        because treating a real debit as pending would drop it out of the
        monthly summary entirely.
        """
        status = str(txn.get("status") or txn.get("transaction_status") or "").strip().upper()
        return status in ("PDNG", "PENDING", "INFO", "HELD")

    # ------------------------------------------------------------------
    # Data normalization (Enable Banking → GoCardless field names)
    # ------------------------------------------------------------------

    @classmethod
    def _normalize_transaction(cls, txn: dict[str, Any]) -> dict[str, Any]:
        """Normalize Enable Banking transaction to GoCardless format.

        Enable Banking uses snake_case; downstream consumers expect
        camelCase GoCardless fields.

        Two conversions matter beyond renaming:

        - **The sign.** Enable Banking sends an unsigned magnitude plus
          ``credit_debit_indicator`` (``CRDT``/``DBDT``). Everything downstream
          — income vs. expense, categorization, the household split — keys on
          the sign, so a debit must become negative here. Without this, every
          transaction reads as income and total expenses stay at zero.
        - **The remittance information**, which is an ARRAY of strings. Joining
          it preserves the payment reference that the categorizer and the
          plan-vs-actual matcher search.
        """
        amount_data = txn.get("transaction_amount") or {}
        creditor = txn.get("creditor")
        debtor = txn.get("debtor")

        # ASPSPs send explicit nulls (a pending entry has no booking date);
        # everything downstream sorts and slices these as strings.
        return {
            "transactionId": txn.get("entry_reference") or txn.get("transaction_id") or "",
            "bookingDate": txn.get("booking_date") or "",
            "bookingDateTime": txn.get("booking_date_time") or "",
            "valueDate": txn.get("value_date") or "",
            # PayPal's own lines carry only this one (#107)
            "transactionDate": txn.get("transaction_date") or "",
            "transactionAmount": {
                "amount": cls._signed_amount(amount_data, txn),
                "currency": amount_data.get("currency") or "EUR",
            },
            # Some ASPSPs deliver UTF-8 names decoded as Latin-1 ("S.Ã  r.l.").
            "creditorName": repair_mojibake(
                (creditor.get("name") or "")
                if isinstance(creditor, dict)
                else (txn.get("creditor_name") or "")
            ),
            "debtorName": repair_mojibake(
                (debtor.get("name") or "")
                if isinstance(debtor, dict)
                else (txn.get("debtor_name") or "")
            ),
            # Stored encrypted, masked in every API (own-account check, #171).
            "creditorAccount": {"iban": cls._account_iban(txn.get("creditor_account"))},
            "debtorAccount": {"iban": cls._account_iban(txn.get("debtor_account"))},
            "remittanceInformationUnstructured": cls._join_remittance(txn),
            "status": str(txn.get("status") or "").upper(),
        }

    @staticmethod
    def _account_iban(account: Any) -> str:
        return str(account.get("iban") or "") if isinstance(account, dict) else ""

    @staticmethod
    def _signed_amount(amount_data: dict[str, Any], txn: dict[str, Any]) -> str:
        """Apply the credit/debit indicator to an unsigned amount.

        Returns a decimal string, matching the GoCardless field format that
        downstream code parses with ``float()``.

        When no indicator is present the sign the ASPSP already supplied is
        preserved — some sandboxes send signed amounts and re-deriving the sign
        would flip them.
        """
        raw = amount_data.get("amount", "0")
        try:
            value = float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            return "0.00"

        indicator = str(txn.get("credit_debit_indicator") or "").strip().upper()
        # DBDT is the documented code; DBIT appears in some ASPSP responses.
        if indicator in ("DBIT", "DBDT", "DEBIT"):
            value = -abs(value)
        elif indicator in ("CRDT", "CREDIT"):
            value = abs(value)

        return f"{value:.2f}"

    @staticmethod
    def _join_remittance(txn: dict[str, Any]) -> str:
        """Flatten the remittance information into a single searchable string."""
        raw = txn.get("remittance_information")
        if raw is None:
            raw = txn.get("remittance_information_unstructured", "")
        if isinstance(raw, (list, tuple)):
            return " ".join(str(part).strip() for part in raw if part)
        if isinstance(raw, dict):
            # Structured remittance — keep whatever free text it carries.
            return " ".join(str(v).strip() for v in raw.values() if isinstance(v, str))
        return str(raw or "")

    @staticmethod
    def _normalize_balance(bal: dict[str, Any]) -> dict[str, Any]:
        """Normalize Enable Banking balance to GoCardless format.

        ``balance_type`` is passed through as the ISO 20022 code the API
        actually sends (``CLBD``, ``ITAV``, ...). It is NOT translated to the
        GoCardless camelCase names, because the codes carry information the
        camelCase set does not — consumers pick a balance via
        :data:`BALANCE_TYPE_PRIORITY`.
        """
        amount_data = bal.get("balance_amount") or {}
        return {
            "balanceAmount": {
                "amount": amount_data.get("amount", "0"),
                "currency": amount_data.get("currency", "EUR"),
            },
            "balanceType": str(bal.get("balance_type") or "").upper() or "OTHR",
            "referenceDate": bal.get("reference_date", ""),
        }

    @staticmethod
    def _normalize_institution(aspsp: dict[str, Any]) -> dict[str, Any]:
        """Normalize Enable Banking ASPSP to GoCardless institution format."""
        return {
            "id": aspsp.get("name", ""),
            "name": aspsp.get("name", ""),
            "bic": aspsp.get("bic", ""),
            "logo": aspsp.get("logo", ""),
            "countries": aspsp.get("countries", []),
        }

    # ------------------------------------------------------------------
    # JWT generation & HTTP transport
    # ------------------------------------------------------------------

    def _generate_jwt(self) -> str:
        """Generate a short-lived JWT for API authentication.

        Creates an RS256-signed JWT with 60-second validity using PyJWT.
        Each token includes a unique ``jti`` claim to prevent replay attacks.
        """
        now = int(time.time())
        payload = {
            "iss": self._application_id,
            "aud": "api.tilisy.com",
            "iat": now,
            "exp": now + 60,
            "jti": secrets.token_hex(16),
        }
        # Export the RSA private key in PEM format so PyJWT can use it.
        # The cryptography key object is already loaded in __init__.
        pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return jwt.encode(
            payload,
            pem,
            algorithm="RS256",
            headers={"kid": self._application_id},
        )

    async def _async_request(
        self,
        method: str,
        endpoint: str,
        psu_ip: str | None = None,
        psu_ua: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make an authenticated API request.

        Generates a fresh JWT for every request (60s validity).
        Raises aiohttp.ClientResponseError on HTTP errors.

        Args:
            psu_ip: Optional PSU IP address (from request context).  Sent as
                ``Psu-Ip-Address`` header when provided.  Omitted otherwise —
                never invent a value.
            psu_ua: Optional PSU user-agent string.  Defaults to the
                integration's canonical UA when not explicitly overridden.
                Sent as ``Psu-User-Agent`` for user-triggered live calls only.
        """
        jwt_token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json",
        }
        if psu_ip:
            headers["Psu-Ip-Address"] = psu_ip
        # PSU headers mark a call as attended. A UA without an IP would be a
        # half-attended request, so both go together or not at all.
        if psu_ua and psu_ip:
            headers["Psu-User-Agent"] = psu_ua

        url = f"{ENABLEBANKING_BASE_URL}{endpoint}"
        _LOGGER.debug("Enable Banking request: %s %s", method, url)

        timeout = aiohttp.ClientTimeout(total=30)
        # Lazily create a private session if none was injected.
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=timeout)

        async with self._session.request(
            method, url, headers=headers, timeout=timeout, **kwargs
        ) as resp:
            _LOGGER.debug(
                "Enable Banking response: HTTP %s for %s %s",
                resp.status,
                method,
                url,
            )
            if not resp.ok:
                body = await resp.text()
                # Log only sanitized form at ERROR level to prevent PII
                # (IBANs, account IDs, amounts) reaching the HA log file.
                _LOGGER.error(
                    "Enable Banking API error: HTTP %s %s %s",
                    resp.status,
                    method,
                    endpoint,
                )
                _LOGGER.debug(
                    "Enable Banking error body (sanitized): %s",
                    _sanitize_log(body[:500]),
                )
                # Daily consent quota exhausted — signal callers to
                # stop retrying and serve cached data until tomorrow.
                # Honor the Retry-After header when present so the
                # reset time can be earlier than midnight.
                if resp.status == 429:
                    retry_after_seconds: int | None = None
                    raw_retry = resp.headers.get("Retry-After")
                    if raw_retry:
                        try:
                            retry_after_seconds = int(raw_retry)
                        except (ValueError, TypeError):
                            _LOGGER.debug(
                                "Could not parse Retry-After header: %s",
                                raw_retry,
                            )
                    raise RateLimitExceeded(
                        "Daily API quota exhausted (HTTP 429)",
                        retry_after_seconds,
                    )
                # Include a sanitized excerpt in the exception message
                # so callers can surface a safe error to the user.
                raise aiohttp.ClientResponseError(
                    resp.request_info,
                    resp.history,
                    status=resp.status,
                    message=_sanitize_log(body[:500]),
                )
            return await resp.json()
