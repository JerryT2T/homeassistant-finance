/**
 * fd-transactions — the transaction list (desktop only, a subpage).
 *
 * Extracted from fd-overview's transactions section (search, account filter, rows,
 * paging). Spec: docs/dev/ui-concept-gap.md § 1.6 / G19, VR-later 5. There is no mobile
 * entry: below 1024 px the page says it is a desktop view instead of loading ~650 rows.
 *
 *   <fd-transactions>   property: hass (required); attribute `embedded` = no own header
 *
 * Data (cache reads, never a bank call):
 *   GET finance_dashboard/transactions?q&account&limit&offset   admin only
 *       (non-admins get {privacy:"aggregate_only"} -> one quiet line, no rows)
 *   GET finance_dashboard/balances                              only the account names for the filter
 * IBANs appear masked only (last 4 digits), as the API delivers them.
 *
 * Overflow: text column `min-width:0`, remittance wraps anywhere (max 2 lines), meta line
 * ellipsizes, amount never shrinks. Fine at 375 px as well as on desktop.
 *
 * Events (bubbling, composed): fd-navigate {target:"back"} via the shared subpage header.
 */

const DOMAIN = "finance_dashboard";
const PAGE_SIZE = 25;
const DEBOUNCE_MS = 300;
const DESKTOP = "(min-width: 1024px)";

/*FB-START*/
const FB = {
  de: {
    "tx.ct.ended": "beendet",
    "tx.ct.title": "Vertrag zuordnen",
    "tx.ct.none": "Kein Vertrag",
    "tx.ct.assign": "Übernehmen",
    "tx.ct.done": "Dem Vertrag zugeordnet",
    "tx.ct.removed": "Zuordnung entfernt",
    "tx.ct.detected": "Die Erkennung ordnet diese Buchung dem Vertrag zu. Wähle einen anderen Vertrag oder teile die Zahlungsreihe im Vertrag.",
    "tx.title": "Transaktionen",
    "tx.search": "Suche in Verwendungszweck, Gegenpartei, Konto",
    "tx.search_label": "Transaktionen durchsuchen",
    "tx.all_accounts": "Alle Konten",
    "tx.account_label": "Konto filtern",
    "tx.empty": "Keine Transaktionen gefunden.",
    "tx.range": "$first–$last von $count",
    "tx.prev": "Zurück",
    "tx.next": "Weiter",
    "tx.pending": "vorgemerkt",
    "tx.admin_only": "Einzelne Transaktionen sind nur für Administratoren sichtbar.",
    "tx.error": "Transaktionen konnten nicht geladen werden.",
    "tx.retry": "Erneut versuchen",
    "tx.loading": "Wird geladen …",
    "tx.desktop_only": "Die Transaktionsliste gibt es nur am Desktop.",
  },
  en: {
    "tx.ct.ended": "ended",
    "tx.ct.title": "Assign to contract",
    "tx.ct.none": "No contract",
    "tx.ct.assign": "Apply",
    "tx.ct.done": "Assigned to the contract",
    "tx.ct.removed": "Assignment removed",
    "tx.ct.detected": "Detection links this booking to the contract. Pick another contract or split the series in the contract.",
    "tx.title": "Transactions",
    "tx.search": "Search purpose, counterparty, account",
    "tx.search_label": "Search transactions",
    "tx.all_accounts": "All accounts",
    "tx.account_label": "Filter by account",
    "tx.empty": "No transactions found.",
    "tx.range": "$first–$last of $count",
    "tx.prev": "Previous",
    "tx.next": "Next",
    "tx.pending": "pending",
    "tx.admin_only": "Individual transactions are visible to administrators only.",
    "tx.error": "Could not load transactions.",
    "tx.retry": "Try again",
    "tx.loading": "Loading …",
    "tx.desktop_only": "The transaction list is available on desktop only.",
  },
};
/*FB-END*/

function tr(key, vars = {}) {
  let s = window._fd.tSync(key, vars);
  if (s !== key) return s;
  const raw = ((window._fd._hass && window._fd._hass.language) || navigator.language || "en").toLowerCase();
  s = (FB[raw.startsWith("de") ? "de" : "en"][key]) || key;
  for (const [k, v] of Object.entries(vars)) s = s.replace(new RegExp(`\\$${k}`, "g"), String(v));
  return s;
}

