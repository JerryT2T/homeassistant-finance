"""CSV export for transaction data.

Generates a CSV file in HA's config directory for local download.
Admin-only. File is ephemeral — auto-cleaned after 1 hour.

SECURITY: CSV files are written to a temporary location inside
the HA config directory. They are never committed to git and
auto-delete after a short TTL.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .tx_dates import effective_date_str

_LOGGER = logging.getLogger(__name__)

EXPORT_DIR_NAME = f"{DOMAIN}_exports"
EXPORT_TTL_HOURS = 1


async def async_export_csv(
    hass: HomeAssistant,
    transactions: list[dict[str, Any]],
    date_from: str | None = None,
    date_to: str | None = None,
    categories: list[str] | None = None,
) -> str:
    """Export transactions as CSV file.

    Args:
        hass: Home Assistant instance
        transactions: List of transaction dicts
        date_from: Optional start date filter (YYYY-MM-DD)
        date_to: Optional end date filter (YYYY-MM-DD)
        categories: Optional category filter list

    Returns:
        Path to the generated CSV file
    """
    # Filter transactions
    filtered = transactions
    if date_from:
        filtered = [t for t in filtered if effective_date_str(t) >= date_from]
    if date_to:
        filtered = [t for t in filtered if effective_date_str(t) <= date_to]
    if categories:
        filtered = [t for t in filtered if t.get("category", "other") in categories]

    # Create export directory
    export_dir = Path(hass.config.path(EXPORT_DIR_NAME))
    export_dir.mkdir(exist_ok=True)

    # Clean up old exports
    _cleanup_old_exports(export_dir)

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"finance_export_{timestamp}.csv"
    filepath = export_dir / filename

    # Write CSV
    await hass.async_add_executor_job(_write_csv, filepath, filtered)

    _LOGGER.info("Exported %d transactions to %s", len(filtered), filepath)
    return str(filepath)


def _write_csv(filepath: Path, transactions: list[dict[str, Any]]) -> None:
    """Write transactions to a CSV file (sync, runs in executor)."""
    fieldnames = [
        "date",
        "amount",
        "currency",
        "creditor",
        "description",
        "category",
        "status",
    ]

    with filepath.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        for txn in transactions:
            writer.writerow(
                {
                    "date": effective_date_str(txn),
                    "amount": txn.get("transactionAmount", {}).get("amount", "0"),
                    "currency": txn.get("transactionAmount", {}).get("currency", "EUR"),
                    "creditor": txn.get("creditorName", ""),
                    "description": txn.get("remittanceInformationUnstructured", ""),
                    "category": txn.get("category", "other"),
                    "status": txn.get("_status", "booked"),
                }
            )


def _cleanup_old_exports(export_dir: Path) -> None:
    """Remove CSV files older than TTL."""
    now = datetime.now()
    for f in export_dir.glob("finance_export_*.csv"):
        try:
            age_hours = (now - datetime.fromtimestamp(f.stat().st_mtime)).total_seconds() / 3600
            if age_hours > EXPORT_TTL_HOURS:
                f.unlink()
                _LOGGER.debug("Cleaned up old export: %s", f.name)
        except (OSError, ValueError, OverflowError) as err:
            # OSError: permission changes, concurrent removal.
            # ValueError / OverflowError: corrupted st_mtime values on weird
            # filesystems. Either way, don't abort the loop — log and skip.
            _LOGGER.debug("Could not clean up old export %s: %s", f.name, err)
