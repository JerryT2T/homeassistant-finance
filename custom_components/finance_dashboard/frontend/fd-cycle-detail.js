/**
 * fd-cycle-detail — the cycle behind the Start screen: Einnahmen · Ausgaben · Überschuss.
 *
 *   <fd-cycle-detail view="household|person" person="Anna" layout="auto|strip|full">
 *
 * Replaces fd-household-cycle + fd-household-section. Spec: docs/dev/ui-concept-gap.md § 1.5.
 *   - strip   (always, mobile): three short figures for the cycle.
 *   - analysis (desktop, ≥ 1024 px viewport or layout="full"; purple marker):
 *       owner split, fixed vs. variable, plan vs. actual per category.
 *     `layout="strip"` forces the strip only, `layout="full"` forces the analysis.
 *
 * Data ONLY from the API (cache reads, never a bank call, never sensor attributes):
 *   GET finance_dashboard/household_summary?cycle=current|previous[&view=person]
 *   GET finance_dashboard/plan_vs_actual   (household view; admins see categories, others `restricted`)
 *   GET finance_dashboard/budget_plan      (only to know whether a plan exists)
 *
 * Properties:
 *   hass    (required)
 *   view    "household" (default) | "person"  — also an attribute. person = the viewer's own figures
 *   person  display name of the viewer's person (attribute or property), heading only
 *   cycle   "current" (default) | "previous"
 *   layout  see above (attribute)
 *   data    (setter) any set re-reads everything, like the old fd-household-cycle
 *   reload() public
 *
 * Privacy: `privacy: "restricted"` / `owners[].restricted` -> totals only, no fixed/variable
 * split; `plan_vs_actual.restricted` -> no category rows. Another person's accounts show as a sum.
 *
 * Events (bubbling, composed):
 *   fd-navigate {target:"setup"}                      not configured
 *   fd-open-plan-wizard                               no plan yet and the plan gate is open
 *   fd-navigate {target:"settings", section:"accounts"} unassigned expenses
 *   fd-navigate {target:"freshness"}                  empty cycle: go to Datenstand to import
 */

const DOMAIN = "finance_dashboard";
const SKIP_CATS = new Set(["income", "transfers"]);
const PERSON_COLORS = ["var(--fd-person-a)", "var(--fd-person-b)", "#ef6c00", "#5e35b1", "#6d4c41"];

