/**
 * fd-plan-wizard — "Haushaltsplan erstellen" (admin only), full-screen step flow.
 *
 *   GET  finance_dashboard/plan_wizard/gate               {ready, cycles, required, earliest_booked, ready_from}
 *   GET/PUT finance_dashboard/plan_wizard                 {current_step, steps{income,fixed,pots,goals,result}, completed}
 *                                                         PUT {step,status} | {complete:true} (+remainder_pots) | {restart:true}
 *   GET  plan_wizard/income_suggestions                   {suggestions:[{person, amount_net, source, samples}]}
 *   PUT  plan_wizard/income                               {income:[{person, amount_net}]}
 *   GET/POST plan_wizard/fixed                            {proposals:[...]} / {accept:[{series_id,name,owner,amount}]}
 *   POST plan_wizard/sheet_ideas                          {content_base64}|{url} -> {ideas, needs_consent, ai_used}
 *   POST budget_plan/position                             an idea without a recurring series becomes a position
 *   GET/PUT setup/ai/consents                             purpose "sheet_analysis" (one-time)
 *   GET/POST setup/pot_suggestions                        items accept account_keys (null = all accounts)
 *   GET  assignments                                      accounts[{key,name,iban_last4}]
 *   GET  plan_wizard/result                               monthly balance, per person, history, remainder
 *   <fd-settings section="goals"> embedded for the goals.
 *
 * Plan sign: expense positive. Nothing here talks to the bank.
 *
 * Properties: hass (required).
 * Events (bubbling, composed):
 *   fd-plan-wizard-close  {completed}
 *   fd-toast              {message, type}
 */

const DOMAIN = "finance_dashboard";
const STEPS = ["income", "fixed", "pots", "goals", "result"];
const SKIPPABLE = new Set(["fixed", "pots", "goals"]);
const SHARED_PLAN_OWNER = "__shared__";

