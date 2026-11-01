"""Number platform — budget limit entities per category.

Creates one Number entity per spending category, allowing users
to set budget limits directly from their HA dashboard.
When spending exceeds the limit, an fd_budget_exceeded event fires.
"""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEFAULT_CATEGORIES, DOMAIN
from .entity import main_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

CATEGORY_ICONS = {
    "housing_cold": "mdi:home",
    "housing_warm": "mdi:radiator",
    "groceries": "mdi:cart",
    "mobility": "mdi:car",
    "health": "mdi:heart-pulse",
    "leisure": "mdi:party-popper",
    "media": "mdi:cellphone-wireless",
    "finance": "mdi:bank",
    "other": "mdi:dots-horizontal",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up budget limit number entities."""
    entities = []
    for category in DEFAULT_CATEGORIES:
        entities.append(BudgetLimitNumber(entry, category))

    async_add_entities(entities, update_before_add=True)


class BudgetLimitNumber(NumberEntity, RestoreEntity):
    """Number entity for a category budget limit.

    Inherits from RestoreEntity so user-set limits survive HA restarts —
    without this the limits silently reset to 0 on every reload, which
    is data loss from the user's point of view.
    """

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 10000
    _attr_native_step = 10
    _attr_native_unit_of_measurement = "EUR"
    _attr_has_entity_name = True
    _attr_translation_key = "budget_limit"

    def __init__(self, entry: ConfigEntry, category: str) -> None:
        """Initialize budget limit number."""
        self._entry = entry
        self._category = category
        self._attr_unique_id = f"{DOMAIN}_budget_{category}"
        self._attr_translation_placeholders = {"category": category.replace("_", " ").title()}
        self._attr_device_info = main_device_info(entry)
        self._attr_icon = CATEGORY_ICONS.get(category, "mdi:cash")
        # Default value: 0 = no limit set. Overridden from restored
        # state in async_added_to_hass() if the entity has been seen
        # before.
        self._attr_native_value = 0.0

    async def async_added_to_hass(self) -> None:
        """Restore the previously set budget limit, if any."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in (None, "unknown", "unavailable"):
            return
        try:
            self._attr_native_value = float(last_state.state)
            _LOGGER.debug(
                "Restored budget limit for %s: %.2f EUR",
                self._category,
                self._attr_native_value,
            )
        except (TypeError, ValueError):
            _LOGGER.debug(
                "Could not parse restored budget limit for %s: %r",
                self._category,
                last_state.state,
            )

    async def async_set_native_value(self, value: float) -> None:
        """Update the budget limit."""
        self._attr_native_value = value
        self.async_write_ha_state()
        _LOGGER.debug(
            "Budget limit for %s set to %.2f EUR",
            self._category,
            value,
        )
