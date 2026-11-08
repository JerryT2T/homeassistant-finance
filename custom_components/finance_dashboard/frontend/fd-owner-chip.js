/**
 * fd-owner-chip — one tap-to-correct component for "whose is this booking?" (E1).
 * Used in the transaction list; the year view and the review reuse it unchanged.
 *
 * Properties (also attributes in kebab-case where a string):
 *   ledgerId   string   booking id (attr: ledger-id). Required for editing.
 *   owner      string   "shared" | person name | "" (unknown / not yet resolved)
 *   source     string   correction | merchant_rule | plan | series | category | ai | account | ""
 *   confidence number   0-100, optional; < 85 with source category is shown as "Vermutung"
 *   merchant   string   merchant name for the "für alle von <Händler> merken" box;
 *                       without it the box is hidden and reach is always "booking"
 *   persons    Array    person names, or {name, display_name}; default: read once from
 *                       GET finance_dashboard/assignments
 *   hass       object   Home Assistant object (callApi, user.is_admin)
 *   editable   bool     default: hass.user.is_admin. Non-admins get a read-only label.
 *   compact    bool     only the owner label, no source hint (attr: compact)
 *
 * Events (bubbles + composed):
 *   fd-owner-changed  detail {ledgerId, owner, reach, merchant}; owner null = back to automatic.
 *                     The host re-fetches its list (the server re-derives the bookings).
 *   fd-toast          detail {message, type}
 *
 * Backend: POST finance_dashboard/ownership/correct {ledger_id, owner, reach} (admin).
 * Keyboard: Enter/Space opens, 1..n pick (Haushalt, persons, Automatisch), Esc closes.
 * Touch: the popover is a bottom sheet below 600 px.
 */
const DOMAIN = "finance_dashboard";
const KEY = {
  "ownchip.shared": ["Haushalt", "Household"], "ownchip.open": ["Zuordnen", "Assign"],
  "ownchip.auto": ["Automatisch", "Automatic"], "ownchip.title": ["Wem gehört die Buchung?", "Whose booking is this?"],
  "ownchip.remember": ["Für alle von $merchant merken", "Remember for all of $merchant"],
  "ownchip.saved": ["Zuordnung gespeichert", "Owner saved"], "ownchip.error": ["Zuordnung fehlgeschlagen", "Could not save the owner"],
  "ownchip.close": ["Schließen", "Close"], "ownchip.guess": ["Vermutung", "Guess"],
  "ownchip.src.correction": ["Korrektur", "Correction"], "ownchip.src.merchant_rule": ["Regel", "Rule"],
  "ownchip.src.plan": ["Plan", "Plan"], "ownchip.src.series": ["Serie", "Series"],
  "ownchip.src.category": ["Kategorie", "Category"], "ownchip.src.ai": ["KI-Vorschlag", "AI suggestion"],
  "ownchip.src.account": ["Konto", "Account"],
};
function tr(key, vars = {}) {
  let s = window._fd.tSync(key, vars);
  if (s === key) {
    const l = ((window._fd._hass && window._fd._hass.language) || navigator.language || "en").toLowerCase().startsWith("de") ? 0 : 1;
    s = (KEY[key] || [key, key])[l];
    for (const [k, v] of Object.entries(vars)) s = s.replace(new RegExp(`\\$${k}`, "g"), String(v));
  }
  return s;
}