/*FB-START*/
const FB = {
  de: {
    "cd.income": "Einnahmen",
    "cd.expenses": "Ausgaben",
    "cd.surplus": "Überschuss",
    "cd.cycle": "Zyklus",
    "cd.day": "Tag $current von $total",
    "cd.cycle.current": "Dieser Zyklus",
    "cd.cycle.previous": "Letzter Zyklus",
    "cd.title.household": "Haushalt",
    "cd.title.person": "Deine Zahlen",
    "cd.vs_prev": "$delta zum Vorzyklus",
    "cd.no_prev": "kein Vergleichszyklus",
    "cd.same": "wie im Vorzyklus",
    "cd.pending": "Gehalt erwartet am $date",
    "cd.pending_nodate": "Gehalt noch erwartet",
    "cd.empty": "In diesem Zyklus sind noch keine Buchungen.",
    "cd.empty.action": "Zum Datenstand",
    "cd.nc": "Der Haushalt ist noch nicht eingerichtet.",
    "cd.nc.action": "Einrichtung starten",
    "cd.error": "Die Zyklusübersicht konnte nicht geladen werden.",
    "cd.retry": "Erneut versuchen",
    "cd.loading": "Wird geladen …",
    "cd.desktop": "Nur am Desktop",
    "cd.analysis": "Analyse",
    "cd.savings": "Sparquote",
    "cd.savings.none": "noch kein Einkommen im Zyklus",
    "cd.fixvar": "Fix und variabel",
    "cd.fixed": "Fix",
    "cd.variable": "Variabel",
    "cd.fixvar.none": "Noch keine Ausgaben in diesem Zyklus.",
    "cd.owners": "Wer trägt was",
    "cd.owner.shared": "Haushalt",
    "cd.owner.open": "Nicht zugeordnet",
    "cd.owner.restricted": "nur Summe sichtbar",
    "cd.owner.spent": "Ausgaben $amount",
    "cd.owner.fix": "fix $amount",
    "cd.owner.var": "variabel $amount",
    "cd.owner.surplus": "Überschuss $amount",
    "cd.owners.say": "Der Haushalt trägt $shared der Ausgaben, auf Personen entfallen $persons.",
    "cd.open.say": "$amount Ausgaben gehören noch keinem Konto-Besitzer.",
    "cd.open.action": "Konten zuordnen",
    "cd.pva": "Haushaltsplan gegen Ist",
    "cd.pva.sub": "$month, Kalendermonat",
    "cd.pva.total": "Geplant $plan · bisher $actual",
    "cd.pva.ok": "passt",
    "cd.pva.near": "knapp",
    "cd.pva.over": "drüber",
    "cd.pva.unmatched": "$n Planpositionen ohne passende Buchung",
    "cd.pva.restricted": "Die Aufschlüsselung nach Kategorie sehen nur Administratoren.",
    "cd.pva.none": "Noch keine Buchungen, die sich mit dem Plan vergleichen lassen.",
    "cd.plan.empty": "Noch kein Haushaltsplan.",
    "cd.plan.action": "Haushaltsplan erstellen",
    "cd.plan.gate": "Haushaltsplan ab ca. $date möglich.",
    "cd.plan.gate_nodata": "Haushaltsplan möglich, sobald 3 volle Monate Buchungen da sind.",
    "cd.restricted": "Details zu einzelnen Konten sind nur für Administratoren sichtbar.",
  },
  en: {
    "cd.income": "Income",
    "cd.expenses": "Expenses",
    "cd.surplus": "Surplus",
    "cd.cycle": "Cycle",
    "cd.day": "Day $current of $total",
    "cd.cycle.current": "This cycle",
    "cd.cycle.previous": "Last cycle",
    "cd.title.household": "Household",
    "cd.title.person": "Your figures",
    "cd.vs_prev": "$delta vs. previous cycle",
    "cd.no_prev": "no comparison cycle",
    "cd.same": "same as previous cycle",
    "cd.pending": "Salary expected on $date",
    "cd.pending_nodate": "Salary still expected",
    "cd.empty": "There are no bookings in this cycle yet.",
    "cd.empty.action": "Go to data status",
    "cd.nc": "The household is not set up yet.",
    "cd.nc.action": "Start setup",
    "cd.error": "The cycle overview could not be loaded.",
    "cd.retry": "Try again",
    "cd.loading": "Loading …",
    "cd.desktop": "Desktop only",
    "cd.analysis": "Analysis",
    "cd.savings": "Savings rate",
    "cd.savings.none": "no income in this cycle yet",
    "cd.fixvar": "Fixed and variable",
    "cd.fixed": "Fixed",
    "cd.variable": "Variable",
    "cd.fixvar.none": "No expenses in this cycle yet.",
    "cd.owners": "Who carries what",
    "cd.owner.shared": "Household",
    "cd.owner.open": "Not assigned",
    "cd.owner.restricted": "totals only",
    "cd.owner.spent": "Expenses $amount",
    "cd.owner.fix": "fixed $amount",
    "cd.owner.var": "variable $amount",
    "cd.owner.surplus": "Surplus $amount",
    "cd.owners.say": "The household carries $shared of the expenses, persons account for $persons.",
    "cd.open.say": "$amount of expenses do not belong to an account owner yet.",
    "cd.open.action": "Assign accounts",
    "cd.pva": "Household plan vs. actual",
    "cd.pva.sub": "$month, calendar month",
    "cd.pva.total": "Planned $plan · so far $actual",
    "cd.pva.ok": "on track",
    "cd.pva.near": "close",
    "cd.pva.over": "over",
    "cd.pva.unmatched": "$n plan positions without a matching booking",
    "cd.pva.restricted": "Only administrators see the breakdown by category.",
    "cd.pva.none": "No bookings yet that can be compared with the plan.",
    "cd.plan.empty": "No household plan yet.",
    "cd.plan.action": "Create household plan",
    "cd.plan.gate": "Household plan possible from about $date.",
    "cd.plan.gate_nodata": "Household plan possible once 3 full months of bookings are in.",
    "cd.restricted": "Details of individual accounts are visible to administrators only.",
  },
};
/*FB-END*/

