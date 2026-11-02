/**
 * fd-history-import — optional import of older booking history (admin only).
 *
 *   GET  finance_dashboard/history_import                 {allowed, accounts[{key,name,iban_masked}], batches[], ai{usable,consented,remaining}}
 *   POST history_import/preview                           {content_base64, account_key, use_ai?} -> preview | {needs_ai, calls, ai}
 *   POST history_import/commit                            {preview_id} -> {batch_id, added}
 *   POST history_import/undo                              {batch_id}
 *   GET/PUT setup/ai/consents                             purpose "history_import" (one-time)
 *
 * CSV / XLSX / PDF statements are read on the server without any AI. Only a file the local reader cannot map
 * is offered to the AI, after the user agreed to this purpose. Rows are shown before saving;
 * every imported batch can be removed again as a whole.
 *
 * Embedded by <fd-settings> (section "history"). Properties: hass (required).
 * Events (bubbling, composed): fd-toast {message, type}
 */

const DOMAIN = "finance_dashboard";

const FB = {
  de: {
    "hist.intro": "Die Bank liefert nur etwa 90 Tage. Mit einer Exportdatei (CSV oder XLSX) oder Kontoauszügen als PDF aus deinem Online-Banking kannst du 13 bis 24 Monate nachladen, damit auch Jahresverträge erkannt werden. Optional, du siehst vorher, was importiert wird, und kannst es als Ganzes rückgängig machen.",
    "hist.account": "Konto",
    "hist.pick": "Datei wählen",
    "hist.file_hint": "CSV, XLSX oder PDF-Kontoauszug, höchstens 5 MB. Die Datei wird lokal gelesen.",
    "hist.busy": "Lese Datei …",
    "hist.unavailable": "Im Demo-Modus oder ohne beschreibbaren Speicher nicht verfügbar.",
    "hist.no_accounts": "Verbinde zuerst ein Konto.",
    "hist.load_error": "Import konnte nicht geladen werden.",
    "hist.needs_ai.title": "Datei nicht lokal lesbar",
    "hist.needs_ai.body": "Die Spalten wurden nicht erkannt. Die KI kann die Datei lesen. Dafür wird ihr Inhalt (auch Beträge und Daten, IBANs vorher lokal maskiert) an deinen KI-Anbieter gesendet. Das braucht $calls Aufruf(e) deines Monatsbudgets, $left sind übrig.",
    "hist.needs_ai.go": "Zustimmen und mit KI lesen",
    "hist.needs_ai.go_granted": "Mit KI lesen",
    "hist.needs_ai.no_provider": "Es ist keine KI eingerichtet (Einstellungen, KI).",
    "hist.needs_ai.budget": "Das Monatsbudget reicht nicht für $calls Aufruf(e).",
    "hist.cancel": "Abbrechen",
    "hist.preview": "Vorschau",
    "hist.method.local": "lokal gelesen",
    "hist.method.ai": "mit KI gelesen",
    "hist.sum.new": "neu: $n",
    "hist.sum.duplicate": "schon vorhanden: $n",
    "hist.sum.overlap": "im Bankzeitraum: $n",
    "hist.sum.invalid": "ungültig: $n",
    "hist.status.new": "neu",
    "hist.status.duplicate": "Duplikat",
    "hist.status.overlap": "Bankdaten gelten",
    "hist.col.date": "Datum",
    "hist.col.party": "Name",
    "hist.col.amount": "Betrag",
    "hist.col.status": "Status",
    "hist.truncated": "Nur die ersten Zeilen werden angezeigt, alle werden importiert.",
    "hist.rule": "Wo die Bank selbst Buchungen liefert, gelten ihre Daten. Duplikate und Zeilen im Bankzeitraum werden nicht importiert.",
    "hist.invalid.title": "Ungültige Zeilen ($n), werden nicht importiert",
    "hist.invalid.line": "Zeile $line",
    "hist.reason.bad_date": "Datum nicht lesbar",
    "hist.reason.date_out_of_range": "Datum in der Zukunft oder über 10 Jahre alt",
    "hist.reason.bad_amount": "Betrag nicht lesbar",
    "hist.reason.amount_out_of_range": "Betrag 0 oder unplausibel",
    "hist.reason.bad_currency": "Währung unbekannt",
    "hist.reason.no_description": "Weder Name noch Verwendungszweck",
    "hist.reason.not_an_object": "Keine Buchung",
    "hist.commit": "$n Buchungen importieren",
    "hist.nothing": "Es gibt nichts Neues zu importieren.",
    "hist.done": "$n Buchungen importiert",
    "hist.batches": "Importiert",
    "hist.batch": "$n Buchungen, $first bis $last",
    "hist.batch_on": "am $date, $method",
    "hist.undo": "Rückgängig",
    "hist.undo_confirm": "Wirklich alle $n Buchungen entfernen?",
    "hist.undone": "Import rückgängig gemacht",
    "hist.err.generic": "Import fehlgeschlagen",
    "hist.err.pdf_encrypted": "Die PDF ist passwortgeschützt. Speichere den Auszug ohne Passwort oder exportiere als CSV.",
    "hist.err.pdf_no_text": "Die PDF enthält keinen Text (eingescannt?). Exportiere die Buchungen als CSV oder XLSX.",
    "hist.err.pdf_unavailable": "PDF kann auf diesem System nicht gelesen werden. Exportiere als CSV.",
    "hist.err.too_large": "Die Datei ist größer als 5 MB.",
    "hist.err.empty": "Die Datei ist leer.",
    "hist.err.unreadable": "Die Datei konnte nicht gelesen werden.",
    "hist.err.too_many_rows": "Die Datei hat zu viele Zeilen.",
    "hist.err.too_large_for_ai": "Die Datei ist für die KI zu groß. Teile sie in kleinere Dateien.",
    "hist.err.consent_required": "Ohne Zustimmung wird nichts an die KI gesendet.",
    "hist.err.no_provider": "Es ist keine KI eingerichtet.",
    "hist.err.budget_exhausted": "Monatsbudget der KI aufgebraucht.",
    "hist.err.unparsable": "Die KI-Antwort war nicht lesbar.",
    "hist.err.no_key": "Kein API-Schlüssel gespeichert.",
    "hist.err.import_unavailable": "Import ist gerade nicht möglich.",
    "hist.err.preview_expired": "Die Vorschau ist abgelaufen. Datei erneut wählen.",
    "hist.err.unknown_account": "Dieses Konto gibt es nicht mehr.",
    "hist.err.nothing_to_import": "Es gibt nichts Neues zu importieren.",
    "hist.err.unknown_batch": "Dieser Import ist nicht mehr vorhanden.",
    "hist.err.xlsx_unavailable": "XLSX kann auf diesem System nicht gelesen werden. Exportiere als CSV.",
    "hist.err.too_many_columns": "Die Datei hat zu viele Spalten.",
    "ai.purpose.history_import.title": "Buchungshistorie importieren",
  },
  en: {
    "hist.intro": "The bank serves only about 90 days. An export file (CSV or XLSX) or a PDF statement from your online banking lets you add 13 to 24 months, so yearly contracts are found too. Optional: you see what will be imported first and can undo it as a whole.",
    "hist.account": "Account",
    "hist.pick": "Choose file",
    "hist.file_hint": "CSV, XLSX or a PDF statement, at most 5 MB. The file is read locally.",
    "hist.busy": "Reading file …",
    "hist.unavailable": "Not available in demo mode or without writable storage.",
    "hist.no_accounts": "Connect an account first.",
    "hist.load_error": "The import could not be loaded.",
    "hist.needs_ai.title": "File not readable locally",
    "hist.needs_ai.body": "The columns were not recognised. The AI can read the file. For that its content (including amounts and dates, IBANs masked locally first) is sent to your AI provider. It needs $calls call(s) of your monthly budget, $left left.",
    "hist.needs_ai.go": "Agree and read with AI",
    "hist.needs_ai.go_granted": "Read with AI",
    "hist.needs_ai.no_provider": "No AI is set up (Settings, AI).",
    "hist.needs_ai.budget": "The monthly budget does not cover $calls call(s).",
    "hist.cancel": "Cancel",
    "hist.preview": "Preview",
    "hist.method.local": "read locally",
    "hist.method.ai": "read with AI",
    "hist.sum.new": "new: $n",
    "hist.sum.duplicate": "already there: $n",
    "hist.sum.overlap": "in bank period: $n",
    "hist.sum.invalid": "invalid: $n",
    "hist.status.new": "new",
    "hist.status.duplicate": "duplicate",
    "hist.status.overlap": "bank data wins",
    "hist.col.date": "Date",
    "hist.col.party": "Name",
    "hist.col.amount": "Amount",
    "hist.col.status": "Status",
    "hist.truncated": "Only the first rows are shown; all are imported.",
    "hist.rule": "Where the bank delivers bookings itself, its data wins. Duplicates and rows inside the bank period are not imported.",
    "hist.invalid.title": "Invalid rows ($n), not imported",
    "hist.invalid.line": "Row $line",
    "hist.reason.bad_date": "date unreadable",
    "hist.reason.date_out_of_range": "date in the future or over 10 years old",
    "hist.reason.bad_amount": "amount unreadable",
    "hist.reason.amount_out_of_range": "amount 0 or implausible",
    "hist.reason.bad_currency": "unknown currency",
    "hist.reason.no_description": "neither name nor purpose",
    "hist.reason.not_an_object": "not a booking",
    "hist.commit": "Import $n bookings",
    "hist.nothing": "Nothing new to import.",
    "hist.done": "$n bookings imported",
    "hist.batches": "Imported",
    "hist.batch": "$n bookings, $first to $last",
    "hist.batch_on": "on $date, $method",
    "hist.undo": "Undo",
    "hist.undo_confirm": "Really remove all $n bookings?",
    "hist.undone": "Import undone",
    "hist.err.generic": "Import failed",
    "hist.err.pdf_encrypted": "The PDF is password protected. Save the statement without a password or export as CSV.",
    "hist.err.pdf_no_text": "The PDF holds no text (scanned?). Export the bookings as CSV or XLSX.",
    "hist.err.pdf_unavailable": "PDF cannot be read on this system. Export as CSV.",
    "hist.err.too_large": "The file is larger than 5 MB.",
    "hist.err.empty": "The file is empty.",
    "hist.err.unreadable": "The file could not be read.",
    "hist.err.too_many_rows": "The file has too many rows.",
    "hist.err.too_large_for_ai": "The file is too large for the AI. Split it into smaller files.",
    "hist.err.consent_required": "Nothing is sent to the AI without consent.",
    "hist.err.no_provider": "No AI is set up.",
    "hist.err.budget_exhausted": "Monthly AI budget used up.",
    "hist.err.unparsable": "The AI answer could not be read.",
    "hist.err.no_key": "No API key stored.",
    "hist.err.import_unavailable": "Import is not possible right now.",
    "hist.err.preview_expired": "The preview expired. Choose the file again.",
    "hist.err.unknown_account": "This account no longer exists.",
    "hist.err.nothing_to_import": "Nothing new to import.",
    "hist.err.unknown_batch": "This import no longer exists.",
    "hist.err.xlsx_unavailable": "XLSX cannot be read on this system. Export as CSV.",
    "hist.err.too_many_columns": "The file has too many columns.",
    "ai.purpose.history_import.title": "Import booking history",
  },
};