const CSS = `
:host { display: inline-block; max-width: 100%; vertical-align: middle; }
button { font: inherit; color: inherit; cursor: pointer; }
button:focus-visible, input:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
.chip { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; min-height: 28px; padding: 0 10px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: var(--fd-sunk); color: var(--fd-t1); font-size: 12px; font-weight: 500; }
button.chip:hover { border-color: var(--fd-a500); }
.dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--c, var(--fd-t3)); }
.nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.src { color: var(--fd-t2); font-weight: 400; white-space: nowrap; }
.chip.open { border-style: dashed; color: var(--fd-t2); }
@media (pointer: coarse) { .chip { min-height: var(--fd-touch, 44px); } }
.pop { position: fixed; z-index: 60; box-sizing: border-box; width: min(320px, calc(100vw - 16px)); padding: 12px; border-radius: var(--fd-r-card); background: var(--fd-card); color: var(--fd-t1); border: 1px solid var(--fd-line); box-shadow: var(--fd-sh2); font-size: 13px; }
.pop h5 { margin: 0 0 8px; font-size: 13px; font-weight: 600; padding-right: 40px; }
.opts { display: flex; flex-wrap: wrap; gap: 6px; }
.opts button { display: inline-flex; align-items: center; gap: 6px; min-height: 40px; padding: 0 12px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: transparent; max-width: 100%; }
.opts button[aria-checked="true"] { background: var(--fd-a50); border-color: var(--c, var(--fd-a500)); color: var(--fd-a900); font-weight: 500; }
.opts kbd { font: inherit; font-size: 11px; color: var(--fd-t3); border: 1px solid var(--fd-line); border-radius: 4px; padding: 0 4px; }
@media (pointer: coarse) { .opts kbd { display: none; } }
.rem { display: flex; align-items: center; gap: 10px; margin-top: 10px; min-height: 40px; color: var(--fd-t2); overflow-wrap: anywhere; }
.rem input { flex: none; width: 20px; height: 20px; accent-color: var(--fd-a700); }
.msg { margin-top: 8px; color: var(--fd-err, #b3261e); font-size: 12px; }
.x { position: absolute; top: 4px; right: 4px; min-width: 40px; min-height: 40px; border: 0; background: transparent; color: var(--fd-t2); font-size: 18px; }
.scrim { position: fixed; inset: 0; z-index: 59; background: transparent; }
@media (max-width: 599px) {
  .pop { left: 0 !important; right: 0; bottom: 0; top: auto !important; width: auto; border-radius: var(--fd-r-card) var(--fd-r-card) 0 0; padding-bottom: calc(14px + env(safe-area-inset-bottom, 0px)); }
  .scrim { background: rgba(0,0,0,.35); }
}
`;

let _personsCache = null;

