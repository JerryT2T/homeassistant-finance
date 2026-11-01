"""Opt-in AI categorisation: provider settings, monthly call budget, merchant cache.

Rules (CLAUDE.md security rule 6, product-concept § AI categorisation):

* opt-in only (``setup_wizard`` state ``ai_opt_in``); nothing is sent otherwise
* provider: Home Assistant's own AI first (``ha``), or an own API key for xAI
  (Grok), Anthropic (Claude) or OpenAI (ChatGPT)
* payload is ONLY merchant + remittance text - never amount, IBAN or date; the
  remittance is scrubbed of IBAN-, date- and long-number-looking text first
* a user-set budget (default ``DEFAULT_CAP``, at most ``HARD_CAP``) of calls per
  calendar month (persisted, resets monthly);
  an attempt counts, a failed call is not retried
* results are cached per merchant permanently
* the API key is Fernet-encrypted (credential manager) in its own Store and is
  never logged or returned by any endpoint
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}.ai_provider"
STORAGE_VERSION = 1
HARD_CAP = 1000  # user-settable monthly budget, at most this many calls
DEFAULT_CAP = 100
REQUEST_TIMEOUT = 20
MAX_REMITTANCE = 140
MAX_MERCHANT = 80
MAX_CACHE = 5000
DEFAULT_MAX_TOKENS = 20

PROVIDER_HA = "ha"
# provider -> (endpoint, default model). The default models are cheap, current
# aliases of each vendor and stay user-configurable.
PROVIDERS: dict[str, tuple[str, str]] = {
    PROVIDER_HA: ("", ""),
    "xai": ("https://api.x.ai/v1/chat/completions", "grok-4-fast"),
    "anthropic": ("https://api.anthropic.com/v1/messages", "claude-haiku-4-5"),
    "openai": ("https://api.openai.com/v1/chat/completions", "gpt-5-mini"),
}
KEYED = ("xai", "anthropic", "openai")

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{3,4}){3,8}\b", re.I)
_DATE = re.compile(r"\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\b")
_LONG_NUM = re.compile(r"\d[\d.,\s]{4,}\d")
_AMOUNT = re.compile(r"[-+]?\d+[.,]\d{2}\s?(?:eur|€)?", re.I)


class AiError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


def default_config() -> dict[str, Any]:
    return {
        "provider": PROVIDER_HA,
        "model": "",
        "ha_agent": "",
        "budget_cap": DEFAULT_CAP,
        "key_enc": "",
        "usage": {"month": "", "calls": 0},
        "cache": {},
        "last_run": None,
        "last_test": None,
    }


def month_key(today: date) -> str:
    return f"{today.year}-{today.month:02d}"


def sanitize(text: str, limit: int) -> str:
    """Strip IBANs, dates, amounts and long numbers; collapse whitespace; truncate."""
    for pattern in (_IBAN, _DATE, _AMOUNT, _LONG_NUM):
        text = pattern.sub(" ", text)
    return " ".join(text.split())[:limit]


def build_payload(merchant: str, remittance: str) -> dict[str, str]:
    """The ONLY data that ever leaves the system."""
    return {
        "merchant": sanitize(merchant, MAX_MERCHANT),
        "remittance": sanitize(remittance, MAX_REMITTANCE),
    }


def build_prompt(payload: dict[str, str], categories: list[str]) -> str:
    return (
        "Classify a bank-statement merchant into exactly one category. "
        f"Allowed categories: {', '.join(categories)}. "
        "Answer with the category slug only.\n"
        f"Merchant: {payload['merchant']}\nPurpose: {payload['remittance']}"
    )


def parse_category(text: str, categories: list[str]) -> str | None:
    """First allowed category slug found in the model answer."""
    answer = (text or "").strip().lower()
    for cat in categories:
        if re.search(rf"(?<![a-z_]){re.escape(cat)}(?![a-z_])", answer):
            return cat
    return None


# ---------------------------------------------------------------------------
# Config + budget (pure)
# ---------------------------------------------------------------------------


def merge_config(raw: Any) -> dict[str, Any]:
    cfg = default_config()
    if not isinstance(raw, dict):
        return cfg
    if raw.get("provider") in PROVIDERS:
        cfg["provider"] = raw["provider"]
    cfg["model"] = str(raw.get("model") or "")[:80]
    cfg["ha_agent"] = str(raw.get("ha_agent") or "")[:120]
    cap = raw.get("budget_cap")
    if isinstance(cap, int) and not isinstance(cap, bool) and 0 <= cap <= HARD_CAP:
        cfg["budget_cap"] = cap
    cfg["key_enc"] = str(raw.get("key_enc") or "")
    usage = raw.get("usage")
    if isinstance(usage, dict):
        cfg["usage"] = {
            "month": str(usage.get("month") or ""),
            "calls": max(0, int(usage.get("calls") or 0)),
        }
    cache = raw.get("cache")
    cfg["cache"] = {str(k): str(v) for k, v in cache.items()} if isinstance(cache, dict) else {}
    for key in ("last_run", "last_test"):
        cfg[key] = _merge_outcome(raw.get(key))
    return cfg


def _merge_outcome(raw: Any) -> dict[str, Any] | None:
    """A stored call outcome: when, whether it worked, the category or an error code."""
    if not isinstance(raw, dict) or not raw.get("at"):
        return None
    return {
        "at": str(raw["at"]),
        "ok": bool(raw.get("ok")),
        "category": str(raw.get("category") or "") or None,
        "error": str(raw.get("error") or "") or None,
    }


def outcome(at: str, category: str | None, error: str | None) -> dict[str, Any]:
    return {"at": at, "ok": bool(category), "category": category, "error": error}


def results_view(cfg: dict[str, Any], recent: int = 8) -> dict[str, Any]:
    """What the AI has learned so far: merchants per category and the latest ones."""
    by_category: dict[str, int] = {}
    for category in cfg["cache"].values():
        by_category[category] = by_category.get(category, 0) + 1
    latest = list(cfg["cache"].items())[-recent:][::-1]
    return {
        "by_category": dict(sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))),
        "recent": [{"merchant": m, "category": c} for m, c in latest],
    }


def usage_view(cfg: dict[str, Any], today: date) -> dict[str, Any]:
    """Calls this month, the cap and what is left (rolls over on a new month)."""
    month = month_key(today)
    used = cfg["usage"]["calls"] if cfg["usage"]["month"] == month else 0
    cap = min(int(cfg["budget_cap"]), HARD_CAP)
    return {
        "month": month,
        "calls": used,
        "cap": cap,
        "hard_cap": HARD_CAP,
        "remaining": max(0, cap - used),
    }


def spend_call(cfg: dict[str, Any], today: date) -> bool:
    """Reserve one call; False when the monthly cap is reached."""
    view = usage_view(cfg, today)
    if view["remaining"] <= 0:
        return False
    cfg["usage"] = {"month": view["month"], "calls": view["calls"] + 1}
    return True


def validate_update(body: dict[str, Any]) -> dict[str, Any]:
    """Validate the PUT body; returns only the keys to change. Raises :class:`AiError`."""
    out: dict[str, Any] = {}
    if "provider" in body:
        if body["provider"] not in PROVIDERS:
            raise AiError("invalid_provider", "provider must be ha, xai, anthropic or openai")
        out["provider"] = body["provider"]
    for key, limit in (("model", 80), ("ha_agent", 120)):
        if key in body:
            if not isinstance(body[key], str) or len(body[key]) > limit:
                raise AiError(f"invalid_{key}", f"{key} must be a short string")
            out[key] = body[key].strip()
    if "budget_cap" in body:
        cap = body["budget_cap"]
        if isinstance(cap, bool) or not isinstance(cap, int) or not 0 <= cap <= HARD_CAP:
            raise AiError("invalid_budget_cap", f"budget_cap must be an integer 0-{HARD_CAP}")
        out["budget_cap"] = cap
    if "api_key" in body:
        key = body["api_key"]
        if not isinstance(key, str) or len(key) > 400 or any(c.isspace() for c in key.strip()):
            raise AiError("invalid_api_key", "api_key must be a string without whitespace")
        out["api_key"] = key.strip()
    return out


# ---------------------------------------------------------------------------
# Persistence + key
# ---------------------------------------------------------------------------


def _store(hass: HomeAssistant) -> Store:
    data = hass.data.setdefault(DOMAIN, {})
    store = data.get("_ai_provider_store")
    if store is None:
        store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        data["_ai_provider_store"] = store
    return store


async def async_load_config(hass: HomeAssistant) -> dict[str, Any]:
    try:
        raw = await _store(hass).async_load()
    except Exception:  # noqa: BLE001 - a broken file must not block setup
        raw = None
    return merge_config(raw)


async def async_save_config(hass: HomeAssistant, cfg: dict[str, Any]) -> None:
    await _store(hass).async_save(cfg)


def apply_update(cfg: dict[str, Any], changes: dict[str, Any], credentials: Any) -> dict[str, Any]:
    """New config with ``changes`` applied; the key is encrypted, never kept plain."""
    new = merge_config(cfg)
    for key in ("provider", "model", "ha_agent", "budget_cap"):
        if key in changes:
            new[key] = changes[key]
    if "api_key" in changes:
        key = changes["api_key"]
        if key and credentials is None:
            raise AiError("unavailable", "Credential store not ready")
        new["key_enc"] = credentials.encrypt_json({"k": key}) if key else ""
    return new


def read_key(cfg: dict[str, Any], credentials: Any) -> str | None:
    if not cfg["key_enc"] or credentials is None:
        return None
    try:
        return str(credentials.decrypt_json(cfg["key_enc"]).get("k") or "") or None
    except Exception:  # noqa: BLE001 - lost key / damaged token
        _LOGGER.warning("Stored AI key could not be decrypted")
        return None


def public_view(cfg: dict[str, Any], today: date, opt_in: bool) -> dict[str, Any]:
    """What GET returns - the key itself is never part of it."""
    provider = cfg["provider"]
    return {
        "opt_in": opt_in,
        "provider": provider,
        "model": cfg["model"],
        "effective_model": cfg["model"] or PROVIDERS[provider][1],
        "ha_agent": cfg["ha_agent"],
        "has_key": bool(cfg["key_enc"]),
        "budget": usage_view(cfg, today),
        "cached_merchants": len(cfg["cache"]),
        "last_run": cfg["last_run"],
        "last_test": cfg["last_test"],
        "results": results_view(cfg),
        "providers": [
            {
                "id": p,
                "needs_key": p in KEYED,
                "default_model": m,
                "host": endpoint.split("/")[2] if endpoint else "",
            }
            for p, (endpoint, m) in PROVIDERS.items()
        ],
    }


# ---------------------------------------------------------------------------
# Candidate selection + usability (pure)
# ---------------------------------------------------------------------------

NEVER_AI = ("other", "income", "transfers")


def provider_usable(
    cfg: dict[str, Any], *, has_key: bool, has_ai_task: bool, has_conversation: bool
) -> bool:
    """A provider is usable when HA has a configured agent, or an own key is stored."""
    if cfg["provider"] in KEYED:
        return has_key
    if has_ai_task:  # AI Task falls back to the agent chosen in HA's AI settings
        return True
    return has_conversation and bool(cfg["ha_agent"])


def select_candidates(
    transactions: list[dict[str, Any]],
    *,
    key_of: Any,
    counterparty_of: Any,
    own_names: Any,
    is_own: Any,
    skip: set[str] | frozenset[str],
    has_rule: Any = None,
) -> list[dict[str, Any]]:
    """Merchants worth asking the AI about, highest euro impact first.

    Only booked expenses still in ``other`` outside transfer chains and not
    paid to the household itself; ``skip`` = AI cache + merchants already tried.
    Each result carries ``id``, ``merchant`` and ``remittance`` (what the
    payload may contain) plus the internal ``total`` used for the ordering.
    """
    groups: dict[str, dict[str, Any]] = {}
    for tx in transactions:
        if tx.get("category") != "other" or tx.get("_transfer_chain_id"):
            continue
        try:
            amount = float((tx.get("transactionAmount") or {}).get("amount", 0) or 0)
        except (TypeError, ValueError):
            continue
        if amount >= 0:
            continue
        key = key_of(tx)
        if not key or key in skip or (has_rule and has_rule(key)):
            continue
        name = counterparty_of(tx)
        if is_own(name.lower(), own_names):
            continue
        g = groups.setdefault(
            key, {"id": key, "merchant": name or key, "remittance": "", "total": 0.0}
        )
        g["total"] += abs(amount)
        if not g["remittance"]:
            g["remittance"] = str(tx.get("remittanceInformationUnstructured") or "")
    return sorted(groups.values(), key=lambda g: (-g["total"], g["id"]))


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------


async def _call_http(
    hass: HomeAssistant,
    provider: str,
    model: str,
    key: str,
    prompt: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str | None:
    endpoint = PROVIDERS[provider][0]
    session = async_get_clientsession(hass)
    if provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    else:  # OpenAI-compatible (xAI, OpenAI)
        headers = {"Authorization": f"Bearer {key}"}
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
    async with session.post(endpoint, json=body, headers=headers, timeout=REQUEST_TIMEOUT) as resp:
        if resp.status != 200:  # noqa: PLR2004
            _LOGGER.warning("AI provider %s answered HTTP %s", provider, resp.status)
            return None
        data = await resp.json()
    if provider == "anthropic":
        return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))
    return str(data["choices"][0]["message"]["content"])


async def _call_ha(hass: HomeAssistant, agent: str, prompt: str) -> str | None:
    """HA's own AI: AI Task when available, else a conversation agent."""
    if hass.services.has_service("ai_task", "generate_data"):
        data: dict[str, Any] = {"task_name": "finance_categorize", "instructions": prompt}
        if agent:
            data["entity_id"] = agent
        res = await hass.services.async_call(
            "ai_task", "generate_data", data, blocking=True, return_response=True
        )
        return str((res or {}).get("data") or "") or None
    if hass.services.has_service("conversation", "process"):
        data = {"text": prompt}
        if agent:
            data["agent_id"] = agent
        res = await hass.services.async_call(
            "conversation", "process", data, blocking=True, return_response=True
        )
        speech = ((res or {}).get("response") or {}).get("speech") or {}
        return str((speech.get("plain") or {}).get("speech") or "") or None
    return None