function tr(key, vars = {}) {
  let s = window._fd.tSync(key, vars);
  if (s !== key) return s;
  const raw = ((window._fd._hass && window._fd._hass.language) || navigator.language || "en").toLowerCase();
  s = (FB[raw.startsWith("de") ? "de" : "en"][key]) || key;
  for (const [k, v] of Object.entries(vars)) s = s.replace(new RegExp(`\\$${k}`, "g"), String(v));
  return s;
}

const MAX_BYTES = 5 * 1024 * 1024;
const EUR = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

const CSS = `
:host { display: block; min-width: 0; }
.root { color: var(--fd-t1); font-size: 13px; line-height: 1.4; min-width: 0; }
button, select { font: inherit; color: inherit; cursor: pointer; }
.muted { color: var(--fd-t2); font-size: 11.5px; margin: 0 0 8px; overflow-wrap: anywhere; }
.note { padding: 12px; border-radius: 10px; background: var(--fd-sunk); color: var(--fd-t2); font-size: 12.5px; margin: 8px 0; overflow-wrap: anywhere; }
.note h4 { margin: 0 0 4px; color: var(--fd-t1); font-size: 13px; }
.note ul { margin: 4px 0 0; padding-left: 18px; }
.f { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; min-width: 0; }
.f > label { color: var(--fd-t2); font-size: 11.5px; }
select { box-sizing: border-box; min-height: var(--fd-touch); padding: 0 10px; border-radius: 10px; border: 1px solid var(--fd-line); background: var(--fd-card); max-width: 100%; }
.btn { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; min-height: var(--fd-touch); padding: 0 16px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; }
.btn.ghost { background: transparent; color: var(--fd-a700); border-color: var(--fd-a100); }
.btn.sm { min-height: 36px; padding: 0 12px; font-size: 12px; }
.btn:disabled { opacity: .5; cursor: default; }
.btn:focus-visible, select:focus-visible { outline: 2px solid var(--fd-a700); outline-offset: 2px; }
.acts { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
input[type=file] { position: absolute; width: 1px; height: 1px; opacity: 0; overflow: hidden; }
.err { color: var(--fd-over); font-size: 12px; overflow-wrap: anywhere; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.chip { display: inline-flex; align-items: center; padding: 2px 10px; border-radius: var(--fd-r-pill); font-size: 11.5px; font-weight: 500; background: var(--fd-a50); color: var(--fd-a900); }
.chip.warn { background: var(--fd-sunk); color: var(--fd-over); }
.scroll { max-height: 340px; overflow: auto; border: 1px solid var(--fd-line); border-radius: 10px; }
table { border-collapse: collapse; width: 100%; font-size: 12px; }
th, td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--fd-line); vertical-align: top; }
th { position: sticky; top: 0; background: var(--fd-card); color: var(--fd-t2); font-weight: 500; }
td.amt, th.amt { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.party { overflow-wrap: anywhere; min-width: 90px; }
tr.duplicate td, tr.overlap td { color: var(--fd-t3); }
.inv { margin: 6px 0; padding-left: 18px; font-size: 12px; overflow-wrap: anywhere; }
.row { display: flex; align-items: center; gap: 10px; min-height: var(--fd-touch); padding: 6px 0; flex-wrap: wrap; }
.row + .row { border-top: 1px solid var(--fd-line); }
.row .who { flex: 1 1 160px; min-width: 0; display: flex; flex-direction: column; }
.row .who span { color: var(--fd-t2); font-size: 11.5px; }
@media (max-width: 480px) { .col-party-hide { display: none; } }
`;

