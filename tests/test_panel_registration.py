"""Frontend delivery: panel_custom registration, cache-busting, idempotency."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.finance_dashboard import panel
from custom_components.finance_dashboard.const import (
    CARDS_MODULE_PATH,
    DOMAIN,
    FRONTEND_URL_BASE,
    PANEL_COMPONENT_NAME,
    PANEL_MODULE_PATH,
    PANEL_URL_PATH,
    VERSION,
)

FRONTEND_DIR = Path(panel.__file__).parent / "frontend"


def _hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()
    return hass


def test_urls_are_versioned_and_inside_static_mount() -> None:
    for url in (PANEL_MODULE_PATH, CARDS_MODULE_PATH):
        assert url.startswith(FRONTEND_URL_BASE + "/")
        assert url.endswith(f"?v={VERSION}")
        assert (FRONTEND_DIR / url.split("/")[-1].split("?")[0]).is_file()


async def test_register_panel_open_to_members_with_cache_busting() -> None:
    hass = _hass()
    with (
        patch.object(panel.panel_custom, "async_register_panel", new=AsyncMock()) as reg,
        patch.object(panel.frontend, "add_extra_js_url") as add_js,
    ):
        await panel.async_register_panel(hass)

    hass.http.async_register_static_paths.assert_awaited_once()
    (cfg,) = hass.http.async_register_static_paths.await_args.args[0]
    assert cfg.url_path == FRONTEND_URL_BASE
    assert Path(cfg.path) == FRONTEND_DIR
    assert cfg.cache_headers is True

    add_js.assert_called_once_with(hass, CARDS_MODULE_PATH)
    kwargs = reg.await_args.kwargs
    assert kwargs["require_admin"] is False  # members open it; endpoints gate themselves
    assert kwargs["config_panel_domain"] == DOMAIN
    assert kwargs["frontend_url_path"] == PANEL_URL_PATH
    assert kwargs["webcomponent_name"] == PANEL_COMPONENT_NAME
    assert kwargs["module_url"] == PANEL_MODULE_PATH


async def test_register_is_idempotent_across_reloads() -> None:
    hass = _hass()
    with (
        patch.object(panel.panel_custom, "async_register_panel", new=AsyncMock()) as reg,
        patch.object(panel.frontend, "add_extra_js_url"),
    ):
        await panel.async_register_panel(hass)
        # HA now knows the panel; a reload must not re-register it or the mount.
        hass.data["frontend_panels"] = {PANEL_URL_PATH: object()}
        await panel.async_register_panel(hass)

    assert reg.await_count == 1
    assert hass.http.async_register_static_paths.await_count == 1


async def test_unregister_removes_panel_and_card_module() -> None:
    hass = _hass()
    hass.data["frontend_panels"] = {PANEL_URL_PATH: object()}
    with (
        patch.object(panel.frontend, "async_remove_panel") as rm,
        patch.object(panel.frontend, "remove_extra_js_url") as rm_js,
    ):
        await panel.async_unregister_panel(hass)
    rm.assert_called_once_with(hass, PANEL_URL_PATH)
    rm_js.assert_called_once_with(hass, CARDS_MODULE_PATH)


async def test_unregister_without_registration_is_silent() -> None:
    hass = _hass()
    with patch.object(panel.frontend, "remove_extra_js_url", side_effect=KeyError):
        await panel.async_unregister_panel(hass)


def test_no_third_party_panel_dependency() -> None:
    root = Path(panel.__file__).parent
    assert "ha-customapps" not in (root / "manifest.json").read_text()
    for py in root.rglob("*.py"):
        assert "ha_customapps" not in py.read_text(encoding="utf-8"), py


def test_every_card_is_guarded_and_sized() -> None:
    """Cards define once, register in the picker and support the sections grid."""
    cards = ["finance-dashboard-card.js", "finance-status-chip.js", "fd-budget-config.js", "fd-categorize.js"]
    for name in cards:
        src = (FRONTEND_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"^customElements\.define", src, re.M), name
        assert "registerCard(" in src, name
        for hook in ("getCardSize", "getGridOptions", "getStubConfig"):
            assert hook in src, f"{name} lacks {hook}"
    kit = (FRONTEND_DIR / "finance-dashboard-kit.js").read_text(encoding="utf-8")
    for name in cards:
        assert name in kit


@pytest.mark.parametrize("js", sorted(p.name for p in FRONTEND_DIR.glob("*.js")))
def test_kit_references_only_existing_files(js: str) -> None:
    if js != "finance-dashboard-kit.js":
        return
    src = (FRONTEND_DIR / js).read_text(encoding="utf-8")
    for ref in re.findall(r'"((?:fd|finance)-[\w-]+\.js)"', src):
        assert (FRONTEND_DIR / ref).is_file(), ref


def test_cycle_disclosure_does_not_share_the_show_more_button_class() -> None:
    """The .more button is display:flex, which would lay an open disclosure out side by side."""
    src = (FRONTEND_DIR / "fd-home.js").read_text(encoding="utf-8")
    assert '<details class="moreset" id="more"' in src
    assert '<details class="more"' not in src
    assert ".moreset > summary" in src
    assert ".more > summary" not in src