/** Plan gate (GET plan_wizard/gate), shared and cached for 60 s; null when unknown or not allowed. */
function planGate(hass) {
  const fd = window._fd;
  if (!fd._planGate || Date.now() - fd._planGate.at > 60000) {
    fd._planGate = { at: Date.now(), p: hass.callApi("GET", "finance_dashboard/plan_wizard/gate").catch(() => null) };
  }
  return fd._planGate.p;
}

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
.root { container: cd / inline-size; color: var(--fd-t1); font-size: 13px; line-height: 1.4; min-width: 0; overflow-wrap: anywhere; }
button { font: inherit; color: inherit; cursor: pointer; }
button:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
.card { margin: 0 0 12px; padding: 12px 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); min-width: 0; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 6px 12px; flex-wrap: wrap; margin-bottom: 8px; }
.head h3 { margin: 0; font-size: 15px; font-weight: 500; }
.sub, .lab { color: var(--fd-t2); font-size: 11.5px; }
.seg { display: inline-flex; max-width: 100%; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); overflow: hidden; }
.seg button { min-height: 36px; padding: 0 12px; border: 0; background: transparent; white-space: nowrap; }
.seg button:hover:not([aria-checked="true"]) { background: var(--fd-sunk); }
.seg button[aria-checked="true"] { background: var(--fd-a50); color: var(--fd-a900); font-weight: 500; }
.strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.cell { min-width: 0; padding: 8px 10px; border-radius: 10px; background: var(--fd-sunk); }
.cell .val { margin: 2px 0; font-size: clamp(13px, 4.7cqw, 24px); font-weight: 500; line-height: 1.15; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.cell .val.ok { color: var(--fd-ok); }
.cell .dl { color: var(--fd-t2); font-size: 11px; line-height: 1.3; overflow-wrap: anywhere; }
.quiet { margin: 8px 0 0; color: var(--fd-t2); font-size: 12px; }
.link { display: inline-flex; align-items: center; min-height: var(--fd-touch); padding: 0 4px; border: 0; background: transparent; color: var(--fd-a700); font-weight: 500; }
.btn { min-height: var(--fd-touch); padding: 0 16px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; }
.btn.ghost { background: transparent; color: var(--fd-a700); border-color: var(--fd-a100); }
.dtag { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: var(--fd-r-pill); font-size: 10.5px; font-weight: 500; background: var(--fd-desktop-bg); color: var(--fd-desktop); white-space: nowrap; }
.dtag::before { content: "\\25C6"; font-size: 8px; }
.dsk { display: none; }
@media (min-width: 1024px) { :host(:not([layout="strip"])) .dsk { display: block; } }
:host([layout="full"]) .dsk { display: block; }
.dsk .card { border: 1px dashed var(--fd-desktop); box-shadow: none; }
.dsk h4 { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin: 0 0 8px; font-size: 14px; font-weight: 500; }
.bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; background: var(--fd-sunk); }
.bar div { height: 100%; }
.leg { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 8px; }
.leg span { display: inline-flex; align-items: center; gap: 6px; }
.leg i { flex: none; width: 8px; height: 8px; border-radius: 50%; }
.leg b { font-weight: 500; font-variant-numeric: tabular-nums; }
.own { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 12px; padding: 8px 0 8px 12px; border-left: 4px solid var(--c); margin-top: 6px; }
.own .nm { flex: 1 1 120px; min-width: 0; font-weight: 500; }
.own .big { font-variant-numeric: tabular-nums; font-weight: 500; }
.own .sm { flex: 1 1 100%; color: var(--fd-t2); font-size: 11.5px; display: flex; flex-wrap: wrap; gap: 2px 12px; }
.act { display: flex; align-items: center; justify-content: space-between; gap: 4px 12px; flex-wrap: wrap; margin-top: 8px; padding: 6px 12px; border-radius: 10px; background: var(--fd-near-bg); }
.cat { padding: 8px 0; }
.cat + .cat { border-top: 1px solid var(--fd-line); }
.cat .top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.cat .top b { font-weight: 500; min-width: 0; }
.cat .top span { flex: none; font-variant-numeric: tabular-nums; }
.cmp { position: relative; height: 8px; margin-top: 6px; border-radius: 4px; background: var(--fd-sunk); }
.cmp > i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 4px; background: var(--c); }
.cmp > b { position: absolute; top: -3px; width: 2px; height: 14px; margin-left: -1px; background: var(--fd-t1); }
.st-ok { --c: var(--fd-ok); }
.st-near { --c: var(--fd-near); }
.st-over { --c: var(--fd-over); }
.chip { display: inline-flex; padding: 0 8px; border-radius: var(--fd-r-pill); font-size: 10.5px; font-weight: 500; background: var(--fd-sunk); color: var(--c, var(--fd-t2)); }
`;

class FdCycleDetail extends HTMLElement {
  static get observedAttributes() { return ["view", "person", "cycle"]; }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._view = "household";
    this._person = "";
    this._cycle = "current";
    this._sum = null;
    this._pva = null;
    this._plan = null;
    this._state = "loading"; // loading | ok | nc | error
    this._seq = 0;
    this._built = false;
  }

  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) this.reload();
  }
  get hass() { return this._hass; }

  get view() { return this._view; }
  set view(v) { const n = v === "person" ? "person" : "household"; if (n !== this._view) { this._view = n; this._sum = this._pva = this._plan = null; this.reload(); } }
  get person() { return this._person; }
  set person(v) { this._person = v == null ? "" : String(v); if (this._built) this._render(); }
  get cycle() { return this._cycle; }
  set cycle(v) { const n = v === "previous" ? "previous" : "current"; if (n !== this._cycle) { this._cycle = n; this.reload(); } }

  attributeChangedCallback(name, _old, val) {
    if (name === "view") this.view = val;
    else if (name === "person") this.person = val;
    else if (name === "cycle") this.cycle = val;
  }

  /** The panel pushes new data on every refresh; re-read then. */
  set data(_v) { if (this._hass && this._built) this.reload(); }

  async reload() {
    if (!this._hass) return;
    const seq = ++this._seq;
    await window._fd.t("cd.income");
    if (!this._built) { this._built = true; this._bind(); }
    if (!this._sum) { this._state = "loading"; this._render(); }
    const person = this._view === "person";
    const call = (p) => this._hass.callApi("GET", `${DOMAIN}/${p}`);
    try {
      const [sum, pva, plan, gate] = await Promise.all([
        call(`household_summary?cycle=${this._cycle}${person ? "&view=person" : ""}`),
        person ? Promise.resolve(null) : call("plan_vs_actual").catch(() => null),
        call("budget_plan").catch(() => null),
        planGate(this._hass),
      ]);
      if (seq !== this._seq) return;
      this._sum = sum;
      this._pva = pva;
      this._plan = plan;
      this._gate = gate;
      this._state = "ok";
    } catch (e) {
      if (seq !== this._seq) return;
      this._state = e && e.status_code === 404 ? "nc" : "error";
    }
    this._render();
  }

  _bind() {
    this.shadowRoot.addEventListener("click", (ev) => {
      const t = ev.target.closest("[data-act],[data-cycle]");
      if (!t) return;
      if (t.dataset.cycle) { this.cycle = t.dataset.cycle; return; }
      const nav = (detail) => this.dispatchEvent(new CustomEvent("fd-navigate", { bubbles: true, composed: true, detail }));
      switch (t.dataset.act) {
        case "setup": nav({ target: "setup" }); break;
        case "planwizard": this.dispatchEvent(new CustomEvent("fd-open-plan-wizard", { bubbles: true, composed: true })); break;
        case "assign": nav({ target: "settings", section: "accounts" }); break;
        case "freshness": nav({ target: "freshness" }); break;
        case "retry": this.reload(); break;
        default: break;
      }
    });
  }

  _delta(line) {
    if (!line || line.delta == null) return tr("cd.no_prev");
    if (Math.abs(line.delta) < 0.005) return tr("cd.same");
    return tr("cd.vs_prev", { delta: `${line.delta > 0 ? "+" : "−"}${window._fd.eur(Math.abs(line.delta))}` });
  }

  _lang() { return (window._fd._hass && window._fd._hass.language) || navigator.language || "de"; }

  _render() {
    if (!this._built) return;
    const { SHARED_CSS } = window._fd;
    let body;
    if (this._state === "loading") body = `<div class="card"><p class="quiet" style="margin:0">${tr("cd.loading")}</p></div>`;
    else if (this._state === "nc") {
      body = `<div class="card"><p class="quiet" style="margin:0">${tr("cd.nc")}</p>
        <button class="link" data-act="setup">${tr("cd.nc.action")}</button></div>`;
    } else if (this._state === "error") {
      body = `<div class="card"><p class="quiet" style="margin:0">${tr("cd.error")}</p>
        <button class="link" data-act="retry">${tr("cd.retry")}</button></div>`;
    } else body = this._body(this._sum || {});
    this.shadowRoot.innerHTML = `<style>${SHARED_CSS}${CSS}</style><div class="root">${body}</div>`;
  }

  _body(s) {
    const { eur, escHtml } = window._fd;
    const e = escHtml;
    const c = s.cycle || {};
    const L = s.lines || {};
    const income = s.income || 0, expenses = s.expenses || 0, surplus = s.surplus || 0;
    const pending = !!s.income_pending;
    const lang = this._lang();
    const fmtD = (iso) => (iso ? new Date(iso + "T00:00:00").toLocaleDateString(lang, { day: "numeric", month: "numeric" }) : "");
    const range = c.start && c.end ? `${fmtD(c.start)} – ${fmtD(c.end)}` : "";
    const isCur = (c.selected || this._cycle) === "current";
    const isPerson = this._view === "person";
    const titleTxt = isPerson ? (this._person ? `${this._person}` : tr("cd.title.person")) : tr("cd.title.household");

    const head = `<div class="head">
  <div><h3>${e(titleTxt)}</h3>
    <div class="sub">${e(tr("cd.cycle"))} ${e(range)}${isCur && c.day ? ` · ${e(tr("cd.day", { current: c.day, total: c.days }))}` : ""}</div></div>
  <div class="seg" role="radiogroup" aria-label="${e(tr("cd.cycle"))}">
    <button role="radio" data-cycle="current" aria-checked="${this._cycle === "current"}">${e(tr("cd.cycle.current"))}</button>
    <button role="radio" data-cycle="previous" aria-checked="${this._cycle === "previous"}">${e(tr("cd.cycle.previous"))}</button>
  </div>