class FdHistoryImport extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._info = null;
    this._account = "";
    this._file = null; // data URL of the chosen file, kept for the AI retry
    this._busy = false;
    this._preview = null;
    this._needsAi = null;
    this._purposes = null;
    this._err = "";
    this._done = "";
    this._undoArm = "";
    this._wired = false;
  }

  get hass() { return this._hass; }
  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    window._fd._hass = window._fd._hass || h;
    if (first) this._load();
  }

  get _isAdmin() { return !!(this._hass && this._hass.user && this._hass.user.is_admin); }
  _api(method, path, body) { return this._hass.callApi(method, `${DOMAIN}/${path}`, body); }
  _toast(message, type = "success") {
    this.dispatchEvent(new CustomEvent("fd-toast", { detail: { message, type }, bubbles: true, composed: true }));
  }

  _errText(e) {
    const code = e && e.body && e.body.error;
    const key = code ? `hist.err.${code}` : "";
    const t = key ? tr(key) : key;
    return t && t !== key ? t : tr("hist.err.generic");
  }

  async _load() {
    if (!this._isAdmin) return this._render();
    try {
      this._info = await this._api("GET", "history_import");
      if (!this._account && this._info.accounts.length) this._account = this._info.accounts[0].key;
    } catch (e) {
      console.warn("fd-history-import: load failed:", e);
      this._loadFailed = true;
    }
    this._render();
  }

  // ---- actions -------------------------------------------------------------
  _pickFile(file) {
    if (!file) return;
    if (file.size > MAX_BYTES) { this._err = tr("hist.err.too_large"); this._render(); return; }
    const reader = new FileReader();
    reader.onload = () => { this._file = String(reader.result || ""); this._runPreview(false); };
    reader.onerror = () => { this._err = tr("hist.err.unreadable"); this._render(); };
    reader.readAsDataURL(file);
  }

  async _runPreview(useAi) {
    this._busy = true; this._err = ""; this._done = ""; this._preview = null; this._needsAi = null;
    this._render();
    try {
      const res = await this._api("POST", "history_import/preview",
        { content_base64: this._file, account_key: this._account, use_ai: !!useAi });
      if (res.needs_ai) {
        this._needsAi = res;
        if (!this._purposes) {
          try { this._purposes = (await this._api("GET", "setup/ai/consents")).purposes || {}; } catch (e) { this._purposes = {}; }
        }
      } else {
        this._preview = res;
      }
    } catch (e) {
      this._err = this._errText(e);
      // the file stays; re-ask what the AI would need now (the one-time consent may be spent)
      if (useAi) await this._refreshNeedsAi();
    }
    this._busy = false;
    this._render();
  }

  async _refreshNeedsAi() {
    try {
      const res = await this._api("POST", "history_import/preview",
        { content_base64: this._file, account_key: this._account, use_ai: false });
      if (res.needs_ai) this._needsAi = res;
    } catch (e) { /* the error above is the one to show */ }
  }

  async _agreeAndRead() {
    const ai = (this._needsAi || {}).ai || {};
    if (!ai.consented) {
      try { await this._api("PUT", "setup/ai/consents", { purpose: "history_import", granted: true }); }
      catch (e) { this._err = this._errText(e); return this._render(); }
    }
    await this._runPreview(true);
  }

  async _commit() {
    if (!this._preview || this._busy) return;
    this._busy = true; this._err = ""; this._render();
    try {
      const res = await this._api("POST", "history_import/commit", { preview_id: this._preview.preview_id });
      this._done = tr("hist.done", { n: res.added });
      this._toast(this._done);
      this._preview = null; this._file = null;
      this._info = await this._api("GET", "history_import");
    } catch (e) { this._err = this._errText(e); }
    this._busy = false;
    this._render();
  }

  async _undo(id) {
    if (this._undoArm !== id) { this._undoArm = id; return this._render(); }
    this._undoArm = ""; this._busy = true; this._err = ""; this._render();
    try {
      await this._api("POST", "history_import/undo", { batch_id: id });
      this._toast(tr("hist.undone"));
      this._info = await this._api("GET", "history_import");
    } catch (e) { this._err = this._errText(e); }
    this._busy = false;
    this._render();
  }

  _cancel() {
    this._undoArm = "";
    this._preview = null; this._needsAi = null; this._file = null; this._err = ""; this._render();
  }

  // ---- render --------------------------------------------------------------
  _render() {
    const sh = this.shadowRoot;
    const { escHtml } = window._fd;
    if (!this._isAdmin) { sh.innerHTML = ""; return; }
    let body;
    if (this._loadFailed) body = `<p class="err" role="alert">${escHtml(tr("hist.load_error"))}</p>`;
    else if (!this._info) body = `<p class="muted" role="status">${escHtml(tr("hist.busy"))}</p>`;
    else body = this._body();
    const focus = this._focusKey();
    this._rendering = true;
    sh.innerHTML = `<style>${window._fd.SHARED_CSS}${CSS}</style><div class="root">${body}</div>`;
    this._restoreFocus(focus);
    this._rendering = false;
    if (!this._wired) { this._wired = true; this._wire(); }
  }

  /** Selector of the control that has keyboard focus, so a re-render can give it back. */
  _focusKey() {
    const el = this.shadowRoot.activeElement;
    if (!el) return "";
    if (el.id) return `#${el.id}`;
    for (const a of ["data-pick", "data-agree", "data-commit", "data-cancel"]) if (el.hasAttribute && el.hasAttribute(a)) return `[${a}]`;
    if (el.dataset && el.dataset.undo) return `[data-undo="${el.dataset.undo}"]`;
    return "";
  }

  _restoreFocus(key) {
    if (!key) return;
    const el = this.shadowRoot.querySelector(key)
      || this.shadowRoot.querySelector("[data-pick]");  // the control is gone (e.g. after commit): the start of the flow
    if (el && !el.disabled) el.focus();
  }

  _body() {
    const { escHtml } = window._fd;
    const info = this._info;
    let html = `<p class="muted">${escHtml(tr("hist.intro"))}</p>`;
    if (!info.allowed) return html + `<p class="note">${escHtml(tr("hist.unavailable"))}</p>`;
    if (!info.accounts.length) return html + `<p class="note">${escHtml(tr("hist.no_accounts"))}</p>`;
    const opts = info.accounts.map((a) =>
      `<option value="${escHtml(a.key)}" ${a.key === this._account ? "selected" : ""}>${escHtml(a.name)} ${escHtml(a.iban_masked)}</option>`).join("");
    html += `<div class="f"><label for="hist-acc">${escHtml(tr("hist.account"))}</label><select id="hist-acc" ${this._busy ? "disabled" : ""}>${opts}</select></div>
      <div class="acts"><button type="button" class="btn" data-pick ${this._busy ? "disabled aria-busy=\"true\"" : ""}>${escHtml(tr(this._busy ? "hist.busy" : "hist.pick"))}</button>
      <input type="file" id="hist-file" accept=".csv,.xlsx,.pdf,.txt,.tsv,text/csv,application/pdf" tabindex="-1" aria-hidden="true"></div>
      <p class="muted">${escHtml(tr("hist.file_hint"))}</p>`;
    if (this._err) html += `<p class="err" role="alert">${escHtml(this._err)}</p>`;
    if (this._done) html += `<p class="chip" role="status">${escHtml(this._done)}</p>`;
    if (this._needsAi) html += this._aiBlock();
    if (this._preview) html += this._previewBlock();
    html += this._batchesBlock();
    return html;
  }

  _aiBlock() {
    const { escHtml } = window._fd;
    const n = this._needsAi, ai = n.ai || {};
    const meta = (this._purposes || {}).history_import || { pros: [], risks: [] };
    const list = (keys) => `<ul>${(keys || []).map((k) => `<li>${escHtml(tr(k))}</li>`).join("")}</ul>`;
    let action;
    if (!ai.usable) action = `<p class="err" role="alert">${escHtml(tr("hist.needs_ai.no_provider"))}</p>`;
    else if (ai.remaining < n.calls) action = `<p class="err" role="alert">${escHtml(tr("hist.needs_ai.budget", { calls: n.calls }))}</p>`;
    else action = `<button type="button" class="btn" data-agree ${this._busy ? "disabled" : ""}>${escHtml(tr(ai.consented ? "hist.needs_ai.go_granted" : "hist.needs_ai.go"))}</button>`;
    return `<div class="note" role="group" aria-label="${escHtml(tr("hist.needs_ai.title"))}"><h4>${escHtml(tr("hist.needs_ai.title"))}</h4>
      ${escHtml(tr("hist.needs_ai.body", { calls: n.calls, left: ai.remaining ?? 0 }))}
      <h4 style="margin-top:8px">${escHtml(tr("settings.ai.pros"))}</h4>${list(meta.pros)}
      <h4 style="margin-top:8px">${escHtml(tr("settings.ai.risks"))}</h4>${list(meta.risks)}</div>
      <div class="acts">${action}<button type="button" class="btn ghost" data-cancel>${escHtml(tr("hist.cancel"))}</button></div>`;
  }

  _previewBlock() {
    const { escHtml, fmtDate } = window._fd;
    const p = this._preview, s = p.summary;
    const chips = ["new", "duplicate", "overlap"].map((k) => `<span class="chip">${escHtml(tr(`hist.sum.${k}`, { n: s[k] }))}</span>`).join("")
      + (s.invalid ? `<span class="chip warn">${escHtml(tr("hist.sum.invalid", { n: s.invalid }))}</span>` : "");
    const rows = p.rows.map((r) => `<tr class="${escHtml(r.status)}"><td>${escHtml(fmtDate ? fmtDate(r.date) : r.date)}</td>
      <td class="party">${escHtml(r.counterparty || r.text)}</td><td class="amt">${escHtml(EUR.format(r.amount))}</td>
      <td>${escHtml(tr(`hist.status.${r.status}`))}</td></tr>`).join("");
    const table = p.rows.length ? `<div class="scroll" tabindex="0" role="region" aria-label="${escHtml(tr("hist.preview"))}"><table>
      <thead><tr><th>${escHtml(tr("hist.col.date"))}</th><th>${escHtml(tr("hist.col.party"))}</th><th class="amt">${escHtml(tr("hist.col.amount"))}</th><th>${escHtml(tr("hist.col.status"))}</th></tr></thead>
      <tbody>${rows}</tbody></table></div>${p.rows_truncated ? `<p class="muted">${escHtml(tr("hist.truncated"))}</p>` : ""}` : "";
    const inv = p.invalid.length ? `<h4>${escHtml(tr("hist.invalid.title", { n: s.invalid }))}</h4><ul class="inv">${p.invalid.map((i) =>
      `<li>${escHtml(tr("hist.invalid.line", { line: i.line }))}: ${escHtml(tr(`hist.reason.${i.reason}`))}</li>`).join("")}</ul>` : "";
    const can = s.new > 0 && !this._busy;
    return `<h4>${escHtml(tr("hist.preview"))} <span class="chip">${escHtml(tr(`hist.method.${p.method}`))}</span></h4>
      <div class="chips">${chips}</div><p class="muted">${escHtml(tr("hist.rule"))}</p>${table}${inv}
      ${s.new ? "" : `<p class="note">${escHtml(tr("hist.nothing"))}</p>`}
      <div class="acts"><button type="button" class="btn" data-commit ${can ? "" : "disabled"}>${escHtml(tr("hist.commit", { n: s.new }))}</button>
      <button type="button" class="btn ghost" data-cancel>${escHtml(tr("hist.cancel"))}</button></div>`;
  }

  _batchesBlock() {
    const { escHtml, fmtDate } = window._fd;
    const list = this._info.batches || [];
    if (!list.length) return "";
    const rows = list.map((b) => {
      const armed = this._undoArm === b.id;
      return `<div class="row"><div class="who"><b>${escHtml(tr("hist.batch", { n: b.count, first: fmtDate ? fmtDate(b.first) : b.first, last: fmtDate ? fmtDate(b.last) : b.last }))}</b>
        <span>${escHtml(tr("hist.batch_on", { date: fmtDate ? fmtDate(b.at, true) : b.at, method: tr(`hist.method.${b.method}`) }))}</span></div>
        <button type="button" class="btn ghost sm" data-undo="${escHtml(b.id)}" ${this._busy ? "disabled" : ""}>${escHtml(armed ? tr("hist.undo_confirm", { n: b.count }) : tr("hist.undo"))}</button></div>`;
    }).join("");
    return `<h4>${escHtml(tr("hist.batches"))}</h4>${rows}`;
  }

  _wire() {
    const sh = this.shadowRoot;
    sh.addEventListener("click", (ev) => {
      const t = ev.target.closest("button");
      if (this._undoArm && !(t && t.dataset.undo === this._undoArm)) { this._undoArm = ""; this._render(); }
      if (!t || t.disabled) return;
      if (t.hasAttribute("data-pick")) sh.getElementById("hist-file")?.click();
      else if (t.hasAttribute("data-agree")) this._agreeAndRead();
      else if (t.hasAttribute("data-commit")) this._commit();
      else if (t.hasAttribute("data-cancel")) this._cancel();
      else if (t.dataset.undo) this._undo(t.dataset.undo);
    });
    sh.addEventListener("focusout", (ev) => {
      // keyboard leaves the armed undo button: disarm (but not while the render itself moves focus)
      if (this._undoArm && ev.target.dataset && ev.target.dataset.undo === this._undoArm && !this._rendering
          && !(ev.relatedTarget && ev.relatedTarget === ev.target)) { this._undoArm = ""; this._render(); }
    });
    sh.addEventListener("change", (ev) => {
      if (ev.target.id === "hist-acc") { this._account = ev.target.value; this._preview = null; this._needsAi = null; }
      else if (ev.target.id === "hist-file") {
        const f = ev.target.files && ev.target.files[0];
        ev.target.value = "";
        this._pickFile(f);
      }
    });
  }
}

if (!customElements.get("fd-history-import")) customElements.define("fd-history-import", FdHistoryImport);