async def async_categorize(
    hass: HomeAssistant,
    *,
    credentials: Any,
    opt_in: bool,
    merchant_id: str,
    merchant: str,
    remittance: str,
    categories: list[str],
    today: date,
) -> str | None:
    """Category for a merchant, or None (no opt-in, cap reached, error, no match)."""
    if not opt_in or not categories:
        return None
    cfg = await async_load_config(hass)
    cached = cfg["cache"].get(merchant_id)
    if cached:
        return cached
    provider = cfg["provider"]
    key = None
    if provider in KEYED:
        key = read_key(cfg, credentials)
        if not key:
            return None
    if not spend_call(cfg, today):
        return None
    await async_save_config(hass, cfg)  # persist the spend before the call
    prompt = build_prompt(build_payload(merchant, remittance), categories)
    category, error = await _ask(hass, cfg, key, prompt, categories)
    cfg["last_run"] = outcome(dt_util.utcnow().isoformat(), category, error)
    if category and len(cfg["cache"]) < MAX_CACHE:
        cfg["cache"][merchant_id] = category
    await async_save_config(hass, cfg)
    return category


async def _ask(
    hass: HomeAssistant, cfg: dict[str, Any], key: str | None, prompt: str, categories: list[str]
) -> tuple[str | None, str | None]:
    """One provider call: (category, None) or (None, error code). Never raises."""
    answer, error = await _ask_raw(hass, cfg, key, prompt)
    if error:
        return None, error
    category = parse_category(answer or "", categories)
    return (category, None) if category else (None, "unparsable")