// Fallback texts until locales/*.json carry the pw.* keys.
const FB = {
  de: {
    "pw.title": "Haushaltsplan erstellen",
    "pw.step_of": "Schritt $n von $total",
    "pw.close": "Schließen",
    "pw.back": "Zurück",
    "pw.next": "Weiter",
    "pw.skip": "Überspringen",
    "pw.error": "Speichern fehlgeschlagen",
    "pw.load_error": "Der Assistent konnte nicht geladen werden.",
    "pw.retry": "Erneut versuchen",
    "pw.admin_only": "Den Haushaltsplan erstellt ein Administrator. Du musst nichts tun.",
    "pw.gate.title": "Noch zu wenig Daten",
    "pw.gate.body": "Für einen belastbaren Plan braucht es $required volle Zahltag-Monate an Buchungen. Bisher sind $cycles vollständig.",
    "pw.gate.when": "Es geht ab ca. $date los.",
    "pw.gate.nodata": "Sobald genug Buchungen da sind, geht es los.",
    "pw.confirm.title": "Plan neu aufbauen?",
    "pw.confirm.body": "Der Haushaltsplan wird neu aufgebaut. Bestehende Posten und Einkommen werden ersetzt. Töpfe und Sparziele bleiben.",
    "pw.confirm.go": "Neu aufbauen",
    "pw.income.title": "Was kommt monatlich rein?",
    "pw.income.body": "Das Netto-Einkommen pro Person. Wir haben den größten regelmäßigen Eingang gesucht. Passe den Betrag an, wenn er nicht stimmt.",
    "pw.income.hint": "aus $source, $n Monate",
    "pw.income.none": "Kein Vorschlag gefunden. Trag den Betrag selbst ein oder lass das Feld leer.",
    "pw.income.amount": "Netto pro Monat",
    "pw.income.need_one": "Trag mindestens ein Einkommen ein.",
    "pw.income.no_persons": "Es gibt noch keine Personen. Lege sie zuerst in der Einrichtung an.",
    "pw.fixed.title": "Fixkosten",
    "pw.fixed.body": "Das sind regelmäßige Zahlungen aus deinen Buchungen. Wähle, was in den Plan soll, und passe Betrag und Besitzer an.",
    "pw.fixed.empty": "Keine Vorschläge gefunden.",
    "pw.fixed.in_plan": "schon im Plan",
    "pw.fixed.per_month": "pro Monat",
    "pw.fixed.amount": "Betrag",
    "pw.fixed.owner": "Besitzer",
    "pw.fixed.owner_shared": "Haushalt",
    "pw.fixed.accepted": "$n Posten in den Plan übernommen",
    "pw.ideas.title": "Haushaltstabelle als Ideengeber (optional)",
    "pw.ideas.body": "Wir lesen nur die Namen der Posten, zum Beispiel „Rücklage Urlaub“. Die Zahlen in der Tabelle bleiben außen vor.",
    "pw.ideas.file": "Datei hochladen (.xlsx)",
    "pw.ideas.url_label": "Google-Sheets-Link",
    "pw.ideas.go": "Lesen",
    "pw.ideas.url_hint": "Die Tabelle muss auf „Jeder mit dem Link“ freigegeben sein. Danach kannst du die Freigabe zurücknehmen.",
    "pw.ideas.url_err": "Bitte einen Link auf docs.google.com/spreadsheets einfügen.",
    "pw.ideas.busy": "Lese die Tabelle…",
    "pw.ideas.empty": "Keine neuen Ideen gefunden.",
    "pw.ideas.list": "Ideen aus der Tabelle",
    "pw.ideas.amount_missing": "Betrag eintragen",
    "pw.ideas.kind_reserve": "Rücklage",
    "pw.ideas.failed": "Die Tabelle konnte nicht gelesen werden",
    "pw.ideas.ai_used": "Einige Namen wurden von der KI zugeordnet. Gesendet wurden nur die Namen.",
    "pw.consent.title": "KI für die Tabelle?",
    "pw.consent.once": "einmalig",
    "pw.consent.pros": "Vorteile",
    "pw.consent.risks": "Risiken",
    "pw.consent.allow": "Einmalig erlauben",
    "pw.consent.deny": "Ohne KI weiter",
    "pw.pots.title": "Töpfe",
    "pw.pots.body": "So viel hast du in den letzten Monaten typischerweise ausgegeben. Wähle, was zu Töpfen werden soll, und passe die Beträge an.",
    "pw.pots.empty": "Noch nicht genug Historie für Vorschläge.",
    "pw.pots.samples": "aus $n Monaten",
    "pw.pots.per_month": "pro Monat",
    "pw.pots.amount": "Betrag",
    "pw.pots.accounts": "Konten",
    "pw.pots.accounts_all": "Alle Konten",
    "pw.pots.created": "$n Töpfe angelegt",
    "pw.pots.owner_shared": "Haushalt",
    "pw.goals.title": "Sparziele",
    "pw.goals.body": "Ein Betrag bis zu einem Datum, ein Limit für eine Kategorie, eine Sparquote oder eine Rücklage zum Auffüllen. Alles optional.",
    "pw.result.title": "Dein Plan im Überblick",
    "pw.result.body": "Nicht alles muss verplant sein. Was übrig bleibt, wird pro Person automatisch zum Topf „Taschengeld“.",
    "pw.result.income": "Einkommen",
    "pw.result.fixed": "Fixkosten",
    "pw.result.pots": "Töpfe",
    "pw.result.goals": "Sparziele",
    "pw.result.rest": "Rest (Taschengeld)",
    "pw.result.missing": "Es fehlen $amount im Monat.",
    "pw.result.missing_hint": "Du kannst trotzdem speichern oder noch anpassen:",
    "pw.result.to_pots": "Zu den Töpfen",
    "pw.result.to_goals": "Zu den Sparzielen",
    "pw.result.persons": "Pro Person",
    "pw.result.share": "Anteil",
    "pw.result.pocket": "Taschengeld",
    "pw.result.history_title": "So habt ihr in den letzten $months Monaten gelebt",
    "pw.result.history_plan": "Plan",
    "pw.result.history_actual": "Letzte Monate",
    "pw.result.avg_income": "Einkommen",
    "pw.result.avg_spent": "Ausgaben",
    "pw.result.avg_left": "Übrig",
    "pw.result.done": "Fertig",
    "pw.result.saved": "Haushaltsplan gespeichert, Taschengeld-Töpfe angelegt",
    "pw.result.saved_plain": "Haushaltsplan gespeichert",
  },
  en: {
    "pw.title": "Create household plan",
    "pw.step_of": "Step $n of $total",
    "pw.close": "Close",
    "pw.back": "Back",
    "pw.next": "Next",
    "pw.skip": "Skip",
    "pw.error": "Saving failed",
    "pw.load_error": "The wizard could not be loaded.",
    "pw.retry": "Try again",
    "pw.admin_only": "An administrator creates the household plan. You do not need to do anything.",
    "pw.gate.title": "Not enough data yet",
    "pw.gate.body": "A reliable plan needs $required full payday months of bookings. $cycles are complete so far.",
    "pw.gate.when": "It starts around $date.",
    "pw.gate.nodata": "It starts as soon as enough bookings are in.",
    "pw.confirm.title": "Rebuild the plan?",
    "pw.confirm.body": "The household plan will be rebuilt. Existing positions and income are replaced. Pots and savings goals stay.",
    "pw.confirm.go": "Rebuild",
    "pw.income.title": "What comes in each month?",
    "pw.income.body": "The net income per person. We looked for the largest regular deposit. Adjust the amount if it is off.",
    "pw.income.hint": "from $source, $n months",
    "pw.income.none": "No suggestion found. Enter the amount yourself or leave it empty.",
    "pw.income.amount": "Net per month",
    "pw.income.need_one": "Enter at least one income.",
    "pw.income.no_persons": "There are no people yet. Add them in the setup first.",
    "pw.fixed.title": "Fixed costs",
    "pw.fixed.body": "These are recurring payments from your bookings. Choose what goes into the plan and adjust amount and owner.",
    "pw.fixed.empty": "No suggestions found.",
    "pw.fixed.in_plan": "already in the plan",
    "pw.fixed.per_month": "per month",
    "pw.fixed.amount": "Amount",
    "pw.fixed.owner": "Owner",
    "pw.fixed.owner_shared": "Household",
    "pw.fixed.accepted": "$n positions added to the plan",
    "pw.ideas.title": "Household spreadsheet as idea source (optional)",
    "pw.ideas.body": "We only read the names of the positions, for example “Vacation reserve”. The numbers in the sheet are left out.",
    "pw.ideas.file": "Upload file (.xlsx)",
    "pw.ideas.url_label": "Google Sheets link",
    "pw.ideas.go": "Read",
    "pw.ideas.url_hint": "The sheet must be shared as “Anyone with the link”. You can revoke the sharing afterwards.",
    "pw.ideas.url_err": "Please paste a link to docs.google.com/spreadsheets.",
    "pw.ideas.busy": "Reading the sheet…",
    "pw.ideas.empty": "No new ideas found.",
    "pw.ideas.list": "Ideas from the sheet",
    "pw.ideas.amount_missing": "Enter an amount",
    "pw.ideas.kind_reserve": "Reserve",
    "pw.ideas.failed": "The sheet could not be read",
    "pw.ideas.ai_used": "Some names were matched by the AI. Only the names were sent.",
    "pw.consent.title": "Use AI for the sheet?",
    "pw.consent.once": "one-time",
    "pw.consent.pros": "Advantages",
    "pw.consent.risks": "Risks",
    "pw.consent.allow": "Allow once",
    "pw.consent.deny": "Continue without AI",
    "pw.pots.title": "Pots",
    "pw.pots.body": "This is what you typically spent in recent months. Choose what becomes a pot and adjust the amounts.",
    "pw.pots.empty": "Not enough history for suggestions yet.",
    "pw.pots.samples": "from $n months",
    "pw.pots.per_month": "per month",
    "pw.pots.amount": "Amount",
    "pw.pots.accounts": "Accounts",
    "pw.pots.accounts_all": "All accounts",
    "pw.pots.created": "$n pots created",
    "pw.pots.owner_shared": "Household",
    "pw.goals.title": "Savings goals",
    "pw.goals.body": "An amount by a date, a cap for a category, a savings rate or a reserve to top up. All optional.",
    "pw.result.title": "Your plan at a glance",
    "pw.result.body": "Not everything has to be planned. What is left over becomes an automatic “Pocket money” pot per person.",
    "pw.result.income": "Income",
    "pw.result.fixed": "Fixed costs",
    "pw.result.pots": "Pots",
    "pw.result.goals": "Savings goals",
    "pw.result.rest": "Left over (pocket money)",
    "pw.result.missing": "You are $amount short per month.",
    "pw.result.missing_hint": "You can still save, or adjust first:",
    "pw.result.to_pots": "Go to pots",
    "pw.result.to_goals": "Go to savings goals",
    "pw.result.persons": "Per person",
    "pw.result.share": "Share",
    "pw.result.pocket": "Pocket money",
    "pw.result.history_title": "How you lived in the last $months months",
    "pw.result.history_plan": "Plan",
    "pw.result.history_actual": "Last months",
    "pw.result.avg_income": "Income",
    "pw.result.avg_spent": "Spending",
    "pw.result.avg_left": "Left over",
    "pw.result.done": "Done",
    "pw.result.saved": "Household plan saved, pocket-money pots created",
    "pw.result.saved_plain": "Household plan saved",
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

const EUR = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
const money = (n) => EUR.format(Number(n) || 0);

const CSS = `
:host { display: block; position: fixed; inset: 0; z-index: 60; background: var(--fd-page); overflow-y: auto; overscroll-behavior: contain; }
.root { box-sizing: border-box; min-height: 100%; display: flex; flex-direction: column; color: var(--fd-t1); font-size: 14px; line-height: 1.45; container: wiz / inline-size; }
button { font: inherit; color: inherit; cursor: pointer; }
.top { display: flex; align-items: center; gap: 10px; padding: 10px 14px; max-width: 680px; width: 100%; box-sizing: border-box; margin: 0 auto; }
.top .lbl { flex: 1; color: var(--fd-t2); font-size: 12px; }
.dots { display: flex; gap: 6px; padding: 0 14px 4px; max-width: 680px; width: 100%; box-sizing: border-box; margin: 0 auto; list-style: none; }
.dots li { flex: 1; height: 5px; border-radius: 3px; background: var(--fd-line); }
.dots li.on { background: var(--fd-a300); }
.dots li.cur { background: var(--fd-a700); }
main { flex: 1; width: 100%; max-width: 680px; box-sizing: border-box; margin: 0 auto; padding: 8px 14px 96px; }
.card { padding: 16px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); }
.card + .card { margin-top: 12px; }
h2 { margin: 0 0 4px; font-size: 19px; font-weight: 500; outline: none; }
h2.sub { font-size: 15px; }
h3 { margin: 16px 0 2px; font-size: 15px; font-weight: 500; }
.muted { color: var(--fd-t2); font-size: 12.5px; margin: 0 0 10px; }
.foot { position: sticky; bottom: 0; background: color-mix(in srgb, var(--fd-page) 92%, transparent); border-top: 1px solid var(--fd-line); padding: 10px 14px calc(10px + env(safe-area-inset-bottom, 0px)); backdrop-filter: blur(6px); }
.foot > div { max-width: 680px; margin: 0 auto; display: flex; align-items: center; gap: 8px; }
.foot .sp { flex: 1; }
.err { color: var(--fd-over); font-size: 12.5px; margin: 8px 0 0; }
.btn { min-height: var(--fd-touch); padding: 0 18px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; }
.btn.ghost { background: transparent; color: var(--fd-a700); border-color: var(--fd-a100); }
.btn.text { background: transparent; color: var(--fd-t2); padding: 0 12px; }
.btn:disabled { opacity: .5; cursor: default; }
button:focus-visible, input:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
.row { display: flex; align-items: center; gap: 10px; min-height: var(--fd-touch); padding: 8px 0; flex-wrap: wrap; }
.row + .row { border-top: 1px solid var(--fd-line); }
.row .who { flex: 1 1 150px; min-width: 0; display: flex; flex-direction: column; }
.row .who b { font-weight: 500; overflow-wrap: anywhere; }
.row .who span { color: var(--fd-t2); font-size: 12px; }
.sw { box-sizing: border-box; flex: none; position: relative; width: 52px; height: 32px; border-radius: 16px; border: 1px solid var(--fd-line); background: var(--fd-sunk); padding: 0; }
.sw::after { content: ""; position: absolute; top: 3px; left: 3px; width: 24px; height: 24px; border-radius: 50%; background: var(--fd-t3); transition: transform .15s, background .15s; }
.sw[aria-checked="true"] { background: var(--fd-a700); border-color: var(--fd-a700); }
.sw[aria-checked="true"]::after { transform: translateX(20px); background: #fff; }
.hit { flex: none; display: inline-flex; align-items: center; justify-content: center; width: 52px; min-height: var(--fd-touch); }
input[type=number] { box-sizing: border-box; width: 100px; min-height: var(--fd-touch); padding: 0 10px; border: 1px solid var(--fd-line); border-radius: 10px; background: var(--fd-page); color: var(--fd-t1); font: inherit; text-align: right; }
.item.off { opacity: .6; }
.item + .item { border-top: 1px solid var(--fd-line); }
.item .row { border-top: 0; }
.chips { display: flex; gap: 6px; overflow-x: auto; padding: 0 0 8px 62px; scroll-snap-type: x proximity; }
.chips button { flex: none; scroll-snap-align: start; min-height: 36px; padding: 0 12px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: transparent; max-width: 100%; }
.chips button[aria-checked="true"] { background: var(--fd-a50); border-color: var(--fd-a500); color: var(--fd-a900); font-weight: 500; }
.chips .lb { display: block; max-width: 16ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.note { padding: 12px; border-radius: 10px; background: var(--fd-sunk); color: var(--fd-t2); font-size: 13px; margin: 8px 0; }
.bad { padding: 12px; border-radius: 10px; background: var(--fd-sunk); color: var(--fd-over); font-weight: 500; margin: 10px 0; }
.imp { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 10px 0 4px; }
.imp input[type=url] { box-sizing: border-box; flex: 1 1 220px; min-width: 0; min-height: var(--fd-touch); padding: 0 10px; border: 1px solid var(--fd-line); border-radius: 10px; background: var(--fd-page); color: var(--fd-t1); font: inherit; }
.imp label { width: 100%; color: var(--fd-t2); font-size: 12.5px; }
.cons ul { margin: 2px 0 8px; padding-left: 18px; }
.cons .btns { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.chip { display: inline-flex; align-items: center; padding: 1px 9px; border-radius: var(--fd-r-pill); font-size: 11.5px; font-weight: 500; background: var(--fd-a50); color: var(--fd-a900); }
.sum { display: flex; justify-content: space-between; gap: 10px; padding: 8px 0; }
.sum + .sum { border-top: 1px solid var(--fd-line); }
.sum.tot { font-weight: 600; border-top: 2px solid var(--fd-line); }
.sum.neg span:last-child { color: var(--fd-over); }
.sum span:last-child { text-align: right; font-variant-numeric: tabular-nums; }
.cmp { display: grid; grid-template-columns: 1fr auto auto; gap: 4px 14px; align-items: baseline; }
.cmp .h { color: var(--fd-t2); font-size: 12px; text-align: right; }
.cmp .v { text-align: right; font-variant-numeric: tabular-nums; }
.links { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.msg { text-align: center; padding: 40px 14px; color: var(--fd-t2); max-width: 520px; margin: 0 auto; }
.msg .acts { display: flex; justify-content: center; gap: 8px; margin-top: 16px; }
`;

class FdPlanWizard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._mode = "loading"; // loading | gate | confirm | wizard
    this._gate = null;
    this._st = null;
    this._persons = [];
    this._idx = 0;
    this._err = "";
    this._busy = false;
    this._loadFailed = false;
    this._income = null;
    this._fixed = null;
    this._ideas = { busy: false, list: null, url: "", needsConsent: false, aiUsed: false, last: null, noAi: false, failed: "" };
    this._consent = null;
    this._pots = null;
    this._accounts = [];
    this._result = null;
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
  get _step() { return STEPS[this._idx]; }
  _api(method, path, body) { return this._hass.callApi(method, `${DOMAIN}/${path}`, body); }
  _dn(p) { return (p.display_name || "").trim() || p.name; }
  _dnOf(name) { const p = this._persons.find((x) => x.name === name); return p ? this._dn(p) : name; }

  async _load() {
    if (!this._isAdmin) return this._render();
    await window._fd.t("pw.title");
    try {
      this._gate = await this._api("GET", "plan_wizard/gate");
      if (!this._gate.ready) {
        this._mode = "gate";
      } else {
        const [st, plan, setup] = await Promise.all([
          this._api("GET", "plan_wizard"),
          this._api("GET", "budget_plan").catch(() => ({})),
          this._api("GET", "setup").catch(() => ({})),
        ]);
        this._st = st;
        this._persons = setup.persons || [];
        const midRun = !st.completed && Object.values(st.steps || {}).some((s) => s !== "pending");
        const hasPlan = ((plan.positions || []).length + (plan.income || []).length) > 0;
        this._idx = st.completed ? 0 : Math.max(0, STEPS.indexOf(st.current_step));
        this._mode = hasPlan && !midRun ? "confirm" : "wizard";
      }
      this._loadFailed = false;
    } catch (e) {
      console.warn("fd-plan-wizard: load failed:", e);
      this._loadFailed = true;
    }
    this._render();
    if (this._mode === "wizard" && !this._loadFailed) this._enter();
  }

  async _restart() {
    if (this._busy) return;
    this._busy = true;
    try {
      this._st = await this._api("PUT", "plan_wizard", { restart: true });
      this._idx = 0;
      this._mode = "wizard";
      this._income = this._fixed = this._pots = this._result = null;
      this._busy = false;
      this._render();
      this._enter();
    } catch (e) {
      this._busy = false;
      this._fail(this._errText(e));
    }
  }

  /** Fetch whatever the freshly entered step needs, then paint it. */
  async _enter() {
    const step = this._step;
    if (step === "income" && this._income === null) {
      let sug = [];
      try { sug = (await this._api("GET", "plan_wizard/income_suggestions")).suggestions || []; } catch (e) { sug = []; }
      let existing = [];
      try { existing = (await this._api("GET", "budget_plan")).income || []; } catch (e) { existing = []; }
      const names = this._persons.map((p) => p.name);
      for (const s of sug) if (!names.includes(s.person)) names.push(s.person);
      this._income = names.map((person) => {
        const s = sug.find((x) => x.person === person);
        const e = existing.find((x) => x.person === person);
        const val = s ? s.amount_net : (e && Number(e.deposit) > 0 ? e.deposit : "");
        return { person, sug: s || null, amount: val === "" ? "" : String(val) };
      });
    } else if (step === "fixed" && this._fixed === null) {
      try {
        this._fixed = ((await this._api("GET", "plan_wizard/fixed")).proposals || [])
          .map((p) => ({ ...p, on: !p.already_in_plan, amount: p.amount, owner: p.owner || "shared" }));
      } catch (e) { this._fixed = []; }
    } else if (step === "pots" && this._pots === null) {
      try {
        this._pots = ((await this._api("GET", "setup/pot_suggestions")).suggestions || [])
          .map((s) => ({ ...s, on: true, amount: s.cycle_budget, keys: null }));
      } catch (e) { this._pots = []; }
      try { this._accounts = (await this._api("GET", "assignments")).accounts || []; } catch (e) { this._accounts = []; }
    } else if (step === "result") {
      this._result = null;
      this._render();
      try { this._result = await this._api("GET", "plan_wizard/result"); } catch (e) { this._result = false; }
    }
    if (step === this._step) this._render();
    this.shadowRoot.querySelector("h2")?.focus();
  }

  // ---- render -----------------------------------------------------------
  _render() {
    const sh = this.shadowRoot;
    const { escHtml } = window._fd;
    const head = `<style>${window._fd.SHARED_CSS}${CSS}</style>`;
    this.setAttribute("role", "dialog");
    this.setAttribute("aria-modal", "true");
    this.setAttribute("aria-label", tr("pw.title"));
    const closeBtn = `<button type="button" class="btn text" data-a="close">${escHtml(tr("pw.close"))}</button>`;
    const simple = (title, body, btns = "") => `${head}<div class="root"><div class="top"><span class="lbl">${escHtml(tr("pw.title"))}</span>${closeBtn}</div>
      <div class="msg"><h2 tabindex="-1">${escHtml(title)}</h2><p>${body}</p>${btns}</div></div>`;

    if (!this._isAdmin) sh.innerHTML = simple(tr("pw.title"), escHtml(tr("pw.admin_only")));
    else if (this._loadFailed) sh.innerHTML = simple(tr("pw.title"), escHtml(tr("pw.load_error")), `<div class="acts"><button type="button" class="btn" data-a="retry">${escHtml(tr("pw.retry"))}</button></div>`);
    else if (this._mode === "loading") sh.innerHTML = simple(tr("pw.title"), "…");
    else if (this._mode === "gate") {
      const g = this._gate || {};
      const when = g.ready_from ? new Date(g.ready_from).toLocaleDateString("de-DE", { day: "numeric", month: "long", year: "numeric" }) : "";
      const body = `${escHtml(tr("pw.gate.body", { required: g.required ?? 3, cycles: g.cycles ?? 0 }))} ${escHtml(when ? tr("pw.gate.when", { date: when }) : tr("pw.gate.nodata"))}`;
      sh.innerHTML = simple(tr("pw.gate.title"), body);
    } else if (this._mode === "confirm") {
      sh.innerHTML = simple(tr("pw.confirm.title"), escHtml(tr("pw.confirm.body")),
        `<div class="acts"><button type="button" class="btn ghost" data-a="close">${escHtml(tr("pw.close"))}</button><button type="button" class="btn" data-a="restart">${escHtml(tr("pw.confirm.go"))}</button></div>`);
    } else {
      const step = this._step;
      const dots = STEPS.map((s, i) => `<li class="${i === this._idx ? "cur" : i < this._idx ? "on" : ""}"${i === this._idx ? ' aria-current="step"' : ""}></li>`).join("");
      const skip = SKIPPABLE.has(step) ? `<button type="button" class="btn text" data-a="skip">${escHtml(tr("pw.skip"))}</button>` : "";
      const foot = step === "result"
        ? `<button type="button" class="btn ghost" data-a="back">${escHtml(tr("pw.back"))}</button><span class="sp"></span><button type="button" class="btn" data-a="finish"${this._result ? "" : " disabled"}>${escHtml(tr("pw.result.done"))}</button>`
        : `<button type="button" class="btn ghost" data-a="back"${this._idx === 0 ? " disabled" : ""}>${escHtml(tr("pw.back"))}</button><span class="sp"></span>${skip}<button type="button" class="btn" data-a="next">${escHtml(tr("pw.next"))}</button>`;
      sh.innerHTML = `${head}<div class="root">
  <div class="top"><span class="lbl">${escHtml(tr("pw.title"))} · ${escHtml(tr("pw.step_of", { n: this._idx + 1, total: STEPS.length }))}</span>${closeBtn}</div>
  <ol class="dots" aria-hidden="true">${dots}</ol>
  <main><div class="card" id="body">${this._body(step)}</div>${step === "fixed" ? this._ideasHtml() : ""}<p class="err" id="err" role="alert">${escHtml(this._err)}</p></main>
  <div class="foot"><div>${foot}</div></div></div>`;
      if (step === "goals") this._mountGoals();
    }
    this._wire();
  }

  _head(key) {
    const { escHtml } = window._fd;
    return `<h2 tabindex="-1">${escHtml(tr(`pw.${key}.title`))}</h2><p class="muted">${escHtml(tr(`pw.${key}.body`))}</p>`;
  }

  _body(step) {
    switch (step) {
      case "income": return this._incomeBody();
      case "fixed": return this._fixedBody();
      case "pots": return this._potsBody();
      case "goals": return `${this._head("goals")}<div id="embed"></div>`;
      default: return this._resultBody();
    }
  }

  _incomeBody() {
    const { escHtml } = window._fd;
    if (this._income === null) return `${this._head("income")}<p class="muted">…</p>`;
    if (!this._income.length) return `${this._head("income")}<div class="note">${escHtml(tr("pw.income.no_persons"))}</div>`;
    const rows = this._income.map((r, i) => {
      const hint = r.sug ? tr("pw.income.hint", { source: r.sug.source, n: r.sug.samples }) : tr("pw.income.none");
      return `<div class="row"><div class="who"><b>${escHtml(this._dnOf(r.person))}</b><span>${escHtml(hint)}</span></div>
        <input type="number" min="0" step="10" inputmode="decimal" data-inc="${i}" value="${escHtml(r.amount)}" aria-label="${escHtml(tr("pw.income.amount") + ": " + this._dnOf(r.person))}"></div>`;
    }).join("");
    return `${this._head("income")}${rows}`;
  }

  _ownerChips(kind, i, current, disabled) {
    const { escHtml } = window._fd;
    const owners = [["shared", tr("pw.fixed.owner_shared")]].concat(this._persons.map((p) => [p.name, this._dn(p)]));
    return owners.map(([v, l]) => `<button type="button" role="radio" aria-checked="${current === v}" data-${kind}-owner="${i}" data-v="${escHtml(v)}"${disabled ? " disabled" : ""}><span class="lb">${escHtml(l)}</span></button>`).join("");
  }

  _fixedBody() {
    const { escHtml } = window._fd;
    if (this._fixed === null) return `${this._head("fixed")}<p class="muted">…</p>`;
    if (!this._fixed.length) return `${this._head("fixed")}<div class="note">${escHtml(tr("pw.fixed.empty"))}</div>`;
    const cats = window._fd.CAT_LABELS || {};
    return `${this._head("fixed")}${this._fixed.map((p, i) => this._posRow("pf", i, p, cats, p.already_in_plan)).join("")}`;
  }

  _posRow(kind, i, p, cats, inPlan) {
    const { escHtml } = window._fd;
    const hasAmt = p.amount !== "" && p.amount != null;
    const sub = inPlan ? tr("pw.fixed.in_plan")
      : hasAmt ? `${money(Math.abs(Number(p.amount) || 0))} ${tr("pw.fixed.per_month")}` : tr("pw.ideas.amount_missing");
    const meta = [cats[p.category] || p.category || "", p.interval || "", p.kind === "reserve" ? tr("pw.ideas.kind_reserve") : "", sub].filter(Boolean).join(" · ");
    return `<div class="item ${p.on ? "" : "off"}"><div class="row"><span class="hit"><button type="button" class="sw" role="switch" aria-checked="${p.on}" data-${kind}="${i}" aria-label="${escHtml(p.name)}"${inPlan ? " disabled" : ""}></button></span>
      <div class="who"><b>${escHtml(p.name)}</b><span>${escHtml(meta)}</span></div>
      <input type="number" min="0" step="any" inputmode="decimal" data-${kind}-amt="${i}" value="${escHtml(p.amount ?? "")}" aria-label="${escHtml(tr("pw.fixed.amount") + ": " + p.name)}"${p.on ? "" : " disabled"}></div>
      ${inPlan ? "" : `<div class="chips" role="radiogroup" aria-label="${escHtml(tr("pw.fixed.owner") + ": " + p.name)}">${this._ownerChips(kind, i, p.owner, !p.on)}</div>`}</div>`;
  }

  _ideasHtml() {
    const { escHtml } = window._fd;
    const d = this._ideas;
    const dis = d.busy ? " disabled" : "";
    let list = "";
    if (d.busy) list = `<p class="muted" role="status">${escHtml(tr("pw.ideas.busy"))}</p>`;
    else {
      if (d.failed) list += `<p class="err" role="alert">${escHtml(d.failed)}</p>`;
      if (d.needsConsent && !d.noAi) list += this._consentHtml();
      if (d.list) {
        const cats = window._fd.CAT_LABELS || {};
        list += d.list.length
          ? `<h3>${escHtml(tr("pw.ideas.list"))}</h3>${d.list.map((p, i) => this._posRow("idea", i, p, cats, false)).join("")}${d.aiUsed ? `<p class="muted">${escHtml(tr("pw.ideas.ai_used"))}</p>` : ""}`
          : `<div class="note">${escHtml(tr("pw.ideas.empty"))}</div>`;
      }
    }
    return `<div class="card"><h2 class="sub">${escHtml(tr("pw.ideas.title"))}</h2><p class="muted">${escHtml(tr("pw.ideas.body"))}</p>
      <div class="imp"><input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" data-ideas-file hidden>
        <button type="button" class="btn ghost" data-a="ideas_file"${dis}>${escHtml(tr("pw.ideas.file"))}</button></div>
      <div class="imp"><label for="sheet-url">${escHtml(tr("pw.ideas.url_label"))}</label>
        <input type="url" id="sheet-url" inputmode="url" autocomplete="off" placeholder="https://docs.google.com/spreadsheets/d/…" data-sheet-url value="${escHtml(d.url)}"${dis}>
        <button type="button" class="btn ghost" data-a="ideas_url"${dis}>${escHtml(tr("pw.ideas.go"))}</button></div>
      <p class="muted">${escHtml(tr("pw.ideas.url_hint"))}</p>${list}</div>`;
  }

  _consentHtml() {
    const { escHtml } = window._fd;
    const meta = ((this._consent || {}).purposes || {}).sheet_analysis || {};
    // Missing locale keys come back as the key itself: leave those lines out.
    const lines = (keys) => (keys || []).slice(0, 3).filter((k) => tr(k) !== k).map((k) => `<li>${escHtml(tr(k))}</li>`).join("");
    const pros = lines(meta.pros);
    const risks = lines(meta.risks);
    return `<div class="note cons" role="group" aria-label="${escHtml(tr("pw.consent.title"))}"><b>${escHtml(tr("pw.consent.title"))}</b> <span class="chip">${escHtml(tr("pw.consent.once"))}</span>
      ${pros ? `<h3>${escHtml(tr("pw.consent.pros"))}</h3><ul>${pros}</ul>` : ""}${risks ? `<h3>${escHtml(tr("pw.consent.risks"))}</h3><ul>${risks}</ul>` : ""}
      <div class="btns"><button type="button" class="btn" data-a="consent_allow">${escHtml(tr("pw.consent.allow"))}</button>
      <button type="button" class="btn ghost" data-a="consent_deny">${escHtml(tr("pw.consent.deny"))}</button></div></div>`;
  }

  _potsBody() {
    const { escHtml } = window._fd;
    if (this._pots === null) return `${this._head("pots")}<p class="muted">…</p>`;
    if (!this._pots.length) return `${this._head("pots")}<div class="note">${escHtml(tr("pw.pots.empty"))}</div>`;
    const cats = window._fd.CAT_LABELS || {};
    const rows = this._pots.map((s, i) => {
      const owner = s.owner === "shared" ? tr("pw.pots.owner_shared") : this._dnOf(s.owner);
      const label = s.name || cats[s.category] || s.category;
      let bind = "";
      if (this._accounts.length > 1) {
        const chips = this._accounts.map((a) => `<button type="button" role="checkbox" aria-checked="${!!(s.keys && s.keys.includes(a.key))}" data-pot-acc="${i}" data-key="${escHtml(a.key)}"${s.on ? "" : " disabled"}><span class="lb">${escHtml(a.name || a.key)}${a.iban_last4 ? ` ·${escHtml(a.iban_last4)}` : ""}</span></button>`).join("");
        bind = `<div class="chips" role="group" aria-label="${escHtml(tr("pw.pots.accounts") + ": " + label)}"><button type="button" role="checkbox" aria-checked="${!s.keys}" data-pot-acc-all="${i}"${s.on ? "" : " disabled"}><span class="lb">${escHtml(tr("pw.pots.accounts_all"))}</span></button>${chips}</div>`;
      }
      return `<div class="item ${s.on ? "" : "off"}"><div class="row"><span class="hit"><button type="button" class="sw" role="switch" aria-checked="${s.on}" data-pot="${i}" aria-label="${escHtml(label)}"></button></span>
        <div class="who"><b>${escHtml(label)}</b><span>${escHtml(owner)} · ${escHtml(tr("pw.pots.samples", { n: s.samples }))}</span></div>
        <input type="number" min="0" step="10" inputmode="decimal" data-pot-amt="${i}" value="${escHtml(s.amount)}" aria-label="${escHtml(tr("pw.pots.amount") + ": " + label + " (" + tr("pw.pots.per_month") + ")")}"${s.on ? "" : " disabled"}></div>${bind}</div>`;
    }).join("");
    return `${this._head("pots")}${rows}`;
  }

  _resultBody() {
    const { escHtml } = window._fd;
    const r = this._result;
    if (r === null) return `${this._head("result")}<p class="muted">…</p>`;
    if (r === false) return `${this._head("result")}<div class="note">${escHtml(tr("pw.load_error"))}</div>`;
    const neg = Number(r.left_over) < 0;
    const sum = (label, v, cls = "") => `<div class="sum ${cls}"><span>${escHtml(label)}</span><span>${escHtml(money(v))}</span></div>`;
    let html = `${this._head("result")}
      ${sum(tr("pw.result.income"), r.income_total)}
      ${sum(tr("pw.result.fixed"), -Math.abs(r.fixed_total))}
      ${sum(tr("pw.result.pots"), -Math.abs(r.pots_total))}
      ${sum(tr("pw.result.goals"), -Math.abs(r.goals_total))}
      ${sum(tr("pw.result.rest"), r.left_over, `tot ${neg ? "neg" : ""}`)}`;
    if (neg) {
      html += `<div class="bad" role="status">${escHtml(tr("pw.result.missing", { amount: money(Math.abs(r.left_over)) }))}</div>
        <p class="muted">${escHtml(tr("pw.result.missing_hint"))}</p>
        <div class="links"><button type="button" class="btn ghost" data-go="2">${escHtml(tr("pw.result.to_pots"))}</button><button type="button" class="btn ghost" data-go="3">${escHtml(tr("pw.result.to_goals"))}</button></div>`;
    }
    const pp = r.per_person || [];
    if (pp.length) {
      html += `<h3>${escHtml(tr("pw.result.persons"))}</h3>${pp.map((p) => `<div class="item"><div class="row"><div class="who"><b>${escHtml(this._dnOf(p.person))}</b>
        <span>${escHtml(tr("pw.result.income"))} ${escHtml(money(p.income))} · ${escHtml(tr("pw.result.share"))} ${escHtml(Math.round((Number(p.share) || 0) * 100) + " %")}</span></div>
        <div class="who" style="flex:0 0 auto;text-align:right"><b>${escHtml(money(p.pocket_money))}</b><span>${escHtml(tr("pw.result.pocket"))}</span></div></div></div>`).join("")}`;
    }
    const h = r.history;
    if (h && h.months) {
      const spent = Math.abs(r.fixed_total) + Math.abs(r.pots_total) + Math.abs(r.goals_total);
      const line = (label, a, b) => `<span>${escHtml(label)}</span><span class="v">${escHtml(money(a))}</span><span class="v">${escHtml(money(b))}</span>`;
      html += `<h3>${escHtml(tr("pw.result.history_title", { months: h.months }))}</h3>
        <div class="cmp" role="table"><span></span><span class="h">${escHtml(tr("pw.result.history_plan"))}</span><span class="h">${escHtml(tr("pw.result.history_actual"))}</span>
        ${line(tr("pw.result.avg_income"), r.income_total, h.avg_income)}
        ${line(tr("pw.result.avg_spent"), spent, Math.abs(h.avg_spent))}
        ${line(tr("pw.result.avg_left"), r.left_over, h.avg_left_over)}</div>`;
    }
    return html;
  }

  _mountGoals() {
    const box = this.shadowRoot.getElementById("embed");
    if (!box) return;
    const el = document.createElement("fd-settings");
    el.setAttribute("section", "goals");
    el.setAttribute("embedded", "");
    el.hass = this._hass;
    box.append(el);
    this._settingsEl = el;
  }

  // ---- events -----------------------------------------------------------
  _wire() {
    if (this._wired) return;
    this._wired = true;
    const sh = this.shadowRoot;
    sh.addEventListener("click", (ev) => {
      const t = ev.target.closest("button");
      if (!t || t.disabled) return;
      const d = t.dataset;
      if (d.a) return this._action(d.a);
      if (d.go !== undefined) return this._go(Number(d.go));
      const n = (v) => Number(v);
      if (d.pf !== undefined) this._fixed[n(d.pf)].on = !this._fixed[n(d.pf)].on;
      else if (d.pfOwner !== undefined) this._fixed[n(d.pfOwner)].owner = d.v;
      else if (d.idea !== undefined) this._ideas.list[n(d.idea)].on = !this._ideas.list[n(d.idea)].on;
      else if (d.ideaOwner !== undefined) this._ideas.list[n(d.ideaOwner)].owner = d.v;
      else if (d.pot !== undefined) this._pots[n(d.pot)].on = !this._pots[n(d.pot)].on;
      else if (d.potAccAll !== undefined) this._pots[n(d.potAccAll)].keys = null;
      else if (d.potAcc !== undefined) {
        const s = this._pots[n(d.potAcc)];
        const set = new Set(s.keys || []);
        if (set.has(d.key)) set.delete(d.key); else set.add(d.key);
        s.keys = set.size ? [...set] : null;
      } else return;
      this._render();
    });
    sh.addEventListener("input", (ev) => {
      const el = ev.target;
      const d = el.dataset;
      if (d.inc !== undefined) this._income[Number(d.inc)].amount = el.value;
      else if (d.pfAmt !== undefined) this._fixed[Number(d.pfAmt)].amount = el.value;
      else if (d.ideaAmt !== undefined) this._ideas.list[Number(d.ideaAmt)].amount = el.value;
      else if (d.potAmt !== undefined) this._pots[Number(d.potAmt)].amount = el.value;
      else if (d.sheetUrl !== undefined) this._ideas.url = el.value;
    });
    sh.addEventListener("change", (ev) => {
      const el = ev.target;
      if (el.dataset.ideasFile !== undefined) { this._uploadIdeas(el.files && el.files[0]); el.value = ""; }
    });
    this.onkeydown = (ev) => {
      if (ev.key === "Escape") this._close(false);
      else if (ev.key === "Enter" && ev.composedPath()[0]?.dataset?.sheetUrl !== undefined) this._ideasFromUrl();
    };
  }

  _close(completed) {
    this.dispatchEvent(new CustomEvent("fd-plan-wizard-close", { bubbles: true, composed: true, detail: { completed } }));
  }

  _action(a) {
    if (a === "close") this._close(false);
    else if (a === "retry") { this._loadFailed = false; this._load(); }
    else if (a === "restart") this._restart();
    else if (a === "back") this._go(this._idx - 1);
    else if (a === "skip") this._advance("skipped");
    else if (a === "next") this._advance("done");
    else if (a === "finish") this._finish();
    else if (a === "ideas_file") this.shadowRoot.querySelector("[data-ideas-file]")?.click();
    else if (a === "ideas_url") this._ideasFromUrl();
    else if (a === "consent_allow") this._allowConsent();
    else if (a === "consent_deny") { this._ideas.noAi = true; this._render(); }
  }

  _go(i) {
    this._err = "";
    this._idx = Math.min(STEPS.length - 1, Math.max(0, i));
    this._render();
    this._enter();
  }

  _fail(msg) {
    this._err = msg;
    const el = this.shadowRoot.getElementById("err");
    if (el) el.textContent = msg;
  }

  _errText(e) {
    const detail = (e && e.body && (e.body.detail || e.body.error)) || (e && e.message) || "";
    return detail ? `${tr("pw.error")}: ${detail}` : tr("pw.error");
  }

  // ---- sheet ideas ---------------------------------------------------------
  _uploadIdeas(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => this._runIdeas({ content_base64: String(reader.result || "") });
    reader.onerror = () => this._fail(tr("pw.ideas.failed"));
    reader.readAsDataURL(file);
  }

  _ideasFromUrl() {
    const url = (this._ideas.url || "").trim();
    if (!/^https:\/\/docs\.google\.com\/spreadsheets\/d\//i.test(url)) return this._fail(tr("pw.ideas.url_err"));
    this._runIdeas({ url });
  }

  async _runIdeas(body) {
    const d = this._ideas;
    if (d.busy) return;
    this._err = "";
    d.busy = true;
    d.failed = "";
    d.last = body;
    this._render();
    try {
      const res = await this._api("POST", "plan_wizard/sheet_ideas", body);
      const have = new Set((this._fixed || []).map((p) => p.series_id));
      d.list = (res.ideas || []).filter((i) => !(i.series_id && have.has(i.series_id)))
        .map((i) => ({ ...i, owner: "shared", on: Number(i.amount) > 0, amount: i.amount == null ? "" : i.amount }));
      d.needsConsent = !!res.needs_consent;
      d.aiUsed = !!res.ai_used;
      if (d.needsConsent && !this._consent) {
        try { this._consent = await this._api("GET", "setup/ai/consents"); } catch (e) { this._consent = {}; }
      }
    } catch (e) {
      const detail = (e && e.body && (e.body.error || e.body.message)) || (e && e.message) || "";
      d.failed = detail ? `${tr("pw.ideas.failed")}: ${detail}` : tr("pw.ideas.failed");
    }
    d.busy = false;
    this._render();
  }

  async _allowConsent() {
    try {
      this._consent = await this._api("PUT", "setup/ai/consents", { purpose: "sheet_analysis", granted: true });
    } catch (e) { return this._fail(this._errText(e)); }
    this._ideas.needsConsent = false;
    if (this._ideas.last) await this._runIdeas(this._ideas.last);
  }

  // ---- step saving ---------------------------------------------------------
  async _advance(status) {
    if (this._busy) return;
    const step = this._step;
    this._err = "";
    this._busy = true;
    this.shadowRoot.querySelectorAll(".foot button").forEach((b) => { b.disabled = true; });
    try {
      if (status === "done") {
        if (step === "income") {
          const income = (this._income || []).filter((r) => r.amount !== "" && Number(r.amount) > 0)
            .map((r) => ({ person: r.person, amount_net: Number(r.amount) }));
          if (!income.length) { this._fail(tr("pw.income.need_one")); return this._unbusy(); }
          await this._api("PUT", "plan_wizard/income", { income });
        } else if (step === "fixed") {
          if (!(await this._saveFixed())) status = "skipped";
        } else if (step === "pots") {
          const accept = (this._pots || []).filter((s) => s.on && Number(s.amount) > 0)
            .map((s) => ({ category: s.category, owner: s.owner, cycle_budget: Number(s.amount), name: s.name, account_keys: s.keys }));
          if (accept.length) {
            await this._api("POST", "setup/pot_suggestions", { accept });
            this._pots = null;
            this._toast(tr("pw.pots.created", { n: accept.length }), "success");
          } else status = "skipped";
        } else if (step === "goals") {
          const s = this._settingsEl;
          if (s && !(await s.save())) return this._unbusy();
        }
      }
      this._st = await this._api("PUT", "plan_wizard", { step, status });
      this._busy = false;
      this._go(this._idx + 1);
    } catch (e) {
      this._fail(this._errText(e));
      this._unbusy();
    }
  }

  /** Proposals and series-matched ideas go through the fixed endpoint, other ideas become positions. */
  async _saveFixed() {
    const accept = (this._fixed || []).filter((p) => p.on && !p.already_in_plan && p.amount !== "" && Number(p.amount) > 0)
      .map((p) => ({ series_id: p.series_id, name: p.name, owner: p.owner, amount: Number(p.amount) }));
    const known = new Set((this._fixed || []).map((p) => p.series_id));
    const ideas = (this._ideas.list || []).filter((p) => p.on && p.amount !== "" && Number(p.amount) > 0);
    const loose = [];
    for (const p of ideas) {
      if (p.series_id && known.has(p.series_id)) accept.push({ series_id: p.series_id, name: p.name, owner: p.owner, amount: Number(p.amount) });
      else loose.push(p);
    }
    let n = 0;
    if (accept.length) {
      const res = await this._api("POST", "plan_wizard/fixed", { accept });
      n += Array.isArray(res.created) ? res.created.length : Number(res.created) || accept.length;
      this._fixed = null;
    }
    for (const p of loose) {
      await this._api("POST", "budget_plan/position", {
        name: p.name, owner: p.owner === "shared" ? SHARED_PLAN_OWNER : p.owner, amount: Math.abs(Number(p.amount)),
        kind: p.kind === "reserve" ? "buffer" : "fixed", ...(p.category ? { category: p.category } : {}),
      });
      n += 1;
    }
    if (loose.length) this._ideas.list = (this._ideas.list || []).filter((p) => !loose.includes(p));
    if (n) this._toast(tr("pw.fixed.accepted", { n }), "success");
    return n > 0;
  }

  _unbusy() {
    this._busy = false;
    this.shadowRoot.querySelectorAll(".foot button").forEach((b) => { b.disabled = this._idx === 0 && b.dataset.a === "back"; });
  }

  async _finish() {
    if (this._busy) return;
    this._busy = true;
    try {
      const res = await this._api("PUT", "plan_wizard", { complete: true });
      const made = Array.isArray(res && res.remainder_pots) ? res.remainder_pots.length : 0;
      this._toast(tr(made ? "pw.result.saved" : "pw.result.saved_plain"), "success");
      this._busy = false;
      this._close(true);
    } catch (e) {
      this._busy = false;
      this._fail(this._errText(e));
    }
  }

  _toast(message, type) {
    this.dispatchEvent(new CustomEvent("fd-toast", { bubbles: true, composed: true, detail: { message, type } }));
    let el = this.shadowRoot.getElementById("wtoast");
    if (!el) {
      el = document.createElement("div");
      el.id = "wtoast";
      el.setAttribute("role", "status");
      el.style.cssText = "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:5;"
        + "max-width:min(360px,calc(100vw - 32px));padding:10px 16px;border-radius:12px;"
        + "background:var(--fd-t1);color:var(--fd-card);font-size:14px;box-shadow:var(--fd-sh2);";
      this.shadowRoot.appendChild(el);
    }
    el.textContent = message;
    el.hidden = false;
    clearTimeout(this._wtoastT);
    this._wtoastT = setTimeout(() => { el.hidden = true; }, 3200);
  }
}

window._fd.defineOnce("fd-plan-wizard", FdPlanWizard);
