"""Config flow for Finance.

Main entry: Enable Banking application id + private key (also reconfigurable).
Banks are config subentries (type ``bank``): the subentry flow picks an ASPSP,
sends the user to the bank via an external step (redirect through
my.home-assistant.io), exchanges the code for a session, runs a test call and
stores the session in the credential store (never in the subentry data).
"""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

try:  # Config subentries need HA >= 2025.2 (hacs.json pins 2026.3)
    from homeassistant.config_entries import (
        ConfigSubentry,
        ConfigSubentryFlow,
        SubentryFlowResult,
    )
except ImportError:  # pragma: no cover - older HA only used for local unit tests

    class ConfigSubentryFlow:  # type: ignore[no-redef]
        """Placeholder so the module imports on HA without subentries."""

    ConfigSubentry = SubentryFlowResult = Any  # type: ignore[assignment,misc]

from .account_identity import dedupe_accounts
from .connect import (
    async_build_client,
    async_complete_session,
    async_credentials,
    async_probe_account_records,
    async_start_authorization,
    get_redirect_url,
    install_callback_bridge,
    map_exception,
)
from .const import (
    CONF_ASPSP_COUNTRY,
    CONF_ASPSP_NAME,
    CONF_SUBENTRY_ACCOUNTS,
    CONF_VALID_UNTIL,
    DEFAULT_RAW_RETENTION_DAYS,
    DEFAULT_SHOW_HOUSEHOLD,
    DOMAIN,
    MAX_RAW_RETENTION_DAYS,
    MIN_RAW_RETENTION_DAYS,
    OPT_RAW_RETENTION_DAYS,
    OPT_SHOW_HOUSEHOLD,
    SUBENTRY_TYPE_BANK,
)
from .credential_manager import CredentialManager

_LOGGER = logging.getLogger(__name__)


def _normalize_pem(raw: str) -> str:
    """Normalize a PEM private key that may have lost newlines.

    Handles:
    - Correct PEM (returned as-is)
    - PEM with all newlines stripped (re-wrapped at 64 chars)
    - PEM with \\n literal strings instead of real newlines
    - Extra whitespace between lines
    """
    if not raw:
        return raw

    # Replace literal \n sequences with real newlines
    normalized = raw.replace("\\n", "\n")

    # If it already has proper PEM structure, return as-is
    if "-----BEGIN" in normalized and "\n" in normalized.split("-----")[2]:
        return normalized.strip()

    # Strip headers/footers and all whitespace to get raw base64
    body = normalized
    for marker in (
        "-----BEGIN PRIVATE KEY-----",
        "-----END PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----END RSA PRIVATE KEY-----",
    ):
        body = body.replace(marker, "")
    body = body.replace("\n", "").replace("\r", "").replace(" ", "")

    if not body:
        return raw

    # Detect header type
    if "RSA PRIVATE KEY" in normalized:
        header = "-----BEGIN RSA PRIVATE KEY-----"
        footer = "-----END RSA PRIVATE KEY-----"
    else:
        header = "-----BEGIN PRIVATE KEY-----"
        footer = "-----END PRIVATE KEY-----"

    # Re-wrap at 64 characters per line (PEM standard)
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    return f"{header}\n" + "\n".join(lines) + f"\n{footer}"


async def _async_validate_credentials(  # noqa: PLR0911
    hass: HomeAssistant, application_id: str, private_key_pem: str
) -> str | None:
    """Validate Enable Banking credentials; return an error key or None.

    Builds the client (PEM check) and fetches the DE catalog once.  The
    catalog is not quota-bound, so this is safe to repeat.
    """
    if not application_id or not private_key_pem:
        return "missing_credentials"
    try:
        from .enablebanking_client import EnableBankingClient

        client = EnableBankingClient(application_id, private_key_pem)
    except (ValueError, TypeError) as exc:
        _LOGGER.error("Failed to load PEM private key: %s", exc)
        return "invalid_key_format"
    except Exception:
        _LOGGER.exception("Unexpected error loading credentials")
        return "invalid_key_format"
    try:
        institutions = await client.async_get_institutions("DE")
    except aiohttp.ClientResponseError as exc:
        _LOGGER.error("Enable Banking API rejected request: HTTP %s", exc.status)
        return "invalid_credentials" if exc.status in (401, 403) else "connection_failed"
    except aiohttp.ClientError as exc:
        _LOGGER.error("Network error contacting Enable Banking: %s", exc)
        return "connection_failed"
    except Exception:
        _LOGGER.exception("Enable Banking connection failed")
        return "invalid_credentials"
    finally:
        close = getattr(client, "async_close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass
    return None if institutions else "no_institutions"


def _credentials_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("application_id"): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required("private_key_pem"): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
            ),
        }
    )


class FinanceDashboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow: Enable Banking credentials; banks are config subentries."""

    VERSION = 3  # v1=GoCardless, v2=Enable Banking full flow, v3=credentials-only

    def _placeholders(self) -> dict[str, str]:
        return {
            "enablebanking_url": "https://enablebanking.com",
            "redirect_url": get_redirect_url(self.hass)
            or "https://my.home-assistant.io/redirect/oauth",
        }

    async def _async_store_credentials(self, application_id: str, pem: str) -> None:
        cred_mgr = CredentialManager(self.hass)
        await cred_mgr.async_initialize()
        await cred_mgr.async_store_api_credentials(application_id, pem)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Collect Enable Banking API credentials and create the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            application_id = user_input["application_id"].strip()
            pem = _normalize_pem(user_input["private_key_pem"].strip())
            error = await _async_validate_credentials(self.hass, application_id, pem)
            if error:
                errors["base"] = error
            else:
                await self._async_store_credentials(application_id, pem)
                return self.async_create_entry(title="Finance", data={"configured": False})

        return self.async_show_form(
            step_id="user",
            data_schema=_credentials_schema(),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the Enable Banking application id / private key."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            application_id = user_input["application_id"].strip()
            pem = _normalize_pem(user_input["private_key_pem"].strip())
            error = await _async_validate_credentials(self.hass, application_id, pem)
            if error:
                errors["base"] = error
            else:
                await self._async_store_credentials(application_id, pem)
                return self.async_update_reload_and_abort(entry, reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """One subentry type: a connected bank."""
        return {SUBENTRY_TYPE_BANK: BankSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> FinanceDashboardOptionsFlow:
        """Get the options flow for this handler."""
        return FinanceDashboardOptionsFlow(config_entry)


class BankSubentryFlow(ConfigSubentryFlow):
    """Connect (or re-authorize) one bank.

    user -> bank -> authorize (external step to the bank) -> finish.
    ``reconfigure`` skips the pickers and re-runs authorize for the stored bank.

    The subentry is added manually (not via ``async_create_entry``) because the
    bank session must be stored under the subentry id BEFORE the entry's update
    listener reloads the integration, and a subentry's id only exists once the
    ``ConfigSubentry`` object is built.  The flow then ends with a translated
    success abort.
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._country: str = "DE"
        self._aspsp_name: str = ""
        self._institutions: list[dict[str, Any]] = []
        self._valid_until: str = ""
        self._code: str = ""
        self._error: str = ""
        self._reconfigure_subentry: Any = None

    # -- helpers ----------------------------------------------------------

    def _placeholders(self) -> dict[str, str]:
        return {
            "redirect_url": get_redirect_url(self.hass)
            or "https://my.home-assistant.io/redirect/oauth"
        }

    async def _async_client(self) -> Any:
        if self._client is None:
            self._client = await async_build_client(self.hass)
        return self._client

    def _store_account_records(self, entry: Any, records: list[dict[str, Any]]) -> None:
        """Merge the linked accounts into the entry's ``accounts`` list.

        The manager fetches from that list; without this a freshly linked
        bank had a subentry but no account to fetch.  Merging by identity
        keeps user-owned fields and entity ids across re-links.
        """
        existing = list((getattr(entry, "data", None) or {}).get("accounts", []))
        merged = dedupe_accounts(existing, records)
        self.hass.config_entries.async_update_entry(
            entry, data={**(getattr(entry, "data", None) or {}), "accounts": merged}
        )

    async def _async_close_client(self) -> None:
        close = getattr(self._client, "async_close", None)
        self._client = None
        if close is not None:
            try:
                await close()
            except Exception:
                pass

    # -- new bank ---------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Pick the country; shows the redirect URL to register."""
        install_callback_bridge(self.hass)
        if user_input is not None:
            self._country = user_input[CONF_ASPSP_COUNTRY].upper()
            try:
                client = await self._async_client()
                # /aspsps is served by Enable Banking, not a bank: not quota-bound.
                self._institutions = await client.async_get_institutions(self._country)
            except Exception as exc:
                return self.async_abort(reason=map_exception(exc).reason)
            if not self._institutions:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._country_schema(),
                    errors={"base": "no_institutions"},
                    description_placeholders=self._placeholders(),
                )
            return await self.async_step_bank()
        return self.async_show_form(
            step_id="user",
            data_schema=self._country_schema(),
            description_placeholders=self._placeholders(),
        )

    def _country_schema(self) -> vol.Schema:
        return vol.Schema({vol.Required(CONF_ASPSP_COUNTRY, default=self._country): str})

    async def async_step_bank(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Pick the bank (ASPSP)."""
        names = sorted({i.get("name", "") for i in self._institutions if i.get("name")})
        if user_input is not None:
            self._aspsp_name = user_input[CONF_ASPSP_NAME]
            entry = self._get_entry()
            unique = _subentry_unique_id(self._country, self._aspsp_name)
            if any(s.unique_id == unique for s in entry.subentries.values()):
                return self.async_abort(reason="already_configured")
            return await self.async_step_authorize()
        return self.async_show_form(
            step_id="bank",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ASPSP_NAME): SelectSelector(
                        SelectSelectorConfig(options=names, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
        )

    # -- re-authorization -------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Re-run the bank authorization for an existing bank."""
        install_callback_bridge(self.hass)
        self._reconfigure_subentry = self._get_reconfigure_subentry()
        self._aspsp_name = self._reconfigure_subentry.data[CONF_ASPSP_NAME]
        self._country = self._reconfigure_subentry.data.get(CONF_ASPSP_COUNTRY, "DE")
        if user_input is not None:
            return await self.async_step_authorize()
        return self.async_show_form(
            step_id="reconfigure",
            description_placeholders={"bank": self._aspsp_name, **self._placeholders()},
        )

    # -- shared authorize / finish ---------------------------------------

    async def async_step_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """External step: send the user to the bank, resume on callback."""
        if user_input is None:
            try:
                client = await self._async_client()
                url, self._valid_until = await async_start_authorization(
                    self.hass, client, self.flow_id, self._aspsp_name, self._country
                )
            except Exception as exc:
                return self.async_abort(reason=map_exception(exc).reason)
            return self.async_external_step(step_id="authorize", url=url)

        # Resumed by the callback view: {"state": {...}, "code"|"error": ...}
        if "code" in user_input:
            self._code = user_input["code"]
        else:
            self._error = "authorization_rejected"
        return self.async_external_step_done(next_step_id="finish")

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create the session, test it, persist the subentry."""
        if self._error or not self._code:
            await self._async_close_client()
            return self.async_abort(reason=self._error or "authorization_rejected")
        try:
            client = await self._async_client()
            session = await async_complete_session(client, self._code)
            accounts, records = await async_probe_account_records(
                client, self._aspsp_name, session["accounts"]
            )
        except Exception as exc:
            return self.async_abort(reason=map_exception(exc).reason)
        finally:
            await self._async_close_client()

        data = {
            CONF_ASPSP_NAME: self._aspsp_name,
            CONF_ASPSP_COUNTRY: self._country,
            CONF_VALID_UNTIL: self._valid_until,
            CONF_SUBENTRY_ACCOUNTS: accounts,
        }
        entry = self._get_entry()
        cred = await async_credentials(self.hass)
        self._store_account_records(entry, records)

        if self._reconfigure_subentry is not None:
            sub = self._reconfigure_subentry
            await cred.async_store_bank_session(
                sub.subentry_id, session["session_id"], self._valid_until
            )
            return self.async_update_and_abort(entry, sub, data=data)

        sub = ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=SUBENTRY_TYPE_BANK,
            title=self._aspsp_name,
            unique_id=_subentry_unique_id(self._country, self._aspsp_name),
        )
        await cred.async_store_bank_session(
            sub.subentry_id, session["session_id"], self._valid_until
        )
        try:
            self.hass.config_entries.async_add_subentry(entry, sub)
        except Exception:
            await cred.async_remove_bank_session(sub.subentry_id)
            raise
        return self.async_abort(reason="bank_connected")


def _subentry_unique_id(country: str, aspsp_name: str) -> str:
    return f"{country.upper()}:{aspsp_name}"


class FinanceDashboardOptionsFlow(OptionsFlow):
    """Handle options for Finance."""

    def __init__(self, config_entry: ConfigEntry | None = None) -> None:
        """Initialize options flow.

        Newer Home Assistant provides ``self.config_entry`` itself and rejects
        assignment, so the argument is only kept as a fallback (and for tests).
        """
        self._entry_override = config_entry

    @property
    def _entry(self) -> ConfigEntry:
        return self._entry_override or self.config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options.

        Deliberately absent: a refresh interval (the bank is never polled; see
        the daily refresh in the panel), the split model (the ``select`` entity
        owns it, the stored option stays its default), currency and the panel
        toggle (nothing read them). Stored values of removed keys are kept.
        """
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._entry.options, **user_input})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "enable_total_balance_sensor",
                        default=self._entry.options.get("enable_total_balance_sensor", False),
                    ): bool,
                    vol.Optional(
                        "demo_mode",
                        default=self._entry.options.get("demo_mode", False),
                    ): bool,
                    vol.Optional(
                        OPT_RAW_RETENTION_DAYS,
                        default=self._entry.options.get(
                            OPT_RAW_RETENTION_DAYS, DEFAULT_RAW_RETENTION_DAYS
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        # 0 keeps raw responses forever (default).
                        vol.Any(
                            0,
                            vol.Range(min=MIN_RAW_RETENTION_DAYS, max=MAX_RAW_RETENTION_DAYS),
                        ),
                    ),
                    vol.Optional(
                        OPT_SHOW_HOUSEHOLD,
                        default=self._entry.options.get(
                            OPT_SHOW_HOUSEHOLD, DEFAULT_SHOW_HOUSEHOLD
                        ),
                    ): bool,
                }
            ),
        )
