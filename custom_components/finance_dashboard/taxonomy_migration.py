"""One-time migration of stored category slugs to the life areas (#112).

Runs at setup before any store is loaded by its owner. Each store that holds a
category is copied to a backup key first, then rewritten with
``life_areas.migrate_slug``; a marker store records that it ran, so it runs
once. A store that cannot be read is left as it is (and stays readable: the
UI shows a legacy slug with a fallback label) - the migration never blocks
startup.

Text used for the keyword splits is what the value belongs to: the merchant
key for learned merchants and the AI cache, the position name for plan
positions. One-off booking answers and contract overrides have no text of
their own: they take the area a legacy slug lands in without one; a contract
override that would become ``other`` is cleared so the contract follows
detection again.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STORAGE_KEY_BUDGET_PLAN, STORAGE_KEY_POTS, STORAGE_VERSION
from .life_areas import LEGACY_SLUGS, OTHER, migrate_slug, migrate_targets

_LOGGER = logging.getLogger(__name__)

TAXONOMY_VERSION = 2
STORAGE_KEY_TAXONOMY = f"{DOMAIN}_taxonomy"
BACKUP_SUFFIX = "_backup_taxonomy_v1"

# Owners of these keys import nothing from here; the names are fixed strings
# in their modules (merchants.py, ai_provider.py, contracts.py).
STORAGE_KEY_MERCHANTS = f"{DOMAIN}_merchants"
STORAGE_KEY_AI = f"{DOMAIN}.ai_provider"
STORAGE_KEY_CONTRACTS = f"{DOMAIN}_contracts"
STORAGE_KEY_GOALS = f"{DOMAIN}.savings_goals"

# Budget-limit number entities: old unique-id slug -> new one. A slug without
# a target (income, transfers) loses its entity; limits for them never made sense.
NUMBER_RENAMES: dict[str, str | None] = {
    "housing": "housing_cold",
    "utilities": "housing_warm",
    "food": "groceries",
    "transport": "mobility",
    "insurance": "health",
    "subscriptions": "media",
    "loans": "finance",
    "income": None,
    "transfers": None,
}


def _rule_slug(rule: Any, text: str) -> bool:
    """Rewrite ``rule["category"]`` in place; True when it changed."""
    if not isinstance(rule, dict):
        return False
    old = rule.get("category")
    new = migrate_slug(old, text) if isinstance(old, str) else old
    if new != old:
        rule["category"] = new
        return True
    return False


def migrate_merchants(data: dict[str, Any]) -> bool:
    changed = False
    for key, rule in (data.get("merchants") or {}).items():
        changed |= _rule_slug(rule, str(key))
    for rule in (data.get("bookings") or {}).values():
        changed |= _rule_slug(rule, "")
    return changed


def migrate_ai(data: dict[str, Any]) -> bool:
    changed = False
    cache = data.get("cache")
    if isinstance(cache, dict):
        for key, slug in list(cache.items()):
            new = migrate_slug(slug, str(key)) if isinstance(slug, str) else slug
            if new != slug:
                cache[key] = new
                changed = True
    for field in ("last_run", "last_test"):
        changed |= _rule_slug(data.get(field), "")
    return changed


def migrate_plan(data: dict[str, Any]) -> bool:
    changed = False
    for pos in data.get("positions") or []:
        if isinstance(pos, dict):
            changed |= _rule_slug(pos, str(pos.get("name") or ""))
    return changed


def migrate_pots(data: dict[str, Any]) -> bool:
    changed = False
    for pot in data.get("pots") or []:
        keys = pot.get("category_keys") if isinstance(pot, dict) else None
        if not isinstance(keys, list) or not any(k in LEGACY_SLUGS for k in keys):
            continue
        new: list[str] = []
        for k in keys:
            for area in migrate_targets(k) if isinstance(k, str) else (k,):
                if area not in new:
                    new.append(area)
        pot["category_keys"] = new
        changed = True
    return changed


def migrate_contracts(data: dict[str, Any]) -> bool:
    changed = False
    for item in (data.get("contracts") or {}).values():
        if not isinstance(item, dict) or item.get("category") not in LEGACY_SLUGS:
            continue
        new = migrate_slug(item["category"], "")
        item["category"] = None if new == OTHER else new
        changed = True
    return changed


def migrate_goals(data: dict[str, Any]) -> bool:
    changed = False
    for goal in data.get("goals") or []:
        if isinstance(goal, dict) and goal.get("kind") == "category_cap":
            changed |= _rule_slug(goal, str(goal.get("name") or ""))
    return changed


_STORES = (
    (STORAGE_KEY_MERCHANTS, migrate_merchants),
    (STORAGE_KEY_AI, migrate_ai),
    (STORAGE_KEY_BUDGET_PLAN, migrate_plan),
    (STORAGE_KEY_POTS, migrate_pots),
    (STORAGE_KEY_CONTRACTS, migrate_contracts),
    (STORAGE_KEY_GOALS, migrate_goals),
)


async def _migrate_store(hass: HomeAssistant, key: str, fn: Any) -> bool:
    """Back up and rewrite one store. False when it could not be read."""
    store: Store = Store(hass, STORAGE_VERSION, key)
    try:
        data = await store.async_load()
    except Exception:  # noqa: BLE001 - a broken store must not block setup
        _LOGGER.warning("Category migration: store %s unreadable, left as it is", key)
        return False
    if not isinstance(data, dict):
        return True
    migrated = copy.deepcopy(data)
    if not fn(migrated):
        return True
    await Store(hass, STORAGE_VERSION, key + BACKUP_SUFFIX).async_save(data)
    await store.async_save(migrated)
    return True


def migrate_number_entities(hass: HomeAssistant, entry_id: str) -> None:
    """Move budget-limit number entities to the new slugs; drop the rest."""
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry_id):
        if entity.domain != "number":
            continue
        prefix = f"{DOMAIN}_budget_"
        if not entity.unique_id.startswith(prefix):
            continue
        slug = entity.unique_id[len(prefix):]
        if slug not in NUMBER_RENAMES:
            continue
        target = NUMBER_RENAMES[slug]
        new_id = f"{prefix}{target}" if target else None
        if new_id and registry.async_get_entity_id("number", DOMAIN, new_id) is None:
            registry.async_update_entity(entity.entity_id, new_unique_id=new_id)
        else:
            registry.async_remove(entity.entity_id)


async def async_migrate_taxonomy(hass: HomeAssistant, entry_id: str | None = None) -> bool:
    """Run the migration once; True when it ran in this call."""
    marker: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY_TAXONOMY)
    try:
        state = await marker.async_load()
    except Exception:  # noqa: BLE001
        state = None
    if isinstance(state, dict) and int(state.get("version") or 0) >= TAXONOMY_VERSION:
        return False
    complete = True
    for key, fn in _STORES:
        complete &= await _migrate_store(hass, key, fn)
    if entry_id:
        try:
            migrate_number_entities(hass, entry_id)
        except Exception:  # noqa: BLE001 - entities are recreated with the new ids anyway
            _LOGGER.warning("Category migration: number entities not moved", exc_info=True)
    if complete:
        await marker.async_save(
            {"version": TAXONOMY_VERSION, "migrated_at": dt_util.utcnow().isoformat()}
        )
    return True
