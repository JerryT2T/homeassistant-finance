/**
 * Finance Dashboard — component kit loader (the ONE entry point of the kit).
 *
 * "One component kit, two shells": every web component (fd-*) and every
 * Lovelace card is defined by this module. The sidebar panel
 * (finance-dashboard-panel.js) is just a full-page layout of the same
 * components; Lovelace cards are the same components in a card frame.
 *
 * Delivery: the integration registers this file with
 * frontend.add_extra_js_url(), so it loads on every dashboard and the cards
 * show up in the card picker with no hand-added Lovelace resource. The panel
 * awaits the same module, so a direct page load of the panel works too.
 *
 * Cache-busting: the integration appends ?v=<VERSION> to this URL. Children
 * are loaded with dynamic import() and inherit that query - static relative
 * imports would drop it and serve stale files from the long-lived cache.
 *
 * Load order: fd-shared-styles first (it defines window._fd, which every other
 * component reads lazily at render time), then everything else in parallel.
 * Nothing here touches ha-card or other HA elements at load time, so the kit
 * can safely run before Lovelace's own elements are defined.
 */

const _query = new URL(import.meta.url).search;
const _load = (file) => import(new URL(file + _query, import.meta.url).href);

const COMPONENTS = [
  "fd-subpage-header.js",
  "fd-home.js",
  "fd-freshness.js",
  "fd-cycle-detail.js",
  "fd-owner-chip.js",
  "fd-transactions.js",
  "fd-budget-plan.js",
  "fd-settings.js",
  "fd-history-import.js",
  "fd-setup.js",
  "fd-plan-wizard.js",
  "fd-questions.js",
  "fd-contracts.js",
  "fd-benchmark.js",
  "fd-review.js",
];

const CARDS = [
  "finance-dashboard-card.js",
  "finance-status-chip.js",
  "fd-budget-config.js",
  "fd-categorize.js",
];

if (!window.__fdKitReady) {
  window.__fdKitReady = (async () => {
    await _load("fd-shared-styles.js");
    // allSettled: one broken or missing module must not take the whole kit
    // (and with it the panel) down; the failing element just stays undefined.
    const results = await Promise.allSettled([...COMPONENTS, ...CARDS].map(_load));
    results.forEach((r, i) => {
      if (r.status === "rejected") console.error(`finance kit: ${[...COMPONENTS, ...CARDS][i]} failed to load`, r.reason);
    });
  })();
}

export const ready = window.__fdKitReady;
await ready;
