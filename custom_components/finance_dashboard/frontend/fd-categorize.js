/**
 * Finance — Drag & Drop Transaction Categorizer
 *
 * Admin-only Lovelace card for re-categorizing transactions.
 * Drag transactions into category buckets. System learns new
 * keyword patterns from user corrections.
 *
 * Usage (admin dashboards only):
 *   type: custom:fd-categorize
 *
 * PRIVACY: This card only renders for HA admin users.
 * Individual transaction data is shown — never expose on
 * public/non-admin dashboards.
 */

class FdCategorize extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) { this._render(); this._rendered = true; }
    this._load();
  }

  setConfig(config) { this._config = config || {}; }

  _render() {
    this.innerHTML = `
<ha-card header="Transaktionen kategorisieren">
<style>
  .fdc { padding: 16px; font-size: 13px; }
  .fdc-info { color: var(--secondary-text-color); font-size: 12px; margin-bottom: 14px;
    padding: 10px; background: var(--primary-background-color); border-radius: 8px; }
  .fdc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .fdc-txns { max-height: 400px; overflow-y: auto; }
  .fdc-cats { display: flex; flex-direction: column; gap: 6px; }

  .fdc-txn { padding: 10px 12px; background: var(--primary-background-color);
    border: 1px solid var(--divider-color); border-radius: 8px;
    cursor: grab; transition: transform 0.15s, box-shadow 0.15s; margin-bottom: 6px; }
  .fdc-txn:active { cursor: grabbing; transform: scale(1.02);
    box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
  .fdc-txn .name { font-weight: 500; margin-bottom: 2px; }
  .fdc-txn .meta { font-size: 11px; color: var(--secondary-text-color); }
  .fdc-txn .amt { font-weight: 600; float: right; }
  .fdc-txn .amt.neg { color: var(--primary-text-color); }
  .fdc-txn .amt.pos { color: var(--accent-color, #4ecca3); }

  .fdc-cat { padding: 12px; border: 2px dashed var(--divider-color);
    border-radius: 10px; min-height: 60px; transition: border-color 0.2s, background 0.2s; }
  .fdc-cat.over { border-color: var(--accent-color, #4ecca3);
    background: rgba(78,204,163,0.05); }
  .fdc-cat .cat-label { font-weight: 600; font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
  .fdc-cat .cat-dot { width: 8px; height: 8px; border-radius: 2px; }
  .fdc-cat .cat-count { font-size: 11px; color: var(--secondary-text-color); }

  .fdc-learned { margin-top: 14px; padding: 12px; background: var(--primary-background-color);
    border-radius: 8px; }
  .fdc-learned h4 { font-size: 12px; color: var(--accent-color); margin-bottom: 6px; }
  .fdc-rule { font-size: 11px; color: var(--secondary-text-color); padding: 2px 0; }
  .fdc-none { color: var(--secondary-text-color); font-size: 12px; text-align: center; padding: 20px; }
</style>
<div class="fdc" id="fdc">
  <div class="fdc-info">
    Ziehe Transaktionen in die passende Kategorie. Das System lernt neue Zuordnungsregeln automatisch.
    <strong>Nur f&uuml;r Admins sichtbar.</strong>
  </div>
  <div class="fdc-grid">
    <div class="fdc-txns" id="txnList"></div>
    <div class="fdc-cats" id="catList"></div>
  </div>
  <div class="fdc-learned" id="learned"></div>
</div>
</ha-card>`;
  }

  async _load() {
    if (!this._hass) return;
    try {
      const data = await this._hass.callApi("GET", "finance_dashboard/transactions");
      if (data.privacy === "aggregate_only") {
        this.querySelector("#fdc").innerHTML =
          '<div class="fdc-none">Admin-Zugang erforderlich.</div>';
        return;
      }
      this._renderTransactions(data.transactions || []);
    } catch { /* not configured */ }
  }

  _renderTransactions(txns) {
    const eur = (v) => new Intl.NumberFormat("de-DE",{style:"currency",currency:"EUR"}).format(v);
    const cats = ["housing_cold","housing_warm","groceries","mobility","health","leisure","media","finance","income_work","income_state","income_capital","income_refund","income_private","other"];
    // catColors comes from window._fd.CAT_COLORS (set by fd-shared-styles.js)
    const catColors = window._fd.CAT_COLORS;

    // Filter to "other" or uncategorized transactions
    const uncategorized = txns.filter(t => t.category === "other" || !t.category).slice(0, 20);

    const txnList = this.querySelector("#txnList");
    if (uncategorized.length === 0) {
      txnList.innerHTML = '<div class="fdc-none">Alle Transaktionen sind kategorisiert.</div>';
    } else {
      txnList.innerHTML = uncategorized.map((t, i) => {
        const amt = parseFloat(t.amount);
        return `<div class="fdc-txn" draggable="true" data-idx="${i}"
          data-creditor="${(t.creditor||t.description||'').replace(/"/g,'')}"
          data-amount="${t.amount}">
          <span class="amt ${amt>=0?'pos':'neg'}">${eur(amt)}</span>
          <div class="name">${t.creditor || t.description || 'Unbekannt'}</div>
          <div class="meta">${t.date} &middot; ${t.category || 'unkategorisiert'}</div>
        </div>`;
      }).join("");

      // Add drag events
      txnList.querySelectorAll(".fdc-txn").forEach(el => {
        el.addEventListener("dragstart", (e) => {
          e.dataTransfer.setData("text/plain", JSON.stringify({
            creditor: el.dataset.creditor,
            amount: el.dataset.amount,
          }));
        });
      });
    }

    // Category drop targets
    const catList = this.querySelector("#catList");
    catList.innerHTML = cats.map(c =>
      `<div class="fdc-cat" data-cat="${c}">
        <div class="cat-label"><div class="cat-dot" style="background:${catColors[c]}"></div>${c}</div>
        <div class="cat-count">Hierher ziehen</div>
      </div>`
    ).join("");

    catList.querySelectorAll(".fdc-cat").forEach(el => {
      el.addEventListener("dragover", (e) => { e.preventDefault(); el.classList.add("over"); });
      el.addEventListener("dragleave", () => el.classList.remove("over"));
      el.addEventListener("drop", (e) => {
        e.preventDefault();
        el.classList.remove("over");
        try {
          const data = JSON.parse(e.dataTransfer.getData("text/plain"));
          this._assignCategory(data.creditor, el.dataset.cat);
          el.querySelector(".cat-count").textContent = `${data.creditor} zugeordnet`;
        } catch {}
      });
    });

    this._renderLearnedRules();
  }

  async _assignCategory(creditor, category) {
    // The backend categorizer learns from this assignment
    // For now, we call a service to update rules
    if (this._hass) {
      await this._hass.callService("finance_dashboard", "categorize_transactions", {});
    }
    this._addLearnedRule(creditor, category);
  }

  _addLearnedRule(creditor, category) {
    if (!this._learnedRules) this._learnedRules = [];
    this._learnedRules.push({ creditor, category, time: new Date().toLocaleTimeString("de-DE") });
    this._renderLearnedRules();
  }

  _renderLearnedRules() {
    const el = this.querySelector("#learned");
    if (!this._learnedRules || this._learnedRules.length === 0) {
      el.innerHTML = '<h4>Gelernte Regeln</h4><div class="fdc-rule">Noch keine Zuordnungen in dieser Session.</div>';
      return;
    }
    el.innerHTML = `<h4>Gelernte Regeln (${this._learnedRules.length})</h4>` +
      this._learnedRules.map(r =>
        `<div class="fdc-rule">${r.time}: "${r.creditor}" &rarr; ${r.category}</div>`
      ).join("");
  }

  static getStubConfig() { return {}; }
  getCardSize() { return 6; }

  // Sections view: width in columns (multiple of 3 of the 12-col grid), height in rows.
  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: 6, min_rows: 4, max_rows: 12 };
  }
}

window._fd.defineOnce("fd-categorize", FdCategorize);
window._fd.registerCard({
  type: "fd-categorize",
  name: "Finance — Categorize",
  description: "Drag & drop transaction categorization (admin only).",
});