class FdOwnerChip extends HTMLElement {
  static get observedAttributes() { return ["ledger-id", "owner", "source", "merchant", "confidence", "compact"]; }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._open = false; this._busy = false; this._msg = ""; this._remember = false;
    this._persons = null; this._hass = null; this._editable = null;
    this._o = { ledgerId: "", owner: "", source: "", merchant: "", confidence: null, compact: false };
  }

  get ledgerId() { return this._o.ledgerId; } set ledgerId(v) { this._set("ledgerId", v || ""); }
  get owner() { return this._o.owner; } set owner(v) { this._set("owner", v || ""); }
  get source() { return this._o.source; } set source(v) { this._set("source", v || ""); }
  get merchant() { return this._o.merchant; } set merchant(v) { this._set("merchant", v || ""); }
  get confidence() { return this._o.confidence; } set confidence(v) { this._set("confidence", v == null || v === "" ? null : Number(v)); }
  get compact() { return this._o.compact; } set compact(v) { this._set("compact", !!v); }
  get persons() { return this._persons; } set persons(v) { this._persons = Array.isArray(v) ? v : null; this._render(); }
  get hass() { return this._hass; } set hass(v) { this._hass = v; this._render(); }
  get editable() { return this._editable !== null ? this._editable : !!(this._hass && this._hass.user && this._hass.user.is_admin); }
  set editable(v) { this._editable = v === null || v === undefined ? null : !!v; this._render(); }

  attributeChangedCallback(name, _o, v) {
    const k = name === "ledger-id" ? "ledgerId" : name;
    this._o[k] = k === "confidence" ? (v == null || v === "" ? null : Number(v)) : k === "compact" ? v !== null : (v || "");
    this._render();
  }
  _set(k, v) { this._o[k] = v; this._render(); }

  connectedCallback() { this._render(); }
  disconnectedCallback() { this._open = false; }

  _name(p) { return typeof p === "string" ? p : p.name; }
  _label(p) { return typeof p === "string" ? p : (p.display_name || p.name); }
  _color(name) {
    const list = this._persons || [];
    const i = list.findIndex((p) => this._name(p) === name);
    const pal = (window._fd.MEMBER_COLORS && window._fd.MEMBER_COLORS.length) ? window._fd.MEMBER_COLORS : ["var(--fd-a500)"];
    return i < 0 ? "var(--fd-t3)" : pal[i % pal.length];
  }
  _ownerLabel() {
    const o = this._o.owner;
    if (!o) return tr("ownchip.open");
    if (o === "shared") return tr("ownchip.shared");
    const p = (this._persons || []).find((x) => this._name(x) === o);
    return p ? this._label(p) : o;
  }
  _hint() {
    const { source, confidence } = this._o;
    if (!source || this._o.compact) return "";
    const key = `ownchip.src.${source}`;
    const s = tr(key);
    if (s === key) return "";
    return source === "category" && confidence != null && confidence < 85 ? `${tr("ownchip.guess")}: ${s}` : s;
  }

  _render() {
    if (!this.isConnected) return;
    const e = window._fd.escHtml;
    const o = this._o.owner;
    const c = o === "shared" ? "var(--fd-household)" : o ? this._color(o) : "var(--fd-t3)";
    const hint = this._hint();
    const inner = `<span class="dot" style="--c:${c}" aria-hidden="true"></span><span class="nm">${e(this._ownerLabel())}</span>${hint ? `<span class="src">· ${e(hint)}</span>` : ""}`;
    const edit = this.editable && this._o.ledgerId;
    const aria = `${this._ownerLabel()}${hint ? ", " + hint : ""}`;
    this.shadowRoot.innerHTML = `<style>${window._fd.SHARED_CSS || ""}${CSS}</style>${edit
      ? `<button type="button" class="chip${o ? "" : " open"}" aria-haspopup="dialog" aria-expanded="${this._open}" aria-label="${e(aria)}" data-tip="${e(tr("ownchip.title"))}">${inner}</button>`
      : `<span class="chip${o ? "" : " open"}">${inner}</span>`}${this._open ? this._popHtml() : ""}`;
    const b = this.shadowRoot.querySelector("button.chip");
    if (b) b.addEventListener("click", (ev) => { ev.stopPropagation(); this._toggle(); });
    if (this._open) this._wirePop();
  }

  _optList() {
    const persons = this._persons || [];
    return [{ v: "shared", l: tr("ownchip.shared"), c: "var(--fd-household)" }]
      .concat(persons.map((p) => ({ v: this._name(p), l: this._label(p), c: this._color(this._name(p)) })))
      .concat([{ v: null, l: tr("ownchip.auto"), c: "var(--fd-t3)" }]);
  }

  _popHtml() {
    const e = window._fd.escHtml;
    const opts = this._optList().map((x, i) => `<button type="button" role="radio" aria-checked="${x.v !== null && x.v === this._o.owner}" data-v="${x.v === null ? "" : e(x.v)}" data-auto="${x.v === null ? 1 : 0}" style="--c:${x.c}" ${this._busy ? "disabled" : ""}><span class="dot" style="--c:${x.c}" aria-hidden="true"></span>${e(x.l)}${i < 9 ? `<kbd aria-hidden="true">${i + 1}</kbd>` : ""}</button>`).join("");
    const rem = this._o.merchant ? `<label class="rem"><input type="checkbox" id="rem" ${this._remember ? "checked" : ""}><span>${e(tr("ownchip.remember", { merchant: this._o.merchant }))}</span></label>` : "";
    return `<div class="scrim" id="scrim"></div><div class="pop" role="dialog" aria-label="${e(tr("ownchip.title"))}" id="pop">
<button type="button" class="x" id="x" aria-label="${e(tr("ownchip.close"))}">×</button>
<h5>${e(tr("ownchip.title"))}</h5><div class="opts" role="radiogroup" aria-label="${e(tr("ownchip.title"))}">${opts}</div>${rem}
${this._msg ? `<div class="msg" role="alert">${e(this._msg)}</div>` : ""}</div>`;
  }

  _wirePop() {
    const sh = this.shadowRoot;
    const pop = sh.getElementById("pop");
    const btn = sh.querySelector("button.chip");
    if (btn && pop && window.matchMedia && !window.matchMedia("(max-width: 599px)").matches) {
      const r = btn.getBoundingClientRect();
      const w = Math.min(320, window.innerWidth - 16);
      pop.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`;
      const below = window.innerHeight - r.bottom;
      if (below < 230 && r.top > below) { pop.style.bottom = `${window.innerHeight - r.top + 6}px`; pop.style.top = "auto"; }
      else pop.style.top = `${r.bottom + 6}px`;
    }
    sh.getElementById("scrim").addEventListener("click", (ev) => { ev.stopPropagation(); this._close(true); });
    sh.getElementById("x").addEventListener("click", () => this._close(true));
    const rem = sh.getElementById("rem");
    if (rem) rem.addEventListener("change", () => { this._remember = rem.checked; });
    const btns = [...sh.querySelectorAll(".opts button")];
    btns.forEach((b) => b.addEventListener("click", () => this._pick(b.dataset.auto === "1" ? null : b.dataset.v)));
    pop.addEventListener("keydown", (ev) => {
      ev.stopPropagation();
      if (ev.key === "Escape") { this._close(true); return; }
      const n = Number(ev.key);
      if (n >= 1 && n <= btns.length && !ev.ctrlKey && !ev.metaKey && !ev.altKey && ev.target.type !== "checkbox") { ev.preventDefault(); btns[n - 1].click(); }
      if (ev.key === "Tab") {
        const f = [...pop.querySelectorAll("button:not([disabled]),input")];
        const first = f[0], last = f[f.length - 1], act = sh.activeElement;
        if (ev.shiftKey && act === first) { ev.preventDefault(); last.focus(); }
        else if (!ev.shiftKey && act === last) { ev.preventDefault(); first.focus(); }
      }
    });
  }

  async _toggle() {
    if (this._open) return this._close(true);
    this._open = true; this._msg = "";
    if (!this._persons) await this._loadPersons();
    this._render();
    const cur = this.shadowRoot.querySelector('.opts button[aria-checked="true"]') || this.shadowRoot.querySelector(".opts button");
    if (cur) cur.focus();
  }

  async _loadPersons() {
    try {
      if (!_personsCache) _personsCache = this._hass.callApi("GET", `${DOMAIN}/assignments`).then((r) => (r.persons || []).map((p) => ({ name: p.name, display_name: p.display_name })));
      this._persons = await _personsCache;
    } catch (_) { _personsCache = null; this._persons = []; }
  }

  _close(refocus) {
    if (!this._open) return;
    this._open = false; this._msg = "";
    this._render();
    if (refocus) { const b = this.shadowRoot.querySelector("button.chip"); if (b) b.focus(); }
  }

  async _pick(owner) {
    if (this._busy || !this._o.ledgerId) return;
    const reach = this._remember && this._o.merchant ? "merchant" : "booking";
    this._busy = true; this._msg = ""; this._render();
    try {
      const res = await this._hass.callApi("POST", `${DOMAIN}/ownership/correct`, { ledger_id: this._o.ledgerId, owner, reach });
      this._busy = false; this._open = false;
      this._o.owner = owner || ""; this._o.source = owner ? "correction" : ""; this._o.confidence = owner ? 100 : null;
      this._render();
      const detail = { ledgerId: this._o.ledgerId, owner, reach, merchant: (res && res.merchant) || this._o.merchant };
      this.dispatchEvent(new CustomEvent("fd-owner-changed", { bubbles: true, composed: true, detail }));
      this.dispatchEvent(new CustomEvent("fd-toast", { bubbles: true, composed: true, detail: { message: tr("ownchip.saved"), type: "success" } }));
      const b = this.shadowRoot.querySelector("button.chip"); if (b) b.focus();
    } catch (err) {
      this._busy = false;
      const d = err && err.body && (err.body.detail || err.body.error);
      this._msg = `${tr("ownchip.error")}${d ? `: ${d}` : ""}`;
      this._render();
    }
  }
}

window._fd.defineOnce("fd-owner-chip", FdOwnerChip);