async def _ask_raw(
    hass: HomeAssistant,
    cfg: dict[str, Any],
    key: str | None,
    prompt: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[str | None, str | None]:
    """One provider call: (answer text, None) or (None, error code). Never raises."""
    provider = cfg["provider"]
    try:
        if provider == PROVIDER_HA:
            answer = await _call_ha(hass, cfg["ha_agent"], prompt)
        else:
            model = cfg["model"] or PROVIDERS[provider][1]
            extra = (max_tokens,) if max_tokens != DEFAULT_MAX_TOKENS else ()
            answer = await _call_http(hass, provider, model, key or "", prompt, *extra)
    except TimeoutError:
        return None, "timeout"
    except Exception as err:  # noqa: BLE001 - never leak provider text or the key
        _LOGGER.warning("AI request failed (%s)", type(err).__name__)
        return None, "request_failed"
    return (answer, None) if answer else (None, "no_answer")


# A made-up merchant: the connection test never sends real bank data.
TEST_MERCHANT = ("REWE Markt", "Einkauf Lebensmittel")


async def async_test(  # noqa: PLR0913 - keyword-only call context
    hass: HomeAssistant,
    *,
    credentials: Any,
    opt_in: bool,
    categories: list[str],
    today: date,
    usable: bool,
) -> dict[str, Any]:
    """Classify :data:`TEST_MERCHANT` once and store the outcome as ``last_test``.

    Counts against the monthly cap like any call; the answer is not cached.
    """
    cfg = await async_load_config(hass)
    key = read_key(cfg, credentials) if cfg["provider"] in KEYED else None
    if not opt_in:
        category, error = None, "not_opted_in"
    elif cfg["provider"] in KEYED and not key:
        category, error = None, "no_key"
    elif not usable:
        category, error = None, "no_provider"
    elif not spend_call(cfg, today):
        category, error = None, "budget_exhausted"
    else:
        await async_save_config(hass, cfg)
        prompt = build_prompt(build_payload(*TEST_MERCHANT), categories)
        category, error = await _ask(hass, cfg, key, prompt, categories)
        # A categorisation pass may have saved while we waited - do not overwrite it.
        cfg = await async_load_config(hass)
    cfg["last_test"] = outcome(dt_util.utcnow().isoformat(), category, error)
    await async_save_config(hass, cfg)
    return cfg["last_test"]


# ---------------------------------------------------------------------------
# Budget-sheet position names (purpose "sheet_analysis")
# ---------------------------------------------------------------------------

POSITION_KINDS = ("fixed", "pot", "reserve")
MAX_NAMES = 40
MAX_NAME = 60


def build_names_prompt(names: list[str]) -> str:
    """Prompt for position NAMES only - no amounts, no bank data."""
    listing = "\n".join(f"{i}: {n}" for i, n in enumerate(names, 1))
    return (
        "Classify household budget positions by name. For each numbered name answer one "
        "line 'number: kind' where kind is fixed (recurring contract or fixed bill), "
        "pot (variable spending such as groceries or leisure) or reserve (saving for "
        "irregular or yearly costs).\n" + listing
    )


def parse_kinds(text: str, count: int) -> dict[int, str]:
    """``{index (1-based): kind}`` from the model answer; unknown lines are skipped."""
    out: dict[int, str] = {}
    for m in re.finditer(r"(\d+)\s*[:.)-]\s*(fixed|pot|reserve)\b", (text or "").lower()):
        idx = int(m.group(1))
        if 1 <= idx <= count:
            out[idx] = m.group(2)
    return out


async def async_classify_names(
    hass: HomeAssistant, *, credentials: Any, names: list[str], today: date, usable: bool
) -> dict[str, str] | None:
    """Kind per position name via the configured provider, or None (not usable,
    no key, budget exhausted, error). One call for the whole batch; the payload is
    the (sanitised) names only. Counts as one call against the monthly budget."""
    names = names[:MAX_NAMES]
    clean = [sanitize(n, MAX_NAME) for n in names]
    if not clean or not usable:
        return None
    cfg = await async_load_config(hass)
    key = None
    if cfg["provider"] in KEYED:
        key = read_key(cfg, credentials)
        if not key:
            return None
    if not spend_call(cfg, today):
        return None
    await async_save_config(hass, cfg)  # persist the spend before the call
    answer, error = await _ask_raw(hass, cfg, key, build_names_prompt(clean), 400)
    if error:
        return None
    kinds = parse_kinds(answer or "", len(clean))
    return {names[i - 1]: kind for i, kind in kinds.items()}