const CSS = `
:host { display: block; min-width: 0; }
.root { container: tx / inline-size; color: var(--fd-t1); font-size: 13px; line-height: 1.4; min-width: 0; }
button, input, select { font: inherit; color: inherit; }
button { cursor: pointer; }
button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
.card { margin: 0 0 12px; padding: 12px 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); min-width: 0; }
.muted { color: var(--fd-t2); font-size: 11.5px; }
.empty { padding: 24px 12px; text-align: center; color: var(--fd-t2); }
.empty .btn { margin-top: 10px; }
.btn { display: inline-flex; align-items: center; justify-content: center; min-height: var(--fd-touch); padding: 0 16px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; }
.btn.ghost { background: transparent; color: var(--fd-a700); border-color: var(--fd-a100); }
.btn:disabled { opacity: .5; cursor: default; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 8px; }
.filters input, .filters select { box-sizing: border-box; min-height: var(--fd-touch); padding: 0 12px; border: 1px solid var(--fd-line); border-radius: 10px; background: var(--fd-page); color: var(--fd-t1); max-width: 100%; }
.filters input { flex: 2 1 220px; min-width: 0; }
.filters select { flex: 1 1 200px; min-width: 0; text-overflow: ellipsis; }
.row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 12px; padding: 8px 0; }
.row + .row { border-top: 1px solid var(--fd-line); }
.row .l { min-width: 0; }
.row .p { font-weight: 500; overflow-wrap: anywhere; }
.row .d { color: var(--fd-t2); font-size: 12px; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.row .m { grid-column: 1 / -1; min-width: 0; color: var(--fd-t2); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row .a { grid-column: 2; grid-row: 1; flex: none; text-align: right; white-space: nowrap; font-weight: 500; font-variant-numeric: tabular-nums; }
.row .a.in { color: var(--fd-ok); }
.row .ac::before { content: " · "; white-space: pre; }
.chip { display: inline-flex; padding: 0 8px; border-radius: var(--fd-r-pill); font-size: 10.5px; font-weight: 500; background: var(--fd-sunk); color: var(--fd-t2); white-space: nowrap; }
@container tx (min-width: 720px) {
  .row { grid-template-columns: 92px minmax(0, 1fr) minmax(0, 200px) auto; align-items: start; gap: 12px; }
  .row .m { display: contents; }
  .row .m .dt { grid-column: 1; grid-row: 1; }
  .row .l { grid-column: 2; grid-row: 1; }
  .row .ac::before { content: none; }
  .row .m .ac { grid-column: 3; grid-row: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row .a { grid-column: 4; grid-row: 1; }
  .row .lb { grid-column: 2 / -1; grid-row: 2; }
}
.pager { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; padding-top: 8px; border-top: 1px solid var(--fd-line); }
.pager .btns { display: flex; gap: 6px; }
.row[data-i] { cursor: pointer; border-radius: 8px; }
.row[data-i]:hover { background: var(--fd-sunk); }
.row[data-i]:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: -2px; }
.row .cat { color: var(--fd-t2); font-size: 11.5px; overflow-wrap: anywhere; }
.row .cat i { font-style: normal; opacity: .8; }
.row .lb { grid-column: 1 / -1; min-width: 0; }
.row .lb:empty { display: none; }
.scrim { position: fixed; inset: 0; z-index: 50; display: flex; align-items: flex-end; justify-content: center; background: rgba(0,0,0,.4); }
.dlg { box-sizing: border-box; width: min(480px, 100%); max-height: 90dvh; overflow: auto; padding: 16px; border-radius: 18px 18px 0 0; background: var(--fd-card); box-shadow: var(--fd-sh2); }
@media (min-width: 600px) { .scrim { align-items: center; } .dlg { border-radius: 18px; } }
.dlg h3 { margin: 0 0 2px; font-size: 15px; font-weight: 500; overflow-wrap: anywhere; }
.dlg .sec { margin: 12px 0 4px; font-size: 12px; color: var(--fd-t2); }
.pick { display: flex; flex-wrap: wrap; gap: 6px; }
.pick label { position: relative; display: inline-flex; align-items: center; min-height: 40px; padding: 0 14px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); cursor: pointer; font-size: 12.5px; }
.pick input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
.pick label:has(input:checked) { background: var(--fd-a50); border-color: var(--fd-a500); color: var(--fd-a900); font-weight: 500; }
.pick label:has(input:focus-visible) { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
.newrow { display: flex; gap: 8px; margin-top: 8px; }
.newrow select { flex: 1 1 auto; min-width: 0; min-height: var(--fd-touch); padding: 0 8px; border: 1px solid var(--fd-line); border-radius: 10px; background: var(--fd-page); color: var(--fd-t1); font: inherit; }
.newrow input { flex: 1 1 auto; min-width: 0; box-sizing: border-box; min-height: var(--fd-touch); padding: 0 12px; border: 1px solid var(--fd-line); border-radius: 10px; background: var(--fd-page); color: var(--fd-t1); }
.acts { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.err { margin-top: 8px; color: var(--fd-over); font-size: 12px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.wide { display: none; }
.narrow { display: block; }
@media (min-width: 1024px) { .wide { display: block; } .narrow { display: none; } }
`;

