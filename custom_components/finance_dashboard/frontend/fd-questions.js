/**
 * fd-questions — open questions as flash cards (admin only).
 *
 *   GET  finance_dashboard/questions
 *     {questions:[{id,merchant,count,total,dates:[iso],booking_ids,suggested:[cat],
 *        bookings:[{date,amount,account,counterparty,iban_last4,text}],
 *        history:{count,first,last,months}|null}],
 *      questions_open, questions_total, answered_total, week_answered,
 *      points, points_every}
 *     Contract cards (#117) come first and carry `type`:
 *       "contract" {series_id, merchant, interval, count, monthly, dates, reasons, suggested_kind}
 *       "price"    {series_id, merchant, interval, previous, last, change_pct, date}
 *   POST finance_dashboard/questions/answer
 *     {id, category, reach:"merchant"|"booking", owner?}
 *     {id, type:"contract", answer:"contract"|"subscription"|"regular"|"coincidence"}
 *     {id, type:"price", answer:"new_price"|"one_off"}
 *     -> {answered_total, week_answered, point_awarded}
 *   GET  finance_dashboard/assignments  -> persons[].name (optional owner chips)
 *   GET  finance_dashboard/questions/history
 *     {items:[{merchant,category,owner,source:"user"|"ai"}] newest first,
 *      total, by_user, by_ai, bookings}  ("Verlauf" tab, loaded on first open)
 *
 * One card per merchant, three suggested categories as big buttons, "other
 * category" opens the full picker. Reach defaults to the whole merchant.
 * Progress: the API awards one point per `points_every` answers (7), so the
 * counter shows the distance to the next point from those counters.
 * No undo: the API cannot take an answer back, so none is offered.
 *
 * Properties: hass.
 * Events (bubbling, composed):
 *   fd-questions-close     back to Start (the shell closes the view)
 *   fd-questions-all       desktop: open the full drag & drop categoriser
 */

const DOMAIN = "finance_dashboard";
const WEEK_CAP = 10;
const PERSON_COLORS = ["var(--fd-person-a)", "var(--fd-person-b)", "#ef6c00", "#5e35b1", "#6d4c41"];

