/**
 * fd-freshness — "Datenstand" subpage: how current the data is, the bank
 * connections, and the only two data actions of the panel.
 *
 *   GET finance_dashboard/freshness    (cache read; contract: docs/dev/contracts/reprocess.md)
 *     non-admin: {as_of, last_import}
 *     admin:     + last_reprocess, processing_version, log[], validity[], derivation,
 *                data_quality[] (accounts with undated bookings)
 *   GET finance_dashboard/bank_status  (cache read) bank connections: consent,
 *                                      per-bank budget, last fetch, block, error
 *
 * Reached from the freshness icon in the Start top bar (fd-navigate
 * {target:"freshness"}). The shell frames it with <fd-subpage-header>.
 *
 * Properties: hass (required), importing / reprocessing (busy state, set by
 * the shell), reload().
 * Events (bubbling, composed):
 *   fd-refresh-requested    — "Neu importieren" (admin): the shell POSTs
 *                             /refresh {"trigger":"user_import"} (attended bank fetch)
 *   fd-reprocess-requested  — "Aktualisieren" (admin): the shell POSTs /reprocess (no bank)
 *   fd-navigate {target:"transactions"} — desktop-only link to the transaction list
 */

const DOMAIN = "finance_dashboard";

/*FB-START*/
const FB = {
  de: {
    "fr.back": "Zurück",
    "fr.title": "Aktualität",
    "fr.loading": "Wird geladen …",
    "fr.error": "Die Aktualität konnte nicht geladen werden.",
    "fr.retry": "Erneut versuchen",
    "fr.as_of": "Stand",
    "fr.last_import": "Letzter Import",
    "fr.last_reprocess": "Letzte Aufbereitung",
    "fr.version": "Verarbeitungsversion",
    "fr.never": "noch nie",
    "fr.say.fresh": "Die Daten stammen vom $time.",
    "fr.say.noimport": "Es wurde noch nichts von der Bank importiert. „Neu importieren“ holt die Umsätze.",
    "fr.import": "Neu importieren",
    "fr.reprocess": "Aktualisieren",
    "fr.log.title": "Protokoll",
    "fr.log.say": "Jeder Import und jede Aufbereitung – ohne Beträge oder Kontonummern.",
    "fr.log.empty": "Noch keine Einträge. Nach dem nächsten Import erscheint er hier.",
    "fr.log.new": "$n neu",
    "fr.log.total": "$n gesamt",
    "fr.kind.import_attended": "Import (von dir ausgelöst)",
    "fr.kind.import_scheduled": "Import (täglich automatisch)",
    "fr.kind.reprocess": "Aktualisierung (ohne Bank)",
    "fr.kind.processing_upgrade": "Automatische Neuaufbereitung nach Update",
    "fr.outcome.ok": "erfolgreich",
    "fr.outcome.partial": "teilweise",
    "fr.outcome.rate_limited": "Bank-Limit erreicht",
    "fr.outcome.error": "fehlgeschlagen",
    "fr.outcome.rebuilt": "neu aufgebaut",
    "fr.outcome.empty": "keine Rohdaten",
    "fr.outcome.unavailable": "nicht verfügbar",
    "fr.valid.title": "Stimmen die Monate?",
    "fr.valid.say": "Pro Konto und Monat: Der Saldo-Unterschied zwischen erstem und letztem Stand muss zu den Buchungen passen.",
    "fr.valid.ok": "stimmt",
    "fr.valid.gap": "Lücke $amount",
    "fr.valid.unknown": "unbekannt",
    "fr.valid.empty": "Noch nicht prüfbar – dafür braucht es mindestens zwei Saldenstände an verschiedenen Tagen eines Monats.",
    "fr.valid.more": "Weitere Monate ($n)",
    "fr.valid.gaps_one": "In einem Monat gibt es eine Lücke. Meist fehlen Buchungen aus der Zeit vor dem ersten Import.",
    "fr.valid.gaps": "In $n Monaten gibt es eine Lücke. Meist fehlen Buchungen aus der Zeit vor dem ersten Import.",
    "fr.valid.allok": "Alle geprüften Monate stimmen.",
    "fr.deriv.title": "Geht beim Auswerten etwas verloren?",
    "fr.deriv.ok": "Nein. Alle $n Buchungen sind vollständig in Kategorien und Umbuchungen eingeflossen.",
    "fr.deriv.bad": "Ja: $diff weichen ab ($ledger Buchungen im Bestand, $derived ausgewertet). „Aktualisieren“ baut alles aus den gespeicherten Rohdaten neu auf.",
    "fr.nonadmin": "Details zu Import und Prüfung sieht nur ein Administrator.",
    "fr.import_busy": "Importiert …",
    "fr.reprocess_busy": "Wird aktualisiert …",
    "fr.import_tip": "Holt neue Umsätze von der Bank",
    "fr.reprocess_tip": "Wertet die gespeicherten Daten neu aus, ohne die Bank zu fragen",
    "fr.banks.title": "Bankverbindungen",
    "fr.banks.manage": "Bank hinzufügen / verwalten",
    "fr.banks.empty": "Noch keine Bank verbunden.",
    "fr.tx.link": "Alle Transaktionen",
    "fr.ai.title": "KI-Kategorisierung",
    "fr.ai.on": "aktiv",
    "fr.ai.off": "aus",
    "fr.ai.unusable": "nicht eingerichtet",
    "fr.ai.say_on": "Händler ohne Regel ordnet $prov einer Kategorie zu. Gesendet werden nur Händlername und Verwendungszweck.",
    "fr.ai.say_off": "Die KI ist ausgeschaltet. Buchungen ohne Regel bleiben unter „Sonstiges“, bis du sie zuordnest.",
    "fr.ai.say_unusable": "Die KI ist erlaubt, aber $prov ist nicht nutzbar. In den Einstellungen kannst du die Verbindung testen.",
    "fr.ai.calls": "Aufrufe diesen Monat",
    "fr.ai.calls_v": "$calls von $cap",
    "fr.ai.learned": "Gelernte Händler",
    "fr.ai.last_run": "Letzte Zuordnung",
    "fr.ai.last_test": "Letzter Test",
    "fr.ai.ok_cat": "$cat",
    "fr.ai.failed": "fehlgeschlagen",
    "fr.ai.by_cat": "Zugeordnet nach Kategorie",
    "fr.ai.recent": "Zuletzt gelernt",
    "fr.ai.none": "Noch nichts gelernt. Neue Händler ohne Regel werden beim nächsten „Aktualisieren“ zugeordnet.",
    "fr.ai.settings": "KI-Einstellungen",
  },
  en: {
    "fr.back": "Back",
    "fr.title": "Freshness",
    "fr.loading": "Loading …",
    "fr.error": "Freshness could not be loaded.",
    "fr.retry": "Try again",
    "fr.as_of": "As of",
    "fr.last_import": "Last import",
    "fr.last_reprocess": "Last processing",
    "fr.version": "Processing version",
    "fr.never": "never",
    "fr.say.fresh": "The data is from $time.",
    "fr.say.noimport": "Nothing has been imported from the bank yet. \"Import again\" fetches the transactions.",
    "fr.import": "Import again",
    "fr.reprocess": "Refresh",
    "fr.log.title": "Log",
    "fr.log.say": "Every import and processing run – without amounts or account numbers.",
    "fr.log.empty": "No entries yet. The next import will show up here.",
    "fr.log.new": "$n new",
    "fr.log.total": "$n total",
    "fr.kind.import_attended": "Import (triggered by you)",
    "fr.kind.import_scheduled": "Import (daily, automatic)",
    "fr.kind.reprocess": "Refresh (no bank)",
    "fr.kind.processing_upgrade": "Automatic reprocessing after an update",
    "fr.outcome.ok": "succeeded",
    "fr.outcome.partial": "partly",
    "fr.outcome.rate_limited": "bank limit reached",
    "fr.outcome.error": "failed",
    "fr.outcome.rebuilt": "rebuilt",
    "fr.outcome.empty": "no raw data",
    "fr.outcome.unavailable": "unavailable",
    "fr.valid.title": "Do the months add up?",
    "fr.valid.say": "Per account and month: the balance change between first and last reading must match the bookings.",
    "fr.valid.ok": "matches",
    "fr.valid.gap": "gap $amount",
    "fr.valid.unknown": "unknown",
    "fr.valid.empty": "Not checkable yet – it needs at least two balance readings on different days of a month.",
    "fr.valid.more": "More months ($n)",
    "fr.valid.gaps_one": "One month has a gap. Usually bookings from before the first import are missing.",
    "fr.valid.gaps": "$n months have a gap. Usually bookings from before the first import are missing.",
    "fr.valid.allok": "All checked months match.",
    "fr.deriv.title": "Is anything lost while evaluating?",
    "fr.deriv.ok": "No. All $n bookings flowed completely into categories and transfers.",
    "fr.deriv.bad": "Yes: $diff differ ($ledger bookings stored, $derived evaluated). \"Refresh\" rebuilds everything from the stored raw data.",
    "fr.nonadmin": "Only an administrator sees import and check details.",
    "fr.import_busy": "Importing …",
    "fr.reprocess_busy": "Refreshing …",
    "fr.import_tip": "Fetches new transactions from the bank",
    "fr.reprocess_tip": "Re-evaluates the stored data without asking the bank",
    "fr.banks.title": "Bank connections",
    "fr.banks.manage": "Add / manage bank",
    "fr.banks.empty": "No bank connected yet.",
    "fr.tx.link": "All transactions",
    "fr.ai.title": "AI categorisation",
    "fr.ai.on": "active",
    "fr.ai.off": "off",
    "fr.ai.unusable": "not set up",
    "fr.ai.say_on": "$prov assigns merchants without a rule to a category. Only merchant name and remittance text are sent.",
    "fr.ai.say_off": "The AI is switched off. Bookings without a rule stay under \"Other\" until you assign them.",
    "fr.ai.say_unusable": "The AI is allowed, but $prov is not usable. You can test the connection in the settings.",
    "fr.ai.calls": "Calls this month",
    "fr.ai.calls_v": "$calls of $cap",
    "fr.ai.learned": "Merchants learned",
    "fr.ai.last_run": "Last assignment",
    "fr.ai.last_test": "Last test",
    "fr.ai.ok_cat": "$cat",
    "fr.ai.failed": "failed",
    "fr.ai.by_cat": "Assigned by category",
    "fr.ai.recent": "Recently learned",
    "fr.ai.none": "Nothing learned yet. New merchants without a rule are assigned on the next \"Refresh\".",
    "fr.ai.settings": "AI settings",
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
:host { display: block; }
.root { color: var(--fd-t1); font-size: 13px; line-height: 1.4; }
button { font: inherit; color: inherit; cursor: pointer; }
h3.hd { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.bk { display: flex; align-items: flex-start; gap: 10px; padding: 10px 0; }
.bk + .bk { border-top: 1px solid var(--fd-line); }
.bk .nm { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-weight: 500; overflow-wrap: anywhere; }
.bk .bf { display: flex; flex-wrap: wrap; gap: 2px 12px; margin-top: 4px; color: var(--fd-t2); font-size: 11.5px; }
.bk .bf .warn { color: var(--fd-over); }
.btn.sm { min-height: 36px; padding: 0 12px; font-size: 12px; }
.btn:disabled { opacity: .55; cursor: progress; }
.dsk-only { display: none; }
@media (hover: hover) and (pointer: fine) and (min-width: 900px) { .dsk-only { display: inline-flex; align-items: center; } }
.card { padding: 14px 16px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); margin-bottom: 12px; }
h3 { margin: 0 0 2px; font-size: 14px; font-weight: 500; }
.say { margin: 4px 0 8px; color: var(--fd-t2); font-size: 12.5px; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px 16px; margin-top: 10px; }
.facts .lab { color: var(--fd-t2); font-size: 11.5px; }
.facts .v { font-weight: 500; font-variant-numeric: tabular-nums; }
.acts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.btn { min-height: var(--fd-touch); padding: 0 16px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; }
.btn.ghost { background: transparent; color: var(--fd-a700); border-color: var(--fd-a100); }
.row { display: flex; justify-content: space-between; gap: 4px 12px; flex-wrap: wrap; padding: 8px 0; }
.row + .row { border-top: 1px solid var(--fd-line); }
.row .l { flex: 1 1 200px; min-width: 0; overflow-wrap: anywhere; }
.row .l b { font-weight: 500; display: block; }
.row .l span, .row .r span { color: var(--fd-t2); font-size: 11.5px; }
.row .r { text-align: right; }
.chip { display: inline-flex; align-items: center; padding: 1px 10px; border-radius: var(--fd-r-pill); font-size: 11.5px; font-weight: 500; white-space: nowrap; }
.chip.ok { background: var(--fd-ok-bg); color: var(--fd-ok); }
.chip.near { background: var(--fd-near-bg); color: var(--fd-near); }
.chip.over { background: var(--fd-over-bg); color: var(--fd-over); }
.chip.unk { background: var(--fd-sunk); color: var(--fd-t2); }
.card > .lab { color: var(--fd-t2); font-size: 11.5px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.acc { margin-top: 10px; font-weight: 500; overflow-wrap: anywhere; }
details { margin-top: 4px; }
summary { min-height: var(--fd-touch); display: flex; align-items: center; color: var(--fd-t2); cursor: pointer; }
.empty { color: var(--fd-t2); line-height: 1.6; }
.empty b { display: block; color: var(--fd-t1); font-weight: 500; }
.empty .btn { margin-top: 10px; }
`;

const AI_NAMES = { xai: "Grok (xAI)", anthropic: "Claude", openai: "ChatGPT" };

const OUTCOME_CLS = { ok: "ok", rebuilt: "ok", partial: "near", rate_limited: "near", empty: "unk", unavailable: "unk", error: "over" };

class FdFreshness extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._d = null;
    this._state = "loading"; // loading | ok | error
    this._seq = 0;
    this._built = false;
    this._banks = null;
    this._importing = false;
    this._reprocessing = false;
  }

  set importing(v) { this._importing = !!v; this._syncBusy(); }
  set reprocessing(v) { this._reprocessing = !!v; this._syncBusy(); }

  _syncBusy() {
    const sh = this.shadowRoot;
    const busy = this._importing || this._reprocessing;
    const imp = sh.querySelector('[data-act="import"]');
    const rep = sh.querySelector('[data-act="reprocess"]');
    if (imp) { imp.disabled = busy; imp.textContent = tr(this._importing ? "fr.import_busy" : "fr.import"); imp.setAttribute("aria-busy", String(this._importing)); }
    if (rep) { rep.disabled = busy; rep.textContent = tr(this._reprocessing ? "fr.reprocess_busy" : "fr.reprocess"); rep.setAttribute("aria-busy", String(this._reprocessing)); }
  }

  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) this.reload();
  }

  get _isAdmin() { return !!(this._hass && this._hass.user && this._hass.user.is_admin); }

  async reload() {
    if (!this._hass) return;
    const seq = ++this._seq;
    await window._fd.t("fr.title");
    if (!this._built) { this._built = true; this._bind(); }
    if (!this._d) { this._state = "loading"; this._render(); }
    try {
      const [r, b, ai] = await Promise.all([
        this._hass.callApi("GET", `${DOMAIN}/freshness`),
        this._hass.callApi("GET", `${DOMAIN}/bank_status`).catch(() => null),
        this._isAdmin ? this._hass.callApi("GET", `${DOMAIN}/setup/ai`).catch(() => null) : null,
      ]);
      if (seq !== this._seq) return;
      this._d = r || {};
      this._banks = (b && b.banks) || [];
      this._ai = ai;
      this._state = "ok";
    } catch (e) {
      if (seq !== this._seq) return;
      this._state = "error";
    }
    this._render();
  }

  _bind() {
    const sh = this.shadowRoot;
    sh.addEventListener("click", (ev) => {
      const t = ev.target.closest("[data-act]");
      if (!t) return;
      const fire = (n) => this.dispatchEvent(new CustomEvent(n, { bubbles: true, composed: true }));
      switch (t.dataset.act) {
        case "import": fire("fd-refresh-requested"); break;
        case "manage": window._fd.navigate(window._fd.INTEGRATION_PATH, ev); break;
        case "tx": this.dispatchEvent(new CustomEvent("fd-navigate", { bubbles: true, composed: true, detail: { target: "transactions" } })); break;
        case "ai": this.dispatchEvent(new CustomEvent("fd-navigate", { bubbles: true, composed: true, detail: { target: "settings", section: "ai" } })); break;
        case "reprocess": fire("fd-reprocess-requested"); break;
        case "retry": this.reload(); break;
        default: break;
      }
    });
  }

  _render() {
    if (!this._built) return;
    const { SHARED_CSS } = window._fd;
    let body;
    if (this._state === "loading") body = `<div class="card"><div class="empty">${tr("fr.loading")}</div></div>`;
    else if (this._state === "error") {
      body = `<div class="card"><div class="empty"><b>${tr("fr.error")}</b><button class="btn ghost" data-act="retry">${tr("fr.retry")}</button></div></div>`;
    } else body = this._body(this._d || {});
    this.shadowRoot.innerHTML = `<style>${SHARED_CSS}${CSS}</style><div class="root">${body}</div>`;
    this._syncBusy();
  }

  /** Bank connections: consent, today's background budget, last fetch, block, error. */
  _banksCard() {
    const { escHtml } = window._fd;
    const banks = this._banks || [];
    const manage = this._isAdmin ? `<button class="btn ghost sm" data-act="manage">${escHtml(tr("fr.banks.manage"))}</button>` : "";
    return `<div class="card"><h3 class="hd"><span>${tr("fr.banks.title")}</span>${manage}</h3>
  ${banks.length ? banks.map((b) => this._bankRow(b)).join("") : `<div class="empty">${tr("fr.banks.empty")}</div>`}</div>`;
  }

  /** AI categorisation (admin): state, monthly calls, last run/test and what was learned. */
  _aiCard() {
    const v = this._ai;
    if (!v) return "";
    const { escHtml, fmtDate, CAT_LABELS } = window._fd;
    const prov = v.provider === "ha" ? "Home Assistant" : (AI_NAMES[v.provider] || v.provider);
    const state = !v.opt_in ? "off" : v.usable === false ? "unusable" : "on";
    const cls = state === "on" ? "ok" : state === "unusable" ? "near" : "unk";
    const cat = (c) => CAT_LABELS[c] || c;
    const outcome = (o) => (!o ? tr("fr.never")
      : `${fmtDate(o.at, true)} · ${o.ok ? cat(o.category) : tr("fr.ai.failed")}`);
    const b = v.budget || {};
    const facts = [
      [tr("fr.ai.calls"), tr("fr.ai.calls_v", { calls: b.calls ?? 0, cap: b.cap ?? 0 })],
      [tr("fr.ai.learned"), String(v.cached_merchants ?? 0)],
      [tr("fr.ai.last_run"), outcome(v.last_run)],
      [tr("fr.ai.last_test"), outcome(v.last_test)],
    ];
    const res = v.results || {};
    const byCat = Object.entries(res.by_category || {});
    const recent = res.recent || [];
    const learned = byCat.length
      ? `<div class="lab" style="margin-top:12px">${escHtml(tr("fr.ai.by_cat"))}</div>
  <div class="chips">${byCat.map(([c, n]) => `<span class="chip unk">${escHtml(cat(c))} · ${n}</span>`).join("")}</div>
  <details><summary>${escHtml(tr("fr.ai.recent"))}</summary>${recent.map((r) => `<div class="row"><div class="l">${escHtml(r.merchant)}</div><div class="r"><span class="chip ok">${escHtml(cat(r.category))}</span></div></div>`).join("")}</details>`
      : `<p class="say" style="margin-bottom:0">${escHtml(tr("fr.ai.none"))}</p>`;
    return `<div class="card"><h3 class="hd"><span>${tr("fr.ai.title")} <span class="chip ${cls}">${escHtml(tr("fr.ai." + state))}</span></span>
    <button class="btn ghost sm" data-act="ai">${escHtml(tr("fr.ai.settings"))}</button></h3>
  <p class="say">${escHtml(tr("fr.ai.say_" + state, { prov }))}</p>
  <div class="facts">${facts.map(([l, x]) => `<div><div class="lab">${escHtml(l)}</div><div class="v">${escHtml(x)}</div></div>`).join("")}</div>
  ${state === "off" ? "" : learned}</div>`;
  }

  _bankRow(b) {
    const { escHtml, fmtDate } = window._fd;
    const state = b.consent_state || "ok";
    const until = fmtDate(b.consent_valid_until);
    let consent;
    if (state === "expired") consent = tr("fr.bank.consent_expired", { date: until });
    else if (state === "expiring") consent = tr("fr.bank.consent_expiring", { date: until });
    else if (until) consent = tr("fr.bank.consent_ok", { date: until });
    else consent = tr("fr.bank.consent_unknown");
    const badge = tr(`fr.bank.badge_${state === "expired" || state === "expiring" ? state : "ok"}`);
    const cls = state === "expired" ? "over" : state === "expiring" ? "near" : "ok";
    const blocked = b.blocked_until && new Date(b.blocked_until) > new Date();
    const facts = [
      `<span>${escHtml(consent)}</span>`,
      `<span>${escHtml(tr("fr.bank.budget", { used: b.budget_used_today ?? 0, limit: b.budget_limit ?? 4 }))}</span>`,
    ];
    // Manual fetches are uncapped, so the background budget never counts them.
    if (b.last_attended_at) facts.push(`<span>${escHtml(tr("fr.bank.last_manual", { date: fmtDate(b.last_attended_at, true) }))}</span>`);
    if (blocked) facts.push(`<span class="warn">${escHtml(tr("fr.bank.blocked", { date: fmtDate(b.blocked_until, true) }))}</span>`);
    if (b.last_success) facts.push(`<span>${escHtml(tr("fr.bank.last_success", { date: fmtDate(b.last_success, true) }))}</span>`);
    if (b.last_error) facts.push(`<span class="warn">${escHtml(tr("fr.bank.last_error", { error: b.last_error }))}</span>`);
    const renew = state === "ok" || !this._isAdmin ? "" : `<button class="btn sm" data-act="manage">${escHtml(tr("fr.bank.renew"))}</button>`;
    return `<div class="bk"><div style="min-width:0;flex:1">
    <div class="nm">${escHtml(b.title || "Bank")} <span class="chip ${cls}">${escHtml(badge)}</span></div>
    <div class="bf">${facts.join("")}</div></div>${renew}</div>`;
  }

  _body(d) {
    const { escHtml, eur, fmtDate } = window._fd;
    const when = (iso) => (iso ? fmtDate(iso, true) : tr("fr.never"));
    const admin = this._isAdmin;
    const say = d.last_import ? tr("fr.say.fresh", { time: when(d.as_of) }) : tr("fr.say.noimport");
    const facts = [
      [tr("fr.as_of"), when(d.last_import ? d.as_of : null)],
      [tr("fr.last_import"), when(d.last_import)],
    ];
    if (admin) {
      facts.push([tr("fr.last_reprocess"), when(d.last_reprocess)]);
      if (d.processing_version != null) facts.push([tr("fr.version"), String(d.processing_version)]);
    }
    let h = `<div class="card"><h3>${tr("fr.as_of")}</h3><p class="say">${escHtml(say)}</p>
  <div class="facts">${facts.map(([l, v]) => `<div><div class="lab">${escHtml(l)}</div><div class="v">${escHtml(v)}</div></div>`).join("")}</div>
  ${admin ? `<div class="acts"><button class="btn" data-act="import" data-tip="${escHtml(tr("fr.import_tip"))}">${tr("fr.import")}</button><button class="btn ghost" data-act="reprocess" data-tip="${escHtml(tr("fr.reprocess_tip"))}">${tr("fr.reprocess")}</button>
    <button class="btn ghost dsk-only" data-act="tx">${tr("fr.tx.link")}</button></div>` : ""}</div>`;
    h += this._banksCard();
    if (!admin) return h + `<div class="card"><div class="empty">${tr("fr.nonadmin")}</div></div>`;
    h += this._aiCard();

    // Log
    const log = d.log || [];
    const rows = log.map((e) => {
      const kind = tr("fr.kind." + e.kind);
      const kindTxt = kind === "fr.kind." + e.kind ? e.kind : kind;
      const oc = tr("fr.outcome." + e.outcome);
      const ocTxt = oc === "fr.outcome." + e.outcome ? (e.outcome || "") : oc;
      const meta = [
        (e.banks || []).length ? e.banks.join(", ") : "",
        e.new != null ? tr("fr.log.new", { n: e.new }) : "",
        e.total != null ? tr("fr.log.total", { n: e.total }) : "",
        e.duration_ms != null ? `${(e.duration_ms / 1000).toFixed(1)} s` : "",
      ].filter(Boolean).join(" · ");
      return `<div class="row"><div class="l"><b>${escHtml(kindTxt)}</b><span>${escHtml(fmtDate(e.at, true))}${meta ? " · " + escHtml(meta) : ""}</span></div>
  <div class="r"><span class="chip ${OUTCOME_CLS[e.outcome] || "unk"}">${escHtml(ocTxt)}</span></div></div>`;
    });
    h += `<div class="card"><h3>${tr("fr.log.title")}</h3><p class="say">${tr("fr.log.say")}</p>
  ${rows.length ? rows.slice(0, 8).join("") + (rows.length > 8 ? `<details><summary>${escHtml(tr("fr.valid.more", { n: rows.length - 8 }))}</summary>${rows.slice(8).join("")}</details>` : "")
    : `<div class="empty">${tr("fr.log.empty")}</div>`}</div>`;

    // Validity per account
    const val = d.validity || [];
    const byAcc = new Map();
    for (const v of val) { if (!byAcc.has(v.account_name)) byAcc.set(v.account_name, []); byAcc.get(v.account_name).push(v); }
    const lang = (window._fd._hass && window._fd._hass.language) || navigator.language || "de";
    const mfmt = (m) => new Date(m + "-01T00:00:00").toLocaleDateString(lang, { month: "long", year: "numeric" });
    const vrow = (v) => {
      const cls = v.status === "ok" ? "ok" : v.status === "gap" ? "near" : "unk";
      const txt = v.status === "ok" ? tr("fr.valid.ok") : v.status === "gap" ? tr("fr.valid.gap", { amount: eur(Math.abs(v.diff || 0)) }) : tr("fr.valid.unknown");
      return `<div class="row"><div class="l">${escHtml(mfmt(v.month))}</div><div class="r"><span class="chip ${cls}">${escHtml(txt)}</span></div></div>`;
    };
    const gaps = val.filter((v) => v.status === "gap").length;
    const vsum = !val.length ? "" : gaps ? tr(gaps === 1 ? "fr.valid.gaps_one" : "fr.valid.gaps", { n: gaps }) : val.some((v) => v.status === "ok") ? tr("fr.valid.allok") : "";
    const vbody = [...byAcc.entries()].map(([acc, list]) => `<div class="acc">${escHtml(acc)}</div>${list.slice(0, 3).map(vrow).join("")}
  ${list.length > 3 ? `<details><summary>${escHtml(tr("fr.valid.more", { n: list.length - 3 }))}</summary>${list.slice(3).map(vrow).join("")}</details>` : ""}`).join("");
    h += `<div class="card"><h3>${tr("fr.valid.title")}</h3><p class="say">${escHtml(vsum || tr("fr.valid.say"))}</p>
  ${val.length ? vbody : `<div class="empty">${tr("fr.valid.empty")}</div>`}</div>`;

    // Data quality: bookings without any date never reach cycles or contracts
    const dq = d.data_quality || [];
    if (dq.length) {
      const rows = dq.map((q) => `<div class="row"><div class="l">${escHtml(q.account_name)}</div>
  <div class="r"><span class="chip near">${escHtml(tr("fr.dq.count", { n: q.undated, total: q.total }))}</span></div></div>`).join("");
      h += `<div class="card"><h3>${tr("fr.dq.title")}</h3><p class="say">${tr("fr.dq.say")}</p>${rows}</div>`;
    }

    // Derivation check
    const dv = d.derivation;
    if (dv && (dv.ledger_count || !dv.ok)) {
      const txt = dv.ok ? tr("fr.deriv.ok", { n: dv.ledger_count ?? 0 })
        : tr("fr.deriv.bad", { diff: eur(Math.abs(dv.diff || 0)), ledger: dv.ledger_count ?? 0, derived: dv.derived_count ?? 0 });
      h += `<div class="card"><h3>${tr("fr.deriv.title")} <span class="chip ${dv.ok ? "ok" : "near"}">${escHtml(dv.ok ? tr("fr.valid.ok") : eur(Math.abs(dv.diff || 0)))}</span></h3>
  <p class="say" style="margin-bottom:0">${escHtml(txt)}</p></div>`;
    }
    return h;
  }
}

window._fd.defineOnce("fd-freshness", FdFreshness);