class FdTransactions extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._accounts = [];
    this._labels = [];
    this._dlg = null;
    this._tx = { items: [], total: 0, offset: 0 };
    this._status = "idle"; // idle | loading | ok | admin | error
    this._q = "";
    this._account = "";
    this._timer = null;
    this._seq = 0;
    this._built = false;
    this._mq = typeof matchMedia === "function" ? matchMedia(DESKTOP) : null;
    this._onMq = () => { if (this._mq.matches && this._status === "idle") this.reload(); };
  }

  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) this.reload();
  }
  get hass() { return this._hass; }

  get _isAdmin() { return !!(this._hass && this._hass.user && this._hass.user.is_admin); }
  get _desktop() { return !this._mq || this._mq.matches; }

  connectedCallback() { if (this._mq) this._mq.addEventListener("change", this._onMq); }
  disconnectedCallback() {
    clearTimeout(this._timer);
    if (this._mq) this._mq.removeEventListener("change", this._onMq);
  }

  /** Re-read accounts and the first page. */
  async reload() {
    if (!this._hass) return;
    await window._fd.t("tx.title");
    if (!this._built) { this._built = true; this._render(); }
    if (!this._desktop) return; // desktop-only: no 650-row fetch on a phone
    if (!this._isAdmin) { this._status = "admin"; this._render(); return; }
    try {
      const balances = await this._hass.callApi("GET", `${DOMAIN}/balances`);
      this._accounts = Object.entries(balances || {})
        .filter(([, a]) => a && typeof a === "object" && !a.error && a.account_key)
        .map(([id, a]) => ({ id, ...a }));
    } catch (_) {
      this._accounts = [];
    }
    await this._load(0);
  }

  async _load(offset) {
    const seq = ++this._seq;
    this._status = "loading";
    this._paintList();
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (this._q) params.set("q", this._q);
    if (this._account) params.set("account", this._account);
    // Catalogue is fetched once (cached in the shared helper); chips need the custom names.
    const labelsP = window._fd.getLabels(this._hass).then((l) => { this._labels = l; });
    try {
      const r = await this._hass.callApi("GET", `${DOMAIN}/transactions?${params}`);
      await labelsP;
      if (seq !== this._seq) return;
      if (r && r.privacy === "aggregate_only") {
        this._status = "admin";
        this._render();
        return;
      }
      this._tx = { items: (r && r.transactions) || [], total: (r && r.total) || 0, offset: (r && r.offset) || 0 };
      this._status = "ok";
    } catch (_) {
      if (seq !== this._seq) return;
      this._status = "error";
    }
    this._paintList();
  }

  _render() {
    if (!this._built) return;
    const { SHARED_CSS, escHtml: e } = window._fd;
    const head = this.hasAttribute("embedded") ? "" : `<fd-subpage-header title="${e(tr("tx.title"))}"></fd-subpage-header>`;
    let inner;
    if (this._status === "admin") {
      inner = `<div class="card"><div class="empty">${e(tr("tx.admin_only"))}</div></div>`;
    } else {
      inner = `<div class="narrow card"><div class="empty">${e(tr("tx.desktop_only"))}</div></div>
<div class="wide card">
  <div class="filters">
    <label class="sr" for="q">${e(tr("tx.search_label"))}</label>
    <input id="q" type="search" placeholder="${e(tr("tx.search"))}" autocomplete="off" value="${e(this._q)}">
    <label class="sr" for="acct">${e(tr("tx.account_label"))}</label>
    <select id="acct">
      <option value="">${e(tr("tx.all_accounts"))}</option>
      ${this._accounts.map((a) => `<option value="${e(a.account_key)}"${a.account_key === this._account ? " selected" : ""}>${e(a.account_name || a.id)} (${e(a.iban_masked || "****")})</option>`).join("")}
    </select>
  </div>
  <div id="list"></div>
</div>`;
    }
    this.shadowRoot.innerHTML = `<style>${SHARED_CSS}${CSS}</style><div class="root">${head}${inner}</div>`;
    const q = this.shadowRoot.getElementById("q");
    if (q) {
      q.addEventListener("input", () => {
        clearTimeout(this._timer);
        this._timer = setTimeout(() => { this._q = q.value.trim(); this._load(0); }, DEBOUNCE_MS);
      });
      this.shadowRoot.getElementById("acct").addEventListener("change", (ev) => {
        this._account = ev.target.value;
        this._load(0);
      });
    }
    this._paintList();
  }

  /** Repaint only the list so the search field keeps focus while typing. */
  _paintList() {
    const list = this.shadowRoot && this.shadowRoot.getElementById("list");
    if (!list) return;
    const { escHtml: e, fmtDate } = window._fd;
    const t = this._tx;
    if (this._status === "loading" && !t.items.length) { list.innerHTML = `<div class="empty">${e(tr("tx.loading"))}</div>`; return; }
    if (this._status === "error") {
      list.innerHTML = `<div class="empty">${e(tr("tx.error"))}<br><button class="btn ghost" id="retry">${e(tr("tx.retry"))}</button></div>`;
      list.querySelector("#retry").addEventListener("click", () => this._load(t.offset));
      return;
    }
    if (!t.items.length) { list.innerHTML = `<div class="empty">${e(tr("tx.empty"))}</div>`; return; }
    const fmtAmt = (x) => {
      const n = parseFloat(x.amount);
      try { return new Intl.NumberFormat(undefined, { style: "currency", currency: x.currency || "EUR" }).format(n); }
      catch (_) { return `${x.amount} ${x.currency || ""}`; }
    };
    const { catLabel, labelChips } = window._fd;
    const rows = t.items.map((x, idx) => {
      const n = parseFloat(x.amount);
      const party = x.creditor || x.debtor || "";
      const pend = x.status && x.status !== "booked" ? ` <span class="chip">${e(tr("tx.pending"))}</span>` : "";
      const cat = x.category ? `<div class="cat">${e(catLabel(x.category))}${x.category_source === "contract" ? ` <i>· ${e(tr("tx.from_contract"))}</i>` : ""}</div>` : "";
      const rs = x.refund_state ? `<span class="chip">${e(tr(`rf.state.${x.refund_state.state}`))}</span>` : "";
      const chips = labelChips(x.labels_inherited, this._labels, "inherited") + labelChips(x.labels_own, this._labels, "own") + labelChips(x.labels_auto, this._labels, "auto") + rs;
      const open = this._isAdmin && x.ledger_id
        ? ` data-i="${idx}" role="button" tabindex="0" aria-label="${e(tr("tx.open_booking") + ": " + (party || x.description || ""))}"` : "";
      return `<div class="row"${open}>
  <div class="l"><div class="p">${e(party)}${pend}</div><div class="d">${e(x.description)}</div>${cat}</div>
  <div class="a ${n > 0 ? "in" : ""}">${e(fmtAmt(x))}</div>
  <div class="lb"><div class="lcs">${chips}</div></div>
  <div class="m"><span class="dt">${e(fmtDate(x.date))}</span><span class="ac">${e(x.account_name || "")}</span></div>
</div>`;
    });
    const from = t.offset + 1;
    const to = t.offset + t.items.length;
    list.innerHTML = `${rows.join("")}
<div class="pager">
  <span class="muted">${e(tr("tx.range", { first: from, last: to, count: t.total }))}</span>
  <span class="btns">
    <button class="btn ghost" id="prev" ${t.offset <= 0 ? "disabled" : ""}>${e(tr("tx.prev"))}</button>
    <button class="btn ghost" id="next" ${to >= t.total ? "disabled" : ""}>${e(tr("tx.next"))}</button>
  </span>
</div>`;
    list.querySelector("#prev").addEventListener("click", () => this._load(Math.max(0, t.offset - PAGE_SIZE)));
    list.querySelector("#next").addEventListener("click", () => this._load(t.offset + PAGE_SIZE));
    list.querySelectorAll(".row[data-i]").forEach((r) => {
      const open = () => this._openDialog(Number(r.dataset.i), r);
      r.addEventListener("click", open);
      r.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } });
    });
  }

  // ---- booking dialog (#113) -------------------------------------------------
  async _openDialog(i, opener) {
    const x = this._tx.items[i];
    if (!x || !x.ledger_id) return;
    this._dlg = { x, opener, sel: new Set(x.labels_own || []), error: "", saving: false, newName: "", rf: null, rfSel: new Set(), rfError: "" };
    this._paintDialog();
    this._focusDialog();
    this._loadRefund(this._dlg);
    if (!this._labels.length) {
      this._labels = await window._fd.getLabels(this._hass);
      if (this._dlg && this._dlg.x === x) { this._paintDialog(); this._focusDialog(); }
    }
    if (!this._contracts) {
      await this._loadContracts();
      if (this._dlg && this._dlg.x === x && this._contracts) {
        const had = this.shadowRoot.activeElement;
        this._paintDialog();
        this._focusDialog(had && had.id ? `#${had.id}` : undefined);
      }
    }
  }

  // Refund allocation (#119): an incoming booking picks the expenses it paid back.
  async _loadRefund(d) {
    if (parseFloat(d.x.amount) <= 0 && !d.x.refund_state) return;
    try {
      const r = await this._hass.callApi("GET", `${DOMAIN}/refunds/${encodeURIComponent(d.x.ledger_id)}`);
      if (this._dlg !== d) return;
      d.rf = r;
      const chosen = r.kind === "refund" ? (r.allocated || []).map((a) => a.id) : [];
      // Merge, do not overwrite: ticks made while the GET was in flight stay.
      for (const id of (chosen.length ? chosen : (r.proposal && r.proposal.expenses) || [])) d.rfSel.add(id);
      this._paintDialog();
    } catch (_) { /* the labels part of the dialog stays usable */ }
  }

  _refundHtml(d) {
    const r = d.rf;
    if (!r) return "";
    const { escHtml: e, fmtDate } = window._fd;
    const money = (n) => { try { return new Intl.NumberFormat(undefined, { style: "currency", currency: d.x.currency || "EUR" }).format(n); } catch (_) { return String(n); } };
    const line = (c) => `${fmtDate(c.date)} · ${c.party || c.description} · ${money(Math.abs(c.amount))}`;
    if (r.kind === "expense") {
      if (!(r.refunded || []).length) return "";
      return `<div class="sec">${e(tr("rf.refunded_by"))}</div><ul class="muted">${r.refunded.map((c) => `<li>${e(fmtDate(c.date))} · ${e(c.party || "")} · ${e(money(c.refunded))}</li>`).join("")}</ul>`;
    }
    const status = r.source === "manual" ? tr("rf.source_manual") : r.source === "auto" ? tr("rf.source_auto") : r.proposal ? tr("rf.proposal") : "";
    const pick = (r.candidates || []).length
      ? r.candidates.map((c) => `<label><input type="checkbox" data-rf="${e(c.id)}"${d.rfSel.has(c.id) ? " checked" : ""}>${e(line(c))}</label>`).join("")
      : `<span class="muted">${e(tr("rf.none"))}</span>`;
    return `<div class="sec" id="rfh">${e(tr("rf.title"))}</div>
  <div class="muted">${e(tr("rf.hint"))}${status ? " " + e(status) : ""}</div>
  <div class="pick" role="group" aria-labelledby="rfh">${pick}</div>
  <div class="err" role="alert">${e(d.rfError)}</div>
  <div class="acts"><button type="button" class="btn ghost" data-act="rf-reset"${r.source === "manual" ? "" : " disabled"}>${e(tr("rf.reset"))}</button>
    <button type="button" class="btn" data-act="rf-save"${d.saving ? " disabled" : ""}>${e(tr("rf.save"))}</button></div>`;
  }

  async _saveRefund(reset) {
    const d = this._dlg;
    if (!d || d.saving) return;
    d.saving = true;
    d.rfError = "";
    this._paintDialog();
    const url = `${DOMAIN}/refunds/${encodeURIComponent(d.x.ledger_id)}`;
    try {
      const r = reset ? await this._hass.callApi("DELETE", url) : await this._hass.callApi("PUT", url, { expenses: [...d.rfSel] });
      d.rf = r;
      const got = (r.allocated || []).map((a) => a.id);
      d.rfSel = new Set(got.length ? got : (r.proposal && r.proposal.expenses) || []);
      d.saving = false;
      if (this._dlg === d) this._paintDialog();
      this._load(this._tx.offset);
    } catch (_) {
      d.saving = false;
      if (this._dlg !== d) return;
      d.rfError = tr("rf.err");
      this._paintDialog();
    }
  }

  _focusDialog(sel) {
    const el = this.shadowRoot.querySelector(sel || "#dlg .pick input, #dlg button");
    if (el) el.focus();
  }

  _closeDialog() {
    const d = this._dlg;
    this._dlg = null;
    const host = this.shadowRoot.getElementById("dlg");
    if (host) host.innerHTML = "";
    if (d && d.opener && d.opener.isConnected) d.opener.focus();
  }

  _paintDialog() {
    const d = this._dlg;
    let host = this.shadowRoot.getElementById("dlg");
    if (!host) {
      host = document.createElement("div");
      host.id = "dlg";
      this.shadowRoot.appendChild(host);
      host.addEventListener("click", (ev) => this._onDlgClick(ev));
      host.addEventListener("keydown", (ev) => this._onDlgKey(ev));
      host.addEventListener("input", (ev) => { if (ev.target.id === "newlb" && this._dlg) this._dlg.newName = ev.target.value; });
      host.addEventListener("change", (ev) => {
        if (ev.target.id === "ctsel" && this._dlg) { this._dlg.ct = ev.target.value; return; }
        const id = ev.target.dataset && ev.target.dataset.lb;
        if (id && this._dlg) { if (ev.target.checked) this._dlg.sel.add(id); else this._dlg.sel.delete(id); }
        const rf = ev.target.dataset && ev.target.dataset.rf;
        if (rf && this._dlg) { if (ev.target.checked) this._dlg.rfSel.add(rf); else this._dlg.rfSel.delete(rf); }
      });
    }
    if (!d) { host.innerHTML = ""; return; }
    const { escHtml: e, catLabel, labelChips, labelName, fmtDate } = window._fd;
    const x = d.x;
    const inh = x.labels_inherited || [];
    const auto = x.labels_auto || [];
    const party = x.creditor || x.debtor || x.description || "";
    let catLine = "";
    if (x.category) {
      catLine = x.category_source === "contract" && x.contract_name
        ? `${e(catLabel(x.category))} · ${e(tr("tx.from_contract_named", { name: x.contract_name }))}`
        : `${e(catLabel(x.category_source === "own" ? (x.own_category || x.category) : x.category))}${x.category_source === "own" ? ` · ${e(tr("tx.own_category"))}` : ""}`;
    }
    const inhSet = new Set(inh);
    const pickable = (this._labels || []).filter((l) => l.kind !== "auto" && !inhSet.has(l.id));
    host.innerHTML = `<div class="scrim" data-act="scrim"><div class="dlg" role="dialog" aria-modal="true" aria-labelledby="dlgt">
  <h3 id="dlgt">${e(tr("tx.booking"))}: ${e(party)}</h3>
  <div class="muted">${e(fmtDate(x.date))}${x.account_name ? " · " + e(x.account_name) : ""}</div>
  ${catLine ? `<div class="sec">${e(tr("tx.category"))}</div><div>${catLine}</div>` : ""}
  ${this._dlgContractHtml(d)}
  ${inh.length ? `<div class="sec">${e(tr("lb.from_contract"))}</div><div class="lcs">${labelChips(inh, this._labels, "inherited")}</div>` : ""}
  ${auto.length ? `<div class="sec">${e(tr("lb.auto"))}</div><div class="lcs">${labelChips(auto, this._labels, "auto")}</div>` : ""}
  <div class="sec" id="ownh">${e(tr("lb.own"))}</div>
  <div class="pick" role="group" aria-labelledby="ownh">${pickable.length ? pickable.map((l) => `<label><input type="checkbox" data-lb="${e(l.id)}"${d.sel.has(l.id) ? " checked" : ""}>${e(labelName(l.id, this._labels))}</label>`).join("") : `<span class="muted">${e(tr("lb.none"))}</span>`}</div>
  ${this._refundHtml(d)}
  <div class="sec"><label for="newlb">${e(tr("lb.new"))}</label></div>
  <div class="newrow"><input id="newlb" type="text" maxlength="40" autocomplete="off" placeholder="${e(tr("lb.new_ph"))}" value="${e(d.newName)}">
    <button type="button" class="btn ghost" data-act="add">${e(tr("lb.add"))}</button></div>
  <div class="err" role="alert">${e(d.error)}</div>
  <div class="acts"><button type="button" class="btn ghost" data-act="cancel">${e(tr("tx.cancel"))}</button>
    <button type="button" class="btn" data-act="save" ${d.saving ? "disabled" : ""}>${e(tr(d.saving ? "tx.saving" : "tx.save"))}</button></div>
</div></div>`;
  }

  // ---- "Vertrag zuordnen" (#117 F): self-contained, acts right away ---------
  _dlgContractHtml(d) {
    const e = window._fd.escHtml;
    const list = this._contracts;
    if (!list) return "";
    const cur = d.x.contract_id || "";
    const opts = list.map((c) => `<option value="${e(c.id)}"${c.id === (d.ct ?? cur) ? " selected" : ""}>${e(c.display_name || c.creditor)}${c.status === "ended" ? ` · ${e(tr("tx.ct.ended"))}` : ""}</option>`).join("");
    return `<div class="sec"><label for="ctsel">${e(tr("tx.ct.title"))}</label></div>
  <div class="newrow"><select id="ctsel"><option value=""${(d.ct ?? cur) ? "" : " selected"}>${e(tr("tx.ct.none"))}</option>${opts}</select>
    <button type="button" class="btn ghost" data-act="ct-assign" ${d.ctBusy ? "disabled" : ""}>${e(tr("tx.ct.assign"))}</button></div>
  ${d.ctMsg ? `<div class="muted" role="status">${e(d.ctMsg)}</div>` : ""}`;
  }

  async _loadContracts() {
    if (this._contracts || !this._isAdmin) return;
    try {
      const r = await this._hass.callApi("GET", `${DOMAIN}/contracts`);
      // ended contracts stay assignable: an old booking may belong to one
      this._contracts = ((r && r.contracts) || []).filter((c) => !c.candidate);
    } catch (_) {
      this._contracts = null;
    }
  }

  async _assignContract() {
    const d = this._dlg;
    if (!d || d.ctBusy) return;
    const want = d.ct ?? (d.x.contract_id || "");
    if (want === (d.x.contract_id || "")) return;
    d.ctBusy = true;
    d.ctMsg = "";
    this._paintDialog();
    try {
      const body = want ? { action: "assign", booking: d.x.ledger_id, series_id: want } : { action: "unassign", booking: d.x.ledger_id };
      const r = await this._hass.callApi("POST", `${DOMAIN}/contract_overrides`, body);
      const all = (r && r.contracts) || [];
      this._contracts = all.filter((c) => !c.candidate);
      const hit = all.find((c) => (c.ledger_ids || []).includes(d.x.ledger_id));
      d.x.contract_id = hit ? hit.id : null;
      d.x.contract_name = hit ? hit.display_name || hit.creditor : null;
      if (hit) { d.x.category = hit.category; d.x.category_source = "contract"; }
      d.ct = undefined;
      d.ctMsg = tr(want ? "tx.ct.done" : "tx.ct.removed");
      this._paintList();
    } catch (err) {
      const code = err && err.body && err.body.error;
      d.ctMsg = tr(code === "unknown_assignment" ? "tx.ct.detected" : "tx.save_failed");
    }
    d.ctBusy = false;
    if (this._dlg !== d) return;
    this._paintDialog();
    this._focusDialog("#ctsel");
  }

  _onDlgKey(ev) {
    if (!this._dlg) return;
    if (ev.key === "Escape") { ev.stopPropagation(); this._closeDialog(); return; }
    if (ev.key === "Enter" && ev.target.id === "newlb") { ev.preventDefault(); this._createLabel(); return; }
    if (ev.key !== "Tab") return;
    const f = [...this.shadowRoot.querySelectorAll("#dlg input, #dlg select, #dlg button:not([disabled])")];
    if (!f.length) return;
    const idx = f.indexOf(this.shadowRoot.activeElement);
    if (ev.shiftKey && idx <= 0) { ev.preventDefault(); f[f.length - 1].focus(); }
    else if (!ev.shiftKey && idx === f.length - 1) { ev.preventDefault(); f[0].focus(); }
  }

  _onDlgClick(ev) {
    const t = ev.target.closest("[data-act]");
    if (!t || !this._dlg) return;
    switch (t.dataset.act) {
      case "scrim": if (ev.target === t) this._closeDialog(); break;
      case "cancel": this._closeDialog(); break;
      case "add": this._createLabel(); break;
      case "save": this._saveLabels(); break;
      case "rf-save": this._saveRefund(false); break;
      case "rf-reset": this._saveRefund(true); break;
      case "ct-assign": this._assignContract(); break;
      default: break;
    }
  }

  async _createLabel() {
    const d = this._dlg;
    const name = ((d && d.newName) || "").trim();
    if (!d || !name || d.creating) return;
    d.creating = true;
    try {
      const r = await this._hass.callApi("POST", `${DOMAIN}/labels`, { name });
      this._labels = (r && r.labels) || this._labels;
      window._fd.setLabels(this._labels);
      if (r && r.id) d.sel.add(r.id);
      d.newName = "";
      d.error = "";
    } catch (err) {
      const code = err && err.body && err.body.error;
      d.error = code && tr(`lb.err.${code}`) !== `lb.err.${code}` ? tr(`lb.err.${code}`) : tr("lb.err.generic");
    }
    d.creating = false;
    if (this._dlg !== d) return; // closed or replaced meanwhile
    this._paintDialog();
    this._focusDialog("#newlb");
  }

  async _saveLabels() {
    const d = this._dlg;
    if (!d || d.saving) return;
    d.saving = true;
    d.error = "";
    this._paintDialog();
    try {
      const r = await this._hass.callApi("PUT", `${DOMAIN}/transactions/${encodeURIComponent(d.x.ledger_id)}/labels`, { labels: [...d.sel] });
      d.x.labels_own = (r && r.labels_own) || [...d.sel];
      if (this._dlg === d) this._closeDialog();
      this._paintList();
    } catch (_) {
      d.saving = false;
      if (this._dlg !== d) return;
      d.error = tr("tx.save_failed");
      this._paintDialog();
      this._focusDialog('[data-act="save"]'); // repaint dropped focus; keep the trap working
    }
  }
}

window._fd.defineOnce("fd-transactions", FdTransactions);