</div>`;

    const empty = income === 0 && expenses === 0 && !pending;
    const money = (v) => `${v < 0 ? "−" : ""}${eur(Math.abs(v))}`;
    const incomeSub = pending
      ? (s.expected_income_date ? tr("cd.pending", { date: fmtD(s.expected_income_date) }) : tr("cd.pending_nodate"))
      : this._delta(L.income);
    const cell = (lab, val, sub, cls = "") => `<div class="cell"><div class="lab">${e(lab)}</div>
  <div class="val ${cls}">${empty ? "–" : e(val)}</div><div class="dl">${e(empty ? "" : sub)}</div></div>`;
    const strip = `<div class="strip">
  ${cell(tr("cd.income"), money(income), incomeSub)}
  ${cell(tr("cd.expenses"), money(expenses), this._delta(L.expenses))}
  ${cell(tr("cd.surplus"), money(surplus), this._delta(L.surplus), surplus >= 0 ? "ok" : "")}
</div>
${empty ? `<p class="quiet">${e(tr("cd.empty"))} <button class="link" data-act="freshness">${e(tr("cd.empty.action"))}</button></p>` : ""}`;

    return `<section class="card">${head}${strip}</section>${empty ? "" : this._analysis(s)}`;
  }

  /** Desktop-only analysis (hidden by CSS on mobile). */
  _analysis(s) {
    const { eur, escHtml: e } = window._fd;
    const isPerson = this._view === "person";
    const expenses = s.expenses || 0;
    const fixed = s.fixed, variable = s.variable;
    const restricted = s.privacy === "restricted" && !isPerson;
    const parts = [];

    // Savings rate: never a number without income.
    const sav = s.savings_rate != null
      ? `${Math.round(s.savings_rate * (Math.abs(s.savings_rate) <= 1.5 ? 100 : 1))} %`
      : null;

    // Fixed vs. variable (own figures; hidden when the API withholds the split).
    if (fixed != null && variable != null) {
      const tot = fixed + variable;
      const fp = tot > 0 ? (fixed / tot) * 100 : 0;
      parts.push(`<section class="card"><h4><span>${e(tr("cd.fixvar"))}</span>${sav ? `<span class="sub">${e(tr("cd.savings"))} ${e(sav)}</span>` : ""}</h4>
  ${tot > 0 ? `<div class="bar" role="img" aria-label="${e(tr("cd.fixvar"))}"><div style="width:${fp}%;background:var(--fd-a700)"></div><div style="width:${100 - fp}%;background:var(--fd-a300)"></div></div>
  <div class="leg"><span><i style="background:var(--fd-a700)"></i>${e(tr("cd.fixed"))} <b>${e(eur(fixed))}</b></span><span><i style="background:var(--fd-a300)"></i>${e(tr("cd.variable"))} <b>${e(eur(variable))}</b></span></div>`
    : `<p class="quiet" style="margin:0">${e(tr("cd.fixvar.none"))}</p>`}</section>`);
    }

    // Owner split (household view only; the person view is one's own row).
    const owners = s.owners || [];
    if (!isPerson && owners.length) {
      let pi = 0;
      const rows = owners.map((o) => {
        const kind = o.kind || "person";
        const color = kind === "shared" ? "var(--fd-household)" : kind === "open" ? "var(--fd-t3)" : PERSON_COLORS[pi++ % PERSON_COLORS.length];
        const name = kind === "shared" ? tr("cd.owner.shared") : kind === "open" ? tr("cd.owner.open") : o.owner;
        const small = o.restricted
          ? `<div class="sm">${e(tr("cd.owner.restricted"))}</div>`
          : `<div class="sm">${o.fixed != null ? `<span>${e(tr("cd.owner.fix", { amount: eur(o.fixed) }))}</span>` : ""}
        ${o.variable != null ? `<span>${e(tr("cd.owner.var", { amount: eur(o.variable) }))}</span>` : ""}
        ${kind === "person" ? `<span>${e(tr("cd.owner.surplus", { amount: eur(o.surplus || 0) }))}</span>` : ""}</div>`;
        return `<div class="own" style="--c:${color}"><span class="nm">${e(name)}</span><span class="big">${e(tr("cd.owner.spent", { amount: eur(o.expenses || 0) }))}</span>${small}</div>`;
      });
      const sum = (k) => owners.filter((o) => o.kind === k).reduce((a, o) => a + (o.expenses || 0), 0);
      const openExp = sum("open");
      parts.push(`<section class="card"><h4><span>${e(tr("cd.owners"))}</span></h4>${rows.join("")}
  ${expenses > 0 ? `<p class="quiet">${e(tr("cd.owners.say", { shared: eur(sum("shared")), persons: eur(sum("person")) }))}</p>` : ""}
  ${openExp > 0 ? `<div class="act"><span>${e(tr("cd.open.say", { amount: eur(openExp) }))}</span><button class="link" data-act="assign">${e(tr("cd.open.action"))}</button></div>` : ""}
  ${restricted ? `<p class="quiet">${e(tr("cd.restricted"))}</p>` : ""}</section>`);
    }

    parts.push(this._planBlock());
    const mark = `<p class="sub" style="margin:0 0 8px"><span class="dtag">${window._fd.escHtml(tr("cd.desktop"))}</span> ${window._fd.escHtml(tr("cd.analysis"))}</p>`;
    return `<div class="dsk">${mark}${parts.join("")}</div>`;
  }

  /** Plan vs. actual; an empty plan is one quiet line, not an empty box. */
  _planBlock() {
    const { eur, escHtml: e, CAT_LABELS } = window._fd;
    if (this._view === "person") return "";
    const plan = this._plan;
    const pva = this._pva;
    const planKnown = plan != null;
    if (!planKnown || plan.is_empty) {
      if (!planKnown && !pva) return "";
      const g = this._gate;
      if (g && !g.ready) {
        return `<p class="quiet">${e(tr("cd.plan.empty"))} ${e(g.ready_from ? tr("cd.plan.gate", { date: window._fd.fmtDate(g.ready_from) }) : tr("cd.plan.gate_nodata"))}</p>`;
      }
      return `<p class="quiet">${e(tr("cd.plan.empty"))} <button class="link" data-act="planwizard">${e(tr("cd.plan.action"))}</button></p>`;
    }
    const month = pva && pva.month
      ? new Date(pva.year || new Date().getFullYear(), pva.month - 1, 1).toLocaleDateString(this._lang(), { month: "long" })
      : "";
    const title = `<h4><span>${e(tr("cd.pva"))}</span><span class="sub">${e(month ? tr("cd.pva.sub", { month }) : "")}</span></h4>`;
    if (!pva) return "";
    if (pva.restricted) {
      return `<section class="card">${title}<p class="quiet" style="margin:0">${e(tr("cd.pva.restricted"))}</p></section>`;
    }
    const cats = (pva.categories || []).filter((x) => !SKIP_CATS.has(x.category) && ((x.planned || 0) > 0 || (x.actual || 0) > 0));
    if (!cats.length || !pva.has_actuals) {
      return `<section class="card">${title}<p class="quiet" style="margin:0">${e(tr("cd.pva.none"))}</p></section>`;
    }
    cats.sort((a, b) => Math.max(b.planned || 0, b.actual || 0) - Math.max(a.planned || 0, a.actual || 0));
    const planTot = cats.reduce((a, x) => a + (x.planned || 0), 0);
    const actTot = cats.reduce((a, x) => a + (x.actual || 0), 0);
    const status = (plan_, act) => {
      if (!(plan_ > 0)) return act > 0 ? "over" : "ok";
      const r = act / plan_;
      return r <= 1 ? "ok" : r <= 1.1 ? "near" : "over";
    };
    const row = (x) => {
      const p = x.planned || 0, a = x.actual || 0;
      const mx = Math.max(p, a, 1);
      const st = status(p, a);
      const label = CAT_LABELS[x.category] || x.category;
      return `<div class="cat st-${st}"><div class="top"><b>${e(label)}</b><span>${e(eur(a))} / ${e(eur(p))}</span></div>
  <div class="cmp" role="img" aria-label="${e(label)}: ${e(tr(`cd.pva.${st}`))}"><i style="width:${(a / mx) * 100}%"></i><b style="left:${(p / mx) * 100}%"></b></div>
  <span class="chip">${e(tr(`cd.pva.${st}`))}</span></div>`;
    };
    const un = pva.unmatched_positions || 0;
    return `<section class="card">${title}
  <p class="quiet" style="margin:0 0 4px">${e(tr("cd.pva.total", { plan: eur(planTot), actual: eur(actTot) }))}</p>
  ${cats.map(row).join("")}
  ${un > 0 ? `<p class="quiet">${e(tr("cd.pva.unmatched", { n: un }))}</p>` : ""}</section>`;
  }
}

window._fd.defineOnce("fd-cycle-detail", FdCycleDetail);