const FB = {
  de: {
    "questions.c_kind": "Wiederkehrende Zahlung",
    "questions.c_prompt": "Vertrag, Abo, regelmäßige Ausgabe oder Zufall?",
    "questions.c_payments": "$n Zahlungen",
    "questions.c_monthly": "etwa $sum pro Monat",
    "questions.c_contract": "Vertrag",
    "questions.c_subscription": "Abo",
    "questions.c_regular": "Regelmäßige Ausgabe",
    "questions.c_coincidence": "Zufall",
    "questions.price_kind": "Preisänderung",
    "questions.price_step": "Von $previous auf $last",
    "questions.price_prompt": "Neuer Preis oder einmaliger Betrag?",
    "questions.price_new": "Neuer Preis",
    "questions.price_once": "Einmaliger Betrag",
    "questions.iv_weekly": "wöchentlich",
    "questions.iv_monthly": "monatlich",
    "questions.iv_quarterly": "vierteljährlich",
    "questions.iv_half_yearly": "halbjährlich",
    "questions.iv_yearly": "jährlich",
    "questions.title": "Fragen",
    "questions.back": "Zurück zum Start",
    "questions.card_of": "Karte $n von $m",
    "questions.bookings": "$n Buchungen",
    "questions.booking_one": "1 Buchung",
    "questions.total": "zusammen $sum",
    "questions.dates": "zuletzt $dates",
    "questions.prompt": "Wohin gehört das?",
    "questions.other": "Andere Kategorie",
    "questions.other_hide": "Weniger",
    "questions.owner": "Wem gehört es?",
    "questions.owner_none": "Wie das Konto",
    "questions.owner_shared": "Haushalt",
    "questions.reach": "Gilt für",
    "questions.reach_booking": "Nur diese Buchung",
    "questions.reach_merchant": "Alle von $merchant",
    "questions.reach_booking_n": "Nur diese $n Buchungen",
    "questions.history": "Insgesamt $n× seit $first, in $m Monaten",
    "questions.history_one": "Bisher nur dieses eine Mal",
    "questions.details": "Buchungen anzeigen",
    "questions.details_hide": "Buchungen ausblenden",
    "questions.no_text": "kein Verwendungszweck",
    "questions.skip": "Später",
    "questions.skip_hint": "Zur Seite wischen = später",
    "questions.progress_point": "Noch $n Antworten bis zum nächsten Punkt",
    "questions.progress_point_one": "Noch 1 Antwort bis zum nächsten Punkt",
    "questions.progress_week": "Diese Woche: $n von $m",
    "questions.points": "Punkte: $n",
    "questions.err": "Das hat nicht geklappt. Versuch es gleich noch einmal.",
    "questions.err_unavailable": "Fragen sind im Demo-Modus nicht verfügbar.",
    "questions.err_admin": "Nur Administratoren können Fragen beantworten.",
    "questions.load_error": "Die Fragen konnten nicht geladen werden.",
    "questions.retry": "Nochmal laden",
    "questions.done_title": "Alles erledigt",
    "questions.done_body": "Im Moment gibt es nichts mehr zu klären. Neue Fragen kommen, sobald neue Buchungen offen sind.",
    "questions.done_week": "Diese Woche geschafft",
    "questions.done_week_body": "$n Antworten, die Kategorien werden mit jeder Antwort treffsicherer.",
    "questions.point_title": "Punkt verdient!",
    "questions.point_body": "Danke, dass du Ordnung ins Haushaltsbuch bringst.",
    "questions.continue": "Weiter",
    "questions.all": "Alle Buchungen kategorisieren",
    "questions.denied": "Fragen sind nur für Administratoren sichtbar.",
    "questions.tab_open": "Offen",
    "questions.tab_history": "Verlauf",
    "questions.hist_say": "$n Händler zugeordnet: $user von dir, $ai von der KI. Dazu $b einzelne Buchungen.",
    "questions.hist_all": "Alle",
    "questions.hist_user": "Von dir",
    "questions.hist_ai": "Von der KI",
    "questions.hist_src_user": "du",
    "questions.hist_src_ai": "KI",
    "questions.hist_empty": "Noch keine Kategorisierungen. Jede Antwort und jeder KI-Vorschlag landet hier.",
    "questions.hist_more": "Ältere ($n)",
    "questions.rf_prompt": "Gehört diese Erstattung zu dieser Ausgabe?",
    "questions.rf_paid": "Erstattet: $sum",
    "questions.rf_confirm": "Ja, passt",
    "questions.rf_other": "Andere Ausgabe",
    "questions.rf_no": "Nein, keine Erstattung",
    "questions.rf_pick": "Welche Ausgaben hat sie erstattet?",
    "questions.rf_send": "Zuordnen",
    "questions.rf_none": "Keine passenden Ausgaben gefunden.",
    "questions.rf_back": "Zurück",
  },
  en: {
    "questions.c_kind": "Recurring payment",
    "questions.c_prompt": "Contract, subscription, regular spending or coincidence?",
    "questions.c_payments": "$n payments",
    "questions.c_monthly": "about $sum per month",
    "questions.c_contract": "Contract",
    "questions.c_subscription": "Subscription",
    "questions.c_regular": "Regular spending",
    "questions.c_coincidence": "Coincidence",
    "questions.price_kind": "Price change",
    "questions.price_step": "From $previous to $last",
    "questions.price_prompt": "New price or a one-off amount?",
    "questions.price_new": "New price",
    "questions.price_once": "One-off amount",
    "questions.iv_weekly": "weekly",
    "questions.iv_monthly": "monthly",
    "questions.iv_quarterly": "quarterly",
    "questions.iv_half_yearly": "half-yearly",
    "questions.iv_yearly": "yearly",
    "questions.title": "Questions",
    "questions.back": "Back to Start",
    "questions.card_of": "Card $n of $m",
    "questions.bookings": "$n bookings",
    "questions.booking_one": "1 booking",
    "questions.total": "$sum in total",
    "questions.dates": "latest $dates",
    "questions.prompt": "Where does this belong?",
    "questions.other": "Other category",
    "questions.other_hide": "Fewer",
    "questions.owner": "Who owns it?",
    "questions.owner_none": "Like the account",
    "questions.owner_shared": "Household",
    "questions.reach": "Applies to",
    "questions.reach_booking": "Only this booking",
    "questions.reach_merchant": "All from $merchant",
    "questions.reach_booking_n": "Only these $n bookings",
    "questions.history": "$n× in total since $first, in $m months",
    "questions.history_one": "Only this once so far",
    "questions.details": "Show bookings",
    "questions.details_hide": "Hide bookings",
    "questions.no_text": "no remittance text",
    "questions.skip": "Later",
    "questions.skip_hint": "Swipe aside = later",
    "questions.progress_point": "$n more answers until the next point",
    "questions.progress_point_one": "1 more answer until the next point",
    "questions.progress_week": "This week: $n of $m",
    "questions.points": "Points: $n",
    "questions.err": "That did not work. Please try again in a moment.",
    "questions.err_unavailable": "Questions are not available in demo mode.",
    "questions.err_admin": "Only administrators can answer questions.",
    "questions.load_error": "The questions could not be loaded.",
    "questions.retry": "Load again",
    "questions.done_title": "All done",
    "questions.done_body": "Nothing left to clarify right now. New questions appear when new bookings are open.",
    "questions.done_week": "Done for this week",
    "questions.done_week_body": "$n answers, categories get more accurate with every one.",
    "questions.point_title": "Point earned!",
    "questions.point_body": "Thanks for keeping the household book in order.",
    "questions.continue": "Continue",
    "questions.all": "Categorise all bookings",
    "questions.denied": "Questions are only visible to administrators.",
    "questions.tab_open": "Open",
    "questions.tab_history": "History",
    "questions.hist_say": "$n merchants assigned: $user by you, $ai by the AI. Plus $b single bookings.",
    "questions.hist_all": "All",
    "questions.hist_user": "By you",
    "questions.hist_ai": "By the AI",
    "questions.hist_src_user": "you",
    "questions.hist_src_ai": "AI",
    "questions.hist_empty": "No categorisations yet. Every answer and every AI suggestion shows up here.",
    "questions.hist_more": "Older ($n)",
    "questions.rf_prompt": "Does this refund belong to this expense?",
    "questions.rf_paid": "Refunded: $sum",
    "questions.rf_confirm": "Yes, that fits",
    "questions.rf_other": "Another expense",
    "questions.rf_no": "No, not a refund",
    "questions.rf_pick": "Which expenses did it pay back?",
    "questions.rf_send": "Assign",
    "questions.rf_none": "No matching expenses found.",
    "questions.rf_back": "Back",
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

const CSS = `
:host { display: block; }
.root { color: var(--fd-t1); font-size: 14px; line-height: 1.4; max-width: 560px; margin: 0 auto; padding: 8px 12px 24px; box-sizing: border-box; }
button { font: inherit; color: inherit; cursor: pointer; }
button:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
.bar { display: flex; align-items: center; gap: 8px; min-height: var(--fd-touch); }
.bar h2 { flex: 1; margin: 0; font-size: 18px; font-weight: 500; }
.ghost { min-height: var(--fd-touch); min-width: var(--fd-touch); padding: 0 14px; border: 0; border-radius: var(--fd-r-pill); background: transparent; color: var(--fd-a700); font-weight: 500; }
.ghost:hover { background: var(--fd-a50); }
.prog { margin: 4px 0 12px; padding: 10px 12px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); }
.prog .row { display: flex; justify-content: space-between; gap: 8px; font-size: 12.5px; color: var(--fd-t2); }
.prog .row b { color: var(--fd-t1); font-weight: 500; white-space: nowrap; }
.meter { height: 8px; margin-top: 8px; border-radius: var(--fd-r-pill); background: var(--fd-sunk); overflow: hidden; }
.meter > i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--fd-a300), var(--fd-gold)); transition: width .5s ease; }
.pips { display: flex; gap: 4px; margin-top: 6px; }
.pips i { flex: 1; height: 4px; border-radius: 2px; background: var(--fd-sunk); }
.pips i.on { background: var(--fd-a500); }
.stage { position: relative; touch-action: pan-y; }
.card { padding: 18px 16px 12px; border-radius: 20px; background: var(--fd-card); box-shadow: var(--fd-sh2); transition: transform .25s ease, opacity .25s ease; user-select: none; }
.card.leave { opacity: 0; transform: translateX(-60px) rotate(-3deg); }
.card.enter { animation: enter .3s ease; }
@keyframes enter { from { opacity: 0; transform: translateY(14px) scale(.98); } to { opacity: 1; transform: none; } }
.cnt { font-size: 12px; color: var(--fd-t2); }
.merchant { margin: 2px 0 4px; font-size: 22px; font-weight: 500; overflow-wrap: anywhere; }
.facts { color: var(--fd-t2); font-size: 13px; }
.facts b { color: var(--fd-t1); font-weight: 500; }
.hist { margin-top: 4px; color: var(--fd-t2); font-size: 12.5px; }
.bk { margin: 10px 0 0; padding: 0; list-style: none; border-top: 1px solid var(--fd-line); }
.bk li { padding: 8px 0; border-bottom: 1px solid var(--fd-line); font-size: 13px; }
.bk .l1 { display: flex; justify-content: space-between; gap: 8px; }
.bk .l1 b { font-weight: 500; font-variant-numeric: tabular-nums; white-space: nowrap; }
.bk .flow { color: var(--fd-t1); overflow-wrap: anywhere; }
.bk .l2 { color: var(--fd-t2); font-size: 12px; overflow-wrap: anywhere; margin-top: 2px; }
.bk .l2.none { color: var(--fd-t3); font-style: italic; }
.toggle { margin-top: 6px; min-height: var(--fd-touch); padding: 0; border: 0; background: transparent; color: var(--fd-a700); font-weight: 500; font-size: 13px; }
.prompt { margin: 16px 0 8px; font-weight: 500; }
.cats { display: grid; gap: 8px; }
.cat { display: flex; align-items: center; gap: 12px; width: 100%; min-height: 56px; padding: 0 16px; border: 1px solid var(--fd-line); border-radius: 14px; background: var(--fd-sunk); text-align: left; font-size: 16px; }
.cat:hover:not(:disabled) { border-color: var(--fd-a300); background: var(--fd-a50); }
.cat:active:not(:disabled) { transform: scale(.985); }
.cat:disabled { opacity: .6; cursor: default; }
.cat .ic { font-size: 22px; width: 28px; text-align: center; }
.cat .dot { width: 8px; height: 28px; border-radius: 4px; flex: none; }
.cat kbd { margin-left: auto; display: none; min-width: 20px; padding: 1px 6px; border: 1px solid var(--fd-line); border-radius: 6px; background: var(--fd-card); color: var(--fd-t2); font: 11px/16px inherit; text-align: center; opacity: 0; transition: opacity .15s .4s; }
@media (hover: hover) { .cat kbd { display: inline-block; } .cat:hover kbd, .cat:focus-visible kbd { opacity: 1; } }
.picker { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; margin-top: 8px; }
.picker .cat { min-height: 48px; font-size: 14px; padding: 0 12px; }
.more { margin-top: 8px; width: 100%; min-height: var(--fd-touch); border: 1px dashed var(--fd-line); border-radius: 14px; background: transparent; color: var(--fd-a700); font-weight: 500; }
.more:hover { background: var(--fd-a50); }
.sub { margin: 16px 0 6px; font-size: 12.5px; color: var(--fd-t2); }
.seg { display: flex; flex-wrap: wrap; gap: 6px; }
.seg button { min-height: var(--fd-touch); padding: 0 14px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: var(--fd-card); }
.bk .cat { width: 100%; height: auto; padding: 8px 10px; text-align: left; display: block; }
.bk .cat[aria-pressed=true] { background: var(--fd-a100); border-color: var(--fd-a500); }
.seg button[aria-pressed=true] { background: var(--fd-a100); border-color: var(--fd-a500); font-weight: 500; }
.seg .pd { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }
.foot { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; gap: 8px; color: var(--fd-t3); font-size: 12px; }
.msg { margin: 12px 0 0; padding: 10px 12px; border-radius: 12px; background: var(--fd-over-bg); font-size: 13px; }
.center { text-align: center; padding: 36px 16px; border-radius: 20px; background: var(--fd-card); box-shadow: var(--fd-sh1); }
.center h3 { margin: 12px 0 6px; font-size: 20px; font-weight: 500; }
.center p { margin: 0 auto 16px; max-width: 34ch; color: var(--fd-t2); }
.big { font-size: 56px; line-height: 1; color: var(--fd-ok); }
.primary { min-height: var(--fd-touch); padding: 0 22px; border: 0; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; }
.primary:hover { background: var(--fd-a900); }
.desk { display: none; margin-top: 10px; text-align: center; }
@media (hover: hover) and (min-width: 900px) { .desk { display: block; } }
.celebrate { position: fixed; inset: 0; z-index: 70; display: flex; align-items: center; justify-content: center; background: color-mix(in srgb, var(--fd-t1) 45%, transparent); padding: 16px; overflow: hidden; }
.celebrate .center { position: relative; width: min(380px, 100%); box-sizing: border-box; animation: pop .5s cubic-bezier(.2,1.4,.4,1); }
.star { display: inline-block; font-size: 72px; line-height: 1; color: var(--fd-gold); animation: spin 1.1s ease-out; filter: drop-shadow(0 4px 10px rgba(249,168,37,.5)); }
@keyframes pop { from { transform: scale(.6); opacity: 0; } to { transform: none; opacity: 1; } }
@keyframes spin { from { transform: rotate(-200deg) scale(.2); } to { transform: none; } }
.confetti { position: absolute; top: -16px; width: 9px; height: 14px; border-radius: 2px; opacity: .9; animation: fall linear forwards; }
@keyframes fall { to { transform: translateY(110vh) rotate(540deg); } }
.tabs { margin: 0 0 10px; }
.hlist { padding: 4px 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); }
.hrow { display: flex; align-items: center; gap: 8px; padding: 9px 0; border-bottom: 1px solid var(--fd-line); font-size: 13.5px; }
.hrow:last-child { border-bottom: 0; }
.hrow .m { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.hrow .m small { display: block; color: var(--fd-t2); font-size: 11.5px; }
.hrow .ch { flex: none; padding: 1px 10px; border-radius: var(--fd-r-pill); background: var(--fd-sunk); font-size: 12px; font-weight: 500; white-space: nowrap; }
.hrow .src { flex: none; min-width: 26px; padding: 1px 6px; border-radius: 6px; font-size: 11px; text-align: center; color: var(--fd-t2); border: 1px solid var(--fd-line); }
.hrow .src.ai { color: var(--fd-a700); border-color: var(--fd-a300); }
.hsay { margin: 0 0 8px; color: var(--fd-t2); font-size: 12.5px; }
.hlist details summary { min-height: var(--fd-touch); display: flex; align-items: center; color: var(--fd-a700); font-weight: 500; cursor: pointer; }
.load { padding: 40px; text-align: center; color: var(--fd-t2); }
@media (prefers-reduced-motion: reduce) {
  .card, .meter > i { transition: none; }
  .card.enter, .celebrate .center, .star { animation: none; }
  .confetti { display: none; }
}
`;

const CONFETTI = ["#f9a825", "#00897b", "#c2185b", "#0277bd", "#7e57c2", "#ef6c00"];

class FdQuestions extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._q = [];
    this._rfOther = false;
    this._rfPick = new Set();
    this._meta = { answered_total: 0, week_answered: 0, points: 0, points_every: 7 };
    this._state = "loading"; // loading | ready | error | denied
    this._i = 0;
    this._reach = "merchant";
    this._owner = "";
    this._more = false;
    this._details = true;
    this._busy = false;
    this._msg = "";
    this._persons = [];
    this._session = 0;
    this._celebrate = null; // null | "point" | "week"
    this._tab = "open"; // open | history
    this._hist = null;  // history payload, loaded on first open of the tab
    this._hfilter = "all";
    this._onKey = (e) => this._key(e);
    this._onNav = (e) => {
      if (e.detail && e.detail.target === "back" && e.composedPath()[0] !== this) this._close();
    };
  }

  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) this.load();
  }

  connectedCallback() {
    this.addEventListener("keydown", this._onKey);
    // The shared header's back arrow (and Esc) bubbles as fd-navigate {target:"back"};
    // keep the long-standing fd-questions-close event alongside it for the shell.
    this.addEventListener("fd-navigate", this._onNav);
  }
  disconnectedCallback() {
    this.removeEventListener("keydown", this._onKey);
    this.removeEventListener("fd-navigate", this._onNav);
    clearTimeout(this._skipTimer);
  }

  get _isAdmin() { return !!(this._hass && this._hass.user && this._hass.user.is_admin); }

  async load() {
    if (!this._hass) return;
    this._state = "loading";
    this._render();
    if (!this._isAdmin) { this._state = "denied"; this._render(); return; }
    await window._fd.t("questions.title");
    try {
      const d = await this._hass.callApi("GET", `${DOMAIN}/questions`);
      this._q = d.questions || [];
      this._meta = {
        answered_total: d.answered_total || 0,
        week_answered: d.week_answered || 0,
        points: d.points || 0,
        points_every: d.points_every || 7,
      };
      this._i = 0;
      this._session = 0;
      this._state = "ready";
      this._resetCard();
      this._hass.callApi("GET", `${DOMAIN}/assignments`)
        .then((a) => { this._persons = (a.persons || []).map((p) => p.name); this._keepRender(); })
        .catch(() => {});
    } catch (e) {
      console.warn("fd-questions: load failed:", e);
      this._state = "error";
    }
    this._render();
  }

  _resetCard() { this._reach = "merchant"; this._owner = ""; this._more = false; this._msg = ""; this._rfOther = false; this._rfPick = new Set(); }

  /** Refund card (#119): "does this refund belong to <expense>?" with confirm / other / no. */
  _refundCardHtml() {
    const { eur, escHtml } = window._fd;
    const c = this._card;
    const day = (d) => escHtml(this._fmtDay(d));
    const line = (b) => `<div class="l1"><span class="flow">${day(b.date)} · ${escHtml(b.party || b.description || "")}</span><b>${escHtml(eur(Math.abs(b.amount)))}</b></div>`;
    const dis = this._busy ? "disabled" : "";
    let body;
    if (this._rfOther) {
      const rows = [...c.proposed, ...c.others];
      body = `<div class="prompt">${tr("questions.rf_pick")}</div>
  ${rows.length ? `<ul class="bk" role="group" aria-label="${tr("questions.rf_pick")}">${rows.map((b) => `<li><button class="cat" data-rfpick="${escHtml(b.id)}" aria-pressed="${this._rfPick.has(b.id)}" ${dis}>${line(b)}</button></li>`).join("")}</ul>` : `<p class="muted">${tr("questions.rf_none")}</p>`}
  <div class="cats"><button class="cat" data-rf="send" ${dis || !this._rfPick.size ? "disabled" : ""}>${tr("questions.rf_send")}</button>
  <button class="cat" data-rf="back" ${dis}>${tr("questions.rf_back")}</button></div>`;
    } else {
      body = `<ul class="bk">${c.proposed.map((b) => `<li>${line(b)}${b.refunded != null ? `<div class="l2">${escHtml(tr("questions.rf_paid", { sum: eur(b.refunded) }))}</div>` : ""}</li>`).join("")}</ul>
  <div class="prompt">${tr("questions.rf_prompt")}</div>
  <div class="cats"><button class="cat" data-rf="confirm" ${dis}>${tr("questions.rf_confirm")}</button>
  <button class="cat" data-rf="other" ${dis}>${tr("questions.rf_other")}</button>
  <button class="cat" data-rf="no" ${dis}>${tr("questions.rf_no")}</button></div>`;
    }
    return `<div class="card enter" id="card">
  <div class="cnt">${tr("questions.card_of", { n: this._i + 1, m: this._q.length })}</div>
  <h3 class="merchant">${escHtml(c.merchant)}</h3>
  <div class="facts"><b>${escHtml(eur(c.refund.amount))}</b> · ${day(c.refund.date)}</div>
  ${c.refund.description ? `<div class="hist">${escHtml(c.refund.description)}</div>` : ""}
  ${body}
  ${this._msg ? `<div class="msg" role="alert">${escHtml(this._msg)}</div>` : ""}
  <div class="foot"><span>${tr("questions.skip_hint")}</span><button class="ghost" data-act="skip" ${this._q.length < 2 ? "hidden" : ""}>${tr("questions.skip")}</button></div>
</div>`;
  }

  get _card() { return this._q[this._i]; }

  _cats(card) {
    const { CAT_LABELS } = window._fd;
    return (card.suggested || []).filter((c) => CAT_LABELS[c] && c !== "other").slice(0, 3);
  }

  _catBtn(c, key) {
    const { CAT_LABELS, CAT_ICONS, CAT_COLORS, escHtml } = window._fd;
    const ic = CAT_ICONS && CAT_ICONS[c];
    return `<button class="cat" data-cat="${escHtml(c)}" ${this._busy ? "disabled" : ""}>${ic ? `<span class="ic" aria-hidden="true">${ic}</span>` : `<span class="dot" style="background:${CAT_COLORS[c] || "#6b7280"}"></span>`}<span>${escHtml(CAT_LABELS[c] || c)}</span>${key ? `<kbd aria-hidden="true">${key}</kbd>` : ""}</button>`;
  }

  _fmtDates(dates) {
    const f = new Intl.DateTimeFormat((this._hass && this._hass.language) || "de", { day: "numeric", month: "short" });
    return (dates || []).slice(0, 3).map((d) => { const x = new Date(d); return isNaN(x) ? d : f.format(x); }).join(", ");
  }

  _fmtDay(d, withYear) {
    const x = new Date(d);
    if (isNaN(x)) return d;
    const opt = withYear ? { month: "short", year: "numeric" } : { day: "numeric", month: "short" };
    return new Intl.DateTimeFormat((this._hass && this._hass.language) || "de", opt).format(x);
  }

  /** History line + the card's bookings: own account → counterparty, amount, remittance text. */
  _detailsHtml(c) {
    const { eur, escHtml } = window._fd;
    const h = c.history;
    let hist = "";
    if (h && h.count > c.count) hist = tr("questions.history", { n: h.count, first: this._fmtDay(h.first, true), m: h.months });
    else if (h && h.count === 1) hist = tr("questions.history_one");
    const rows = c.bookings || [];
    if (!rows.length) return hist ? `<div class="hist">${escHtml(hist)}</div>` : "";
    const list = this._details ? `<ul class="bk">${rows.map((b) => {
      const to = b.counterparty || c.merchant;
      const flow = `${b.account ? `${escHtml(b.account)} → ` : ""}${escHtml(to)}${b.iban_last4 ? ` (…${escHtml(b.iban_last4)})` : ""}`;
      return `<li><div class="l1"><span class="flow">${flow}</span><b>${escHtml(eur(b.amount))}</b></div>
        <div class="l2${b.text ? "" : " none"}">${escHtml(this._fmtDay(b.date))} · ${escHtml(b.text || tr("questions.no_text"))}</div></li>`;
    }).join("")}</ul>` : "";
    return `${hist ? `<div class="hist">${escHtml(hist)}</div>` : ""}${list}
  <button class="toggle" data-act="details" aria-expanded="${this._details}">${tr(this._details ? "questions.details_hide" : "questions.details")}</button>`;
  }

  _progressHtml() {
    const m = this._meta;
    const every = m.points_every || 7;
    const into = m.answered_total % every;
    const left = every - into;
    const week = Math.min(m.week_answered, WEEK_CAP);
    return `<div class="prog" aria-live="polite">
  <div class="row"><span>${left === 1 ? tr("questions.progress_point_one") : tr("questions.progress_point", { n: left })}</span><b>★ ${tr("questions.points", { n: m.points })}</b></div>
  <div class="meter" role="progressbar" aria-valuemin="0" aria-valuemax="${every}" aria-valuenow="${into}"><i style="width:${(into / every) * 100}%"></i></div>
  <div class="row" style="margin-top:8px"><span>${tr("questions.progress_week", { n: week, m: WEEK_CAP })}</span></div>
  <div class="pips" aria-hidden="true">${Array.from({ length: WEEK_CAP }, (_, k) => `<i class="${k < week ? "on" : ""}"></i>`).join("")}</div>
</div>`;
  }

  /** Answer buttons of a contract card (#117 B, G): [value, label key, icon]. */
  _contractOptions(c) {
    if (c.type === "price") return [["new_price", "questions.price_new", "↗"], ["one_off", "questions.price_once", "①"]];
    return [["contract", "questions.c_contract", "📄"], ["subscription", "questions.c_subscription", "🔁"],
      ["regular", "questions.c_regular", "🛒"], ["coincidence", "questions.c_coincidence", "🎲"]];
  }

  _contractCardHtml(c) {
    const { eur, escHtml } = window._fd;
    const iv = tr(`questions.iv_${c.interval}`);
    let facts, prompt;
    if (c.type === "price") {
      const pct = c.change_pct != null ? ` (${c.change_pct > 0 ? "+" : ""}${String(c.change_pct).replace(".", ",")} %)` : "";
      facts = `${escHtml(tr("questions.price_step", { previous: eur(Math.abs(c.previous)), last: eur(Math.abs(c.last)) }))}${escHtml(pct)} · ${escHtml(this._fmtDates([c.date]))}`;
      prompt = tr("questions.price_prompt");
    } else {
      facts = `<b>${escHtml(tr("questions.c_payments", { n: c.count }))}</b> · ${escHtml(iv)} · ${escHtml(tr("questions.c_monthly", { sum: eur(c.monthly) }))}${c.dates && c.dates.length ? ` · ${tr("questions.dates", { dates: escHtml(this._fmtDates(c.dates)) })}` : ""}`;
      prompt = tr("questions.c_prompt");
    }
    const btns = this._contractOptions(c).map(([v, key, ic], n) =>
      `<button class="cat" data-ans="${v}" ${this._busy ? "disabled" : ""}><span class="ic" aria-hidden="true">${ic}</span><span>${escHtml(tr(key))}</span><kbd aria-hidden="true">${n + 1}</kbd></button>`).join("");
    return `<div class="card enter" id="card">
  <div class="cnt">${tr("questions.card_of", { n: this._i + 1, m: this._q.length })} · ${escHtml(tr(c.type === "price" ? "questions.price_kind" : "questions.c_kind"))}</div>
  <h3 class="merchant">${escHtml(c.merchant)}</h3>
  <div class="facts">${facts}</div>
  <div class="prompt">${escHtml(prompt)}</div>
  <div class="cats">${btns}</div>
  ${this._msg ? `<div class="msg" role="alert">${escHtml(this._msg)}</div>` : ""}
  <div class="foot"><span>${tr("questions.skip_hint")}</span><button class="ghost" data-act="skip" ${this._q.length < 2 ? "hidden" : ""}>${tr("questions.skip")}</button></div>
</div>`;
  }

  _cardHtml() {
    const { eur, escHtml, CAT_LABELS } = window._fd;
    const c = this._card;
    if (c.kind === "refund") return this._refundCardHtml();
    if (c.type === "contract" || c.type === "price") return this._contractCardHtml(c);
    const cats = this._cats(c);
    const people = this._persons;
    const credit = Number(c.total) > 0;
    const rest = Object.keys(CAT_LABELS).filter((k) => (k !== "other" && k !== "transfers") && String(k).startsWith("income") === credit);
    return `<div class="card enter" id="card">
  <div class="cnt">${tr("questions.card_of", { n: this._i + 1, m: this._q.length })}</div>
  <h3 class="merchant">${escHtml(c.merchant)}</h3>
  <div class="facts"><b>${c.count === 1 ? tr("questions.booking_one") : tr("questions.bookings", { n: c.count })}</b> · ${tr("questions.total", { sum: eur(c.total) })}${c.dates && c.dates.length ? ` · ${tr("questions.dates", { dates: escHtml(this._fmtDates(c.dates)) })}` : ""}</div>
  ${this._detailsHtml(c)}
  <div class="prompt">${tr("questions.prompt")}</div>
  <div class="cats">${cats.map((k, n) => this._catBtn(k, String(n + 1))).join("")}</div>
  <button class="more" data-act="more" aria-expanded="${this._more}">${this._more ? tr("questions.other_hide") : tr("questions.other")}</button>
  ${this._more ? `<div class="picker">${rest.map((k) => this._catBtn(k)).join("")}</div>` : ""}
  <div class="sub">${tr("questions.reach")}</div>
  <div class="seg" role="group" aria-label="${tr("questions.reach")}">
    <button data-reach="merchant" aria-pressed="${this._reach === "merchant"}">${tr("questions.reach_merchant", { merchant: escHtml(c.merchant) })}</button>
    <button data-reach="booking" aria-pressed="${this._reach === "booking"}">${c.count > 1 ? tr("questions.reach_booking_n", { n: c.count }) : tr("questions.reach_booking")}</button>
  </div>
  ${people.length ? `<div class="sub">${tr("questions.owner")}</div>
  <div class="seg" role="group" aria-label="${tr("questions.owner")}">
    <button data-owner="" aria-pressed="${this._owner === ""}">${tr("questions.owner_none")}</button>
    ${people.map((p, n) => `<button data-owner="${escHtml(p)}" aria-pressed="${this._owner === p}"><span class="pd" style="background:${PERSON_COLORS[n % 5]}"></span>${escHtml(p)}</button>`).join("")}
    <button data-owner="shared" aria-pressed="${this._owner === "shared"}"><span class="pd" style="background:var(--fd-household)"></span>${tr("questions.owner_shared")}</button>
  </div>` : ""}
  ${this._msg ? `<div class="msg" role="alert">${escHtml(this._msg)}</div>` : ""}
  <div class="foot"><span>${tr("questions.skip_hint")}</span><button class="ghost" data-act="skip" ${this._q.length < 2 ? "hidden" : ""}>${tr("questions.skip")}</button></div>
</div>`;
  }

  _doneHtml() {
    return `<div class="center"><div class="big" aria-hidden="true">✓</div><h3>${tr("questions.done_title")}</h3><p>${tr("questions.done_body")}</p>
<button class="primary" data-act="close">${tr("questions.back")}</button></div>`;
  }

  _celebrateHtml() {
    const week = this._celebrate === "week";
    const pieces = Array.from({ length: 36 }, (_, k) =>
      `<span class="confetti" style="left:${(k * 37) % 100}%;background:${CONFETTI[k % CONFETTI.length]};animation-duration:${2.2 + (k % 5) * 0.4}s;animation-delay:${(k % 7) * 0.12}s"></span>`).join("");
    const more = this._i < this._q.length && !week;
    return `<div class="celebrate" role="dialog" aria-modal="true" aria-label="${tr(week ? "questions.done_week" : "questions.point_title")}">${pieces}
<div class="center"><span class="star" aria-hidden="true">${week ? "🎉" : "★"}</span>
<h3>${tr(week ? "questions.done_week" : "questions.point_title")}</h3>
<p>${week ? tr("questions.done_week_body", { n: this._session }) : tr("questions.point_body")}</p>
<button class="primary" data-act="${more ? "continue" : "close"}" id="celebrateBtn">${more ? tr("questions.continue") : tr("questions.back")}</button></div></div>`;
  }

  _tabsHtml() {
    const b = (id, key) => `<button data-tab="${id}" aria-pressed="${this._tab === id}">${tr(key)}</button>`;
    return `<div class="seg tabs" role="group">${b("open", "questions.tab_open")}${b("history", "questions.tab_history")}</div>`;
  }

  async _openHistory() {
    this._tab = "history";
    this._render();
    try {
      this._hist = await this._hass.callApi("GET", `${DOMAIN}/questions/history`);
    } catch (e) {
      console.warn("fd-questions: history failed:", e);
      this._hist = { error: true };
    }
    if (this._tab === "history") this._render();
  }

  /** "Verlauf": every learned merchant, newest first, filterable by who assigned it. */
  _historyHtml() {
    const { escHtml, CAT_LABELS } = window._fd;
    const h = this._hist;
    if (!h) return `<div class="load">…</div>`;
    if (h.error) return `<div class="center"><p>${tr("questions.load_error")}</p><button class="primary" data-act="history">${tr("questions.retry")}</button></div>`;
    if (!h.total && !h.bookings) return `<div class="center"><p>${tr("questions.hist_empty")}</p></div>`;
    const f = this._hfilter;
    const items = (h.items || []).filter((i) => f === "all" || i.source === f);
    const fb = (id, key) => `<button data-hfilter="${id}" aria-pressed="${f === id}">${tr(key)}</button>`;
    const row = (i) => `<div class="hrow"><span class="src ${i.source}">${tr(i.source === "ai" ? "questions.hist_src_ai" : "questions.hist_src_user")}</span>
  <span class="m">${escHtml(i.merchant)}${i.owner ? `<small>${escHtml(i.owner === "shared" ? tr("questions.owner_shared") : i.owner)}</small>` : ""}</span>
  <span class="ch">${escHtml(CAT_LABELS[i.category] || i.category || "")}</span></div>`;
    const head = items.slice(0, 40).map(row).join("");
    const rest = items.length > 40 ? `<details><summary>${tr("questions.hist_more", { n: items.length - 40 })}</summary>${items.slice(40).map(row).join("")}</details>` : "";
    return `<p class="hsay">${escHtml(tr("questions.hist_say", { n: h.total, user: h.by_user, ai: h.by_ai, b: h.bookings }))}</p>
<div class="seg tabs" role="group">${fb("all", "questions.hist_all")}${fb("user", "questions.hist_user")}${fb("ai", "questions.hist_ai")}</div>
<div class="hlist">${head || `<p class="hsay">${tr("questions.hist_empty")}</p>`}${rest}</div>`;
  }

  _render() {
    let body;
    if (this._state === "loading") body = `<div class="load">…</div>`;
    else if (this._state === "denied") body = `<div class="center"><p>${tr("questions.denied")}</p><button class="primary" data-act="close">${tr("questions.back")}</button></div>`;
    else if (this._state === "error") body = `<div class="center"><p>${tr("questions.load_error")}</p><button class="primary" data-act="retry">${tr("questions.retry")}</button></div>`;
    else if (this._tab === "history") body = this._historyHtml();
    else if (!this._card) body = this._doneHtml();
    else body = this._progressHtml() + `<div class="stage">${this._cardHtml()}</div>`;
    if (this._state === "ready") body = this._tabsHtml() + body;
    const desk = this._state === "ready" && this._tab === "open" ? `<div class="desk"><button class="ghost" data-act="all">${tr("questions.all")}</button></div>` : "";
    this.shadowRoot.innerHTML = `<style>${window._fd.SHARED_CSS}${CSS}</style>
<div class="root">
  <fd-subpage-header title="${window._fd.escHtml(tr("questions.title"))}"></fd-subpage-header>
  ${body}${desk}
</div>${this._celebrate ? this._celebrateHtml() : ""}`;
    this._wire();
    if (this._celebrate) this.shadowRoot.getElementById("celebrateBtn")?.focus();
  }

  _wire() {
    const sh = this.shadowRoot;
    if (this._wired) { this._wireCard(); return; }
    this._wired = true;
    sh.addEventListener("click", (e) => {
      const t = e.target.closest("button");
      if (!t || t.disabled) return;
      if (t.dataset.cat) return this._answer(t.dataset.cat);
      if (t.dataset.rfpick) {
        if (this._rfPick.has(t.dataset.rfpick)) this._rfPick.delete(t.dataset.rfpick); else this._rfPick.add(t.dataset.rfpick);
        return this._keepRender();
      }
      if (t.dataset.rf) {
        switch (t.dataset.rf) {
          case "confirm": return this._answer(null, { choice: "confirm" });
          case "no": return this._answer(null, { choice: "no" });
          case "other": this._rfOther = true; return this._keepRender();
          case "back": this._rfOther = false; return this._keepRender();
          case "send": return this._answer(null, { choice: "other", expenses: [...this._rfPick] });
        }
        return undefined;
      }
      if (t.dataset.ans) return this._answer(t.dataset.ans);
      if (t.dataset.reach) { this._reach = t.dataset.reach; return this._keepRender(); }
      if (t.dataset.owner !== undefined) { this._owner = t.dataset.owner; return this._keepRender(); }
      if (t.dataset.tab) {
        if (t.dataset.tab === "history") return this._openHistory();
        this._tab = "open";
        return this._keepRender();
      }
      if (t.dataset.hfilter) { this._hfilter = t.dataset.hfilter; return this._render(); }
      switch (t.dataset.act) {
        case "more": this._more = !this._more; return this._keepRender();
        case "details": this._details = !this._details; return this._keepRender();
        case "skip": return this._skip();
        case "close": return this._close();
        case "retry": return this.load();
        case "history": return this._openHistory();
        case "all": return this.dispatchEvent(new CustomEvent("fd-questions-all", { bubbles: true, composed: true }));
        case "continue": this._celebrate = null; return this._render();
      }
    });
    this._wireCard();
  }

  _wireCard() {
    const card = this.shadowRoot.getElementById("card");
    if (!card) return;
    let x0 = null, dx = 0;
    card.onpointerdown = (e) => { if (e.target.closest("button")) return; x0 = e.clientX; dx = 0; };
    card.onpointermove = (e) => {
      if (x0 === null) return;
      dx = e.clientX - x0;
      if (Math.abs(dx) > 8) { card.style.transition = "none"; card.style.transform = `translateX(${dx}px) rotate(${dx / 40}deg)`; }
    };
    const end = () => {
      if (x0 === null) return;
      x0 = null;
      card.style.transition = "";
      if (Math.abs(dx) > 90 && this._q.length > 1) this._skip();
      else card.style.transform = "";
    };
    card.onpointerup = end;
    card.onpointercancel = end;
  }

  /** Re-render without replaying the entrance animation. */
  _keepRender() {
    this._render();
    this.shadowRoot.getElementById("card")?.classList.remove("enter");
  }

  _key(e) {
    if (this._state !== "ready" || this._tab !== "open" || !this._card || this._celebrate || this._busy) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const n = parseInt(e.key, 10);
    const c = this._card;
    if (c.kind === "refund") return; // refund cards answer by their own buttons
    const cats = c.type === "contract" || c.type === "price" ? this._contractOptions(c).map((o) => o[0]) : this._cats(c);
    if (n >= 1 && n <= cats.length) { e.preventDefault(); this._answer(cats[n - 1]); }
  }

  _close() {
    this._celebrate = null;
    this.dispatchEvent(new CustomEvent("fd-questions-close", { bubbles: true, composed: true }));
  }

  _skip() {
    const card = this.shadowRoot.getElementById("card");
    const go = () => {
      const [c] = this._q.splice(this._i, 1);
      this._q.push(c);
      this._resetCard();
      this._render();
    };
    if (card) { card.classList.add("leave"); this._skipTimer = setTimeout(go, 220); } else go();
  }

  _errText(e) {
    const code = e && ((e.body && e.body.error) || e.error);
    const map = { unavailable: "questions.err_unavailable", admin_required: "questions.err_admin" };
    return tr(map[code] || "questions.err");
  }

  async _answer(category, refundAnswer) {
    const c = this._card;
    if (!c || this._busy) return;
    this._busy = true;
    this._msg = "";
    this._keepRender();
    let body;
    if (refundAnswer) body = { id: c.id, ...refundAnswer };
    else if (c.type === "contract" || c.type === "price") body = { id: c.id, type: c.type, answer: category };
    else {
      body = { id: c.id, category, reach: this._reach };
      if (this._owner) body.owner = this._owner;
    }
    try {
      const r = await this._hass.callApi("POST", `${DOMAIN}/questions/answer`, body);
      this._meta.answered_total = r.answered_total ?? this._meta.answered_total + 1;
      this._meta.week_answered = r.week_answered ?? this._meta.week_answered + 1;
      if (r.point_awarded) this._meta.points += 1;
      this._session += 1;
      this._q.splice(this._i, 1);
      if (this._i >= this._q.length) this._i = 0;
      this._resetCard();
      this._busy = false;
      if (r.point_awarded) this._celebrate = "point";
      if (!this._q.length) this._celebrate = "week";
      this._render();
    } catch (e) {
      this._busy = false;
      const code = e && ((e.body && e.body.error) || e.error);
      if (code === "unknown_question") {
        // Already settled elsewhere: drop the card silently, no dead end.
        this._q.splice(this._i, 1);
        if (this._i >= this._q.length) this._i = 0;
        this._resetCard();
      } else {
        this._msg = this._errText(e);
      }
      this._keepRender();
    }
  }
}

window._fd.defineOnce("fd-questions", FdQuestions);
