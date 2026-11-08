/**
 * fd-budget-plan — the household plan, set against what the bank shows.
 *
 * The plan (what the household budgeted: positions with an explicit owner,
 * income per person) exists independently of any bank link. The actual is live
 * bank data. They are never merged: plan amounts are expenses-positive, bank
 * amounts are expenses-negative and are flipped once (see toPlanSign, the
 * mirror of budget_plan.actual_amount_to_plan_sign).
 *
 * Every view combines dimensions - plan x actual x owner x fixed/variable -
 * says what it means and where action is needed. Status is carried by colour
 * and words (passt / knapp / drüber), never red.
 *
 * Mobile: a simple card summary (verdict, fixed/variable, owners, categories,
 * the shared fixed costs). Desktop (container >= 760px): the detail tables
 * (income, cost ledger per owner, transfers, benchmark), marked purple.
 *
 * Loads its own plan data from the plan endpoints. The actual comes from
 * window._fd._actual (published by fd-household-section) or the `data`
 * property; without it only the plan side is shown.
 *
 * Properties:
 *   hass  {object} — Home Assistant connection
 *   month {number} — optional month override
 *   year  {number} — optional year override
 *   data  {object} — optional actual data (fd-data-provider shape)
 */

const OWNER_SHARED = "__shared__";
const PERSON_COLORS = [
  "var(--fd-person-a)", "var(--fd-person-b)", "#5d4037", "#455a64", "#9e9d24",
];
const SKIP_CATS = { has: (k) => k === "transfers" || String(k).startsWith("income") };

/** Plan gate (GET plan_wizard/gate), shared and cached for 60 s; null when unknown or not allowed. */
function planGate(hass) {
  const fd = window._fd;
  if (!fd._planGate || Date.now() - fd._planGate.at > 60000) {
    fd._planGate = { at: Date.now(), p: hass.callApi("GET", "finance_dashboard/plan_wizard/gate").catch(() => null) };
  }
  return fd._planGate.p;
}

/** New texts: locale key if present, else inline de/en default (never a raw key). */
function T(key, de, en, vars = {}) {
  const f = window._fd;
  const s = f.tSync(key, vars);
  if (s !== key) return s;
  const raw = ((f._hass && f._hass.language) || navigator.language || "en").toLowerCase();
  let text = raw.startsWith("de") ? de : en;
  for (const [k, v] of Object.entries(vars)) text = text.replace(new RegExp(`\\$${k}`, "g"), String(v));
  return text;
}

/** Bank sign (expense negative) -> plan sign (expense positive). */
const toPlanSign = (bank) => -(bank || 0);

/** passt / knapp / drüber from actual vs plan (both expense-positive). */
function status(plan, actual) {
  if (!(plan > 0)) return actual > 0 ? "over" : "ok";
  const r = actual / plan;
  return r <= 1.02 ? "ok" : r <= 1.1 ? "near" : "over";
}

class FdBudgetPlan extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._plan = null;
    this._transfer = null;
    this._error = null;
    this._loading = false;
    this._loaded = false;
    this._data = null;
    this._onActual = () => this._render();
  }

  set hass(v) {
    const first = this._hass === null;
    this._hass = v;
    if (first) this._load();
  }

  get hass() {
    return this._hass;
  }

  set month(v) { this._month = v; this._load(); }
  set year(v) { this._year = v; this._load(); }
  set data(v) { this._data = v; this._render(); }

  connectedCallback() {
    window.addEventListener("fd-actual-data", this._onActual);
    if (!this._ctaBound) {
      this._ctaBound = true;
      // Empty-plan CTA: ask the panel to open the plan wizard (fd-open-plan-wizard).
      this.shadowRoot.addEventListener("click", (ev) => {
        if (ev.target.closest('[data-act="planwizard"]')) {
          this.dispatchEvent(new CustomEvent("fd-open-plan-wizard", { bubbles: true, composed: true }));
        }
      });
    }
    this._render();
  }

  disconnectedCallback() {
    window.removeEventListener("fd-actual-data", this._onActual);
  }

  /** Button while the plan gate is open (or unknown); otherwise the expected date. */
  _planCta() {
    const g = this._gate;
    if (g && !g.ready) {
      const when = g.ready_from ? window._fd.fmtDate(g.ready_from) : "";
      return `<span class="muted" role="status">${when ? T("home.plan.gate", "Haushaltsplan ab ca. $date möglich", "Household plan possible from about $date", { date: when }) : T("home.plan.gate_nodata", "Haushaltsplan möglich, sobald 3 volle Monate Buchungen da sind", "Household plan possible once 3 full months of bookings are in")}</span>`;
    }
    return `<button type="button" data-act="planwizard" style="min-height:var(--fd-touch);padding:0 16px;border:0;border-radius:var(--fd-r-pill);background:var(--fd-a700);color:#fff;font:inherit;font-weight:500;cursor:pointer">${T("hh.plan.cta", "Haushaltsplan erstellen", "Create household plan")}</button>`;
  }

  /** Reload all plan data. Safe to call repeatedly; overlapping calls are dropped. */
  async _load() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._error = null;
    this._render();

    const qs = [];
    if (this._month) qs.push(`month=${this._month}`);
    if (this._year) qs.push(`year=${this._year}`);
    const suffix = qs.length ? `?${qs.join("&")}` : "";

    try {
      // Fetched in parallel — none depends on another.
      const [plan, transfer] = await Promise.all([
        this._hass.callApi("GET", `finance_dashboard/budget_plan${suffix}`),
        this._hass
          .callApi("GET", `finance_dashboard/transfer_plan${suffix}`)
          .catch(() => null),
      ]);
      this._plan = plan;
      this._transfer = transfer;
      this._loaded = true;
    } catch (err) {
      this._error = (err && err.message) || T("hh.plan.load_error", "Haushaltsplan konnte nicht geladen werden", "Could not load the household plan");
    } finally {
      this._loading = false;
      this._render();
    }
    if (this._plan && this._plan.is_empty) {
      planGate(this._hass).then((g) => { this._gate = g; this._render(); });
    }
  }

  /** Public: re-fetch after an import or an edit. */
  refresh() {
    this._loaded = false;
    this._load();
  }

  /** Category key shared by plan (free text) and bank (keys). */
  _catKey(raw) {
    const { CAT_COLORS, CAT_LABELS } = window._fd;
    const s = String(raw || "").trim().toLowerCase();
    if (!s) return "other";
    if (CAT_COLORS[s]) return s;
    for (const [k, label] of Object.entries(CAT_LABELS)) {
      if (label.toLowerCase() === s) return k;
    }
    return s;
  }

  /** Plan x actual numbers, one object the views draw from. */
  _model(plan) {
    const actual = this._data || (window._fd && window._fd._actual) || null;
    const sum = actual && actual.summary;
    const hasActual = !!(sum && (sum.totalExpenses || 0) > 0);
    const pos = (plan.positions || []).filter((p) => p.is_active);
    const isVar = (p) => p.kind === "buffer";

    const m = {
      hasActual,
      planTotal: plan.costs ? plan.costs.grand_total : pos.reduce((a, p) => a + p.effective_amount, 0),
      planFixed: pos.filter((p) => !isVar(p)).reduce((a, p) => a + p.effective_amount, 0),
      planVar: pos.filter(isVar).reduce((a, p) => a + p.effective_amount, 0),
      actTotal: hasActual ? sum.totalExpenses : 0,
      actFixed: hasActual ? sum.fixedCosts || 0 : 0,
      actVar: hasActual ? sum.variableCosts || 0 : 0,
      owners: [],
      cats: [],
    };

    // Owner rows: ours first, then each person in plan order.
    const hh = actual && actual.household;
    const persons = plan.persons || [];
    const ind = (plan.costs && plan.costs.individual) || {};
    m.owners.push({
      key: OWNER_SHARED, color: "var(--fd-household)",
      plan: plan.costs ? plan.costs.shared : 0,
      act: hh ? hh.total_shared_costs || 0 : null,
    });
    persons.forEach((p, i) => {
      const mem = hh && (hh.members || []).find((x) => x.person === p);
      m.owners.push({
        key: p, color: PERSON_COLORS[i % PERSON_COLORS.length],
        plan: ind[p] || 0, act: mem ? mem.individual_costs || 0 : null,
      });
    });

    // Categories: plan (fixed/variable) against the bank's category totals.
    const cats = new Map();
    const row = (k) => {
      if (!cats.has(k)) cats.set(k, { key: k, planFix: 0, planVar: 0, act: 0 });
      return cats.get(k);
    };
    for (const p of pos) {
      const r = row(this._catKey(p.category));
      if (isVar(p)) r.planVar += p.effective_amount; else r.planFix += p.effective_amount;
    }
    if (hasActual) {
      for (const [k, v] of Object.entries(sum.categories || {})) {
        if (SKIP_CATS.has(k)) continue;
        const a = Math.max(0, toPlanSign(v));
        if (a > 0) row(k).act += a;
      }
    }
    m.cats = [...cats.values()]
      .map((c) => ({ ...c, plan: c.planFix + c.planVar }))
      .filter((c) => c.plan > 0 || c.act > 0)
      .sort((a, b) => Math.max(b.plan, b.act) - Math.max(a.plan, a.act));
    return m;
  }

  _render() {
    const { SHARED_CSS, escHtml } = window._fd || {};
    if (!SHARED_CSS) return;

    const LOCAL_CSS = `
:host { display: block; margin-bottom: 14px; min-width: 0; }
.root, .cols > * { min-width: 0; }
.root { overflow-wrap: anywhere; }
.root { container: bp / inline-size; color: var(--fd-t1); font-size: 13px; line-height: 1.4; }
.card { margin: 0 0 12px; padding: 12px 14px; border: 0; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); }
.h { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 4px 8px; margin: 0 0 8px; font-size: 14px; font-weight: 500; }
.h .sub { font-size: 11.5px; font-weight: 400; color: var(--fd-t2); }
.muted { color: var(--fd-t2); }
.st-ok { --c: var(--fd-ok); --cbg: var(--fd-ok-bg); --cfg: color-mix(in srgb, var(--fd-ok) 72%, var(--fd-t1)); }
.st-near { --c: var(--fd-near); --cbg: var(--fd-near-bg); --cfg: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
.st-over { --c: var(--fd-over); --cbg: var(--fd-over-bg); --cfg: color-mix(in srgb, var(--fd-over) 72%, var(--fd-t1)); }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 1px 9px; border-radius: var(--fd-r-pill); font-size: 11.5px; font-weight: 500; white-space: nowrap; background: var(--cbg); color: var(--cfg); }
.tag { display: inline-block; margin-left: 6px; padding: 0 7px; border: 1px dashed var(--fd-t3); border-radius: var(--fd-r-pill); font-size: 10.5px; color: var(--fd-t2); white-space: nowrap; }
.tag.fix { border-style: solid; border-color: var(--fd-line); background: var(--fd-sunk); }
.dtag { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: var(--fd-r-pill); font-size: 10.5px; font-weight: 500; background: var(--fd-desktop-bg); color: var(--fd-desktop); white-space: nowrap; }
.dtag::before { content: "\\25C6"; font-size: 8px; }
.hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; }
.big { font-size: 34px; font-weight: 500; line-height: 1.05; color: var(--cfg, var(--fd-t1)); }
.cap { margin-top: 4px; font-size: 12.5px; color: var(--fd-t2); }
.meter { position: relative; height: 12px; margin: 14px 0 4px; border-radius: 6px; background: var(--fd-sunk); }
.meter > i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 6px; background: var(--c); }
.meter > b { position: absolute; top: -5px; width: 3px; height: 22px; margin-left: -1.5px; border-radius: 2px; background: var(--fd-t1); box-shadow: 0 0 0 2px var(--fd-card); }
.scale { display: flex; justify-content: space-between; font-size: 11px; color: var(--fd-t2); }
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
.tile { padding: 8px 10px; border-radius: 10px; background: var(--fd-sunk); }
.tile span.l { display: flex; justify-content: space-between; align-items: center; gap: 6px; font-size: 11.5px; color: var(--fd-t2); }
.tile b { display: block; margin-top: 2px; font-size: 17px; font-weight: 500; }
.tile small { color: var(--fd-t2); font-size: 11px; }
.orow { display: grid; grid-template-columns: 6px 1fr auto; align-items: center; column-gap: 10px; padding: 9px 0; }
.orow + .orow { border-top: 1px solid var(--fd-line); }
.orow > i { align-self: stretch; border-radius: 3px; background: var(--oc); }
.orow > span { display: flex; flex-direction: column; min-width: 0; }
.orow > span b { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.orow > div { display: flex; align-items: center; gap: 8px; }
.orow em { font-style: normal; font-size: 16px; font-weight: 500; white-space: nowrap; }
.cat { padding: 8px 0; }
.cat + .cat { border-top: 1px solid var(--fd-line); }
.cat .top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.cat .top b { font-weight: 500; }
.cat .nums { white-space: nowrap; font-size: 12px; color: var(--fd-t2); }
.cat .nums strong { color: var(--cfg, var(--fd-t1)); font-weight: 500; }
.cmp { position: relative; height: 8px; margin-top: 6px; border-radius: 4px; background: var(--fd-sunk); }
.cmp > i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 4px; background: var(--c, var(--fd-a500)); }
.cmp > b { position: absolute; top: -3px; width: 2px; height: 14px; margin-left: -1px; background: var(--fd-t1); }
.cat.extra { display: none; }
.ins { display: grid; grid-template-columns: 8px 1fr auto; gap: 4px 10px; align-items: start; padding: 8px 0; }
.ins + .ins { border-top: 1px solid var(--fd-line); }
.ins > i { width: 8px; height: 8px; margin-top: 5px; border-radius: 50%; background: var(--c); }
.ins .need { font-size: 11px; color: var(--cfg); white-space: nowrap; }
.prow { display: flex; justify-content: space-between; gap: 8px; padding: 7px 0; }
.pos + .prow { border-top: 1px solid var(--fd-line); }
.prow span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.prow span:last-child { white-space: nowrap; }
.dnote { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border: 1px dashed var(--fd-desktop); border-radius: var(--fd-r-card); background: var(--fd-desktop-bg); color: var(--fd-desktop); font-size: 12.5px; margin-bottom: 12px; }
.dsk { display: none; }
.dcard { border: 1px dashed var(--fd-desktop); background: var(--fd-card); }
.dcard > .h { color: var(--fd-t1); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 7px 10px; text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; white-space: normal; }
thead th { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--fd-t2); font-weight: 500; border-bottom: 1px solid var(--fd-line); }
tbody tr + tr td { border-top: 1px solid var(--fd-line); }
.sub td { font-weight: 500; background: var(--fd-sunk); }
.scroll { overflow-x: auto; }
.badge { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; padding: 1px 10px; border-radius: var(--fd-r-pill); font-weight: 500; }
.badge.ok { background: var(--fd-ok-bg); color: var(--fd-ok); }
.badge.warn { background: var(--fd-near-bg); color: var(--fd-near); }
.pockets { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }
.pocket { padding: 10px 12px; border-radius: 10px; background: var(--fd-sunk); }
.pocket .who { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--fd-t2); }
.pocket .dot { width: 8px; height: 8px; border-radius: 50%; }
.pocket .amt { margin-top: 2px; font-size: 20px; font-weight: 500; }
.pocket .brk { margin-top: 4px; font-size: 11px; color: var(--fd-t2); line-height: 1.5; }
.empty { padding: 4px 0; color: var(--fd-t2); line-height: 1.6; }
.empty code { display: block; margin-top: 10px; padding: 10px 12px; border-radius: 8px; background: var(--fd-sunk); font-size: 12px; white-space: pre-wrap; word-break: break-word; color: var(--fd-t1); }
@container bp (min-width: 640px) {
  .tiles { grid-template-columns: repeat(2, 1fr); }
  .cat.extra { display: block; }
}
@container bp (min-width: 760px) {
  .dsk { display: block; }
  .mob { display: none; }
  .big { font-size: 40px; }
  .cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; align-items: start; }
  .cols > .card { margin-bottom: 0; }
  .cols { margin-bottom: 12px; }
}
`;

    const title = T("hh.plan.title", "Haushaltsplan", "Household plan");
    const head = this.hasAttribute("embedded") ? "" : `<fd-subpage-header title="${escHtml(title)}"></fd-subpage-header>`;
    const wrap = (inner) => {
      this.shadowRoot.innerHTML = `<style>${SHARED_CSS}${LOCAL_CSS}</style><div class="root">${head}${inner}</div>`;
    };

    if (this._error) {
      wrap(`<div class="card"><div class="empty">${escHtml(this._error)}</div></div>`);
      return;
    }
    if (!this._loaded) {
      wrap(`<div class="card"><div class="empty">${T("hh.plan.loading", "Wird geladen …", "Loading …")}</div></div>`);
      return;
    }

    const plan = this._plan || {};
    if (plan.is_empty) {
      wrap(`<div class="card">
  <div class="empty">
    ${T("hh.plan.empty", "Noch kein Haushaltsplan vorhanden. Er entsteht aus deinen Buchungen: Einkommen, Fixkosten, Töpfe und Sparziele.", "No household plan yet. It is built from your bookings: income, fixed costs, pots and savings goals.")}
    <div style="margin-top:12px">${this._planCta()}</div>
  </div></div>`);
      return;
    }

    const m = this._model(plan);
    wrap(`
<div class="cols">${this._renderVerdict(m, escHtml)}</div>
<div class="cols">${this._renderOwners(m, escHtml)}
${this._renderCategories(m, escHtml)}</div>
${this._renderSharedList(plan, escHtml)}
<div class="mob dnote"><span class="dtag">${T("hh.desktop", "Nur am Desktop", "Desktop only")}</span>
  ${T("hh.mobile_note", "Einkommen, Positionen je Person und Umbuchungen findest du am Desktop.", "Income, positions per person and transfers are on desktop.")}</div>
<div class="dsk">
${this._renderPockets(plan, escHtml)}
${this._renderIncome(plan, escHtml)}
${this._renderLedger(plan, escHtml)}
${this._renderTransfer(escHtml)}
</div>`);
  }

  /** Hero: plan vs actual overall, fixed/variable, and what it means. */
  _renderVerdict(m, escHtml) {
    const { eur, CAT_LABELS } = window._fd;
    const ownerName = (o) => (o.key === OWNER_SHARED ? T("hh.ours.title", "Gemeinsam", "Ours") : o.key);
    const title = T("hh.verdict.title", "Plan gegen Ist", "Plan vs actual");
    const stLabel = (s) => (s === "ok" ? T("hh.status.ok", "passt", "fine")
      : s === "near" ? T("hh.status.near", "knapp", "tight") : T("hh.status.over", "drüber", "over"));

    if (!m.hasActual) {
      return `<div class="card"><div class="h">${title}<span class="sub">${T("hh.plan.month", "Haushaltsplan", "Household plan")}</span></div>
<div class="hero"><div><div class="big">${eur(m.planTotal)}</div>
<div class="cap">${T("hh.verdict.plan_only", "geplante Ausgaben im Monat – Ist-Daten folgen mit dem Bankabruf.", "planned spending per month – actuals follow with the bank fetch.")}</div></div></div>
<div class="tiles">
 <div class="tile"><span class="l">${T("hh.fixed", "Fix", "Fixed")}</span><b>${eur(m.planFixed)}</b></div>
 <div class="tile"><span class="l">${T("hh.variable", "Variabel", "Variable")}</span><b>${eur(m.planVar)}</b></div>
</div></div>`;
    }

    const st = status(m.planTotal, m.actTotal);
    const diff = m.actTotal - m.planTotal;
    const max = Math.max(m.planTotal, m.actTotal, 1) * 1.08;
    const verdict = diff > 0.5
      ? T("hh.verdict.over", "$d mehr als geplant", "$d more than planned", { d: eur(diff) })
      : T("hh.verdict.under", "$d unter Plan", "$d under plan", { d: eur(-diff) });

    const tile = (label, plan, act) => {
      const s = status(plan, act);
      return `<div class="tile st-${s}"><span class="l">${label}<span class="chip">${stLabel(s)}</span></span>
<b>${eur(act)}</b><small>${T("hh.plan.word", "Plan", "Plan")} ${eur(plan)}</small></div>`;
    };

    // Rule-based reading: what it means and where to act.
    const ins = [];
    ins.push(st === "ok"
      ? { s: "ok", t: T("hh.ins.total_ok", "Insgesamt im Plan.", "Overall on plan."), act: false }
      : { s: st, t: T("hh.ins.total_over", "Insgesamt $d über dem Plan – die Quelle steht unten.", "Overall $d over plan – the source is below.", { d: eur(Math.max(diff, 0)) }), act: true });
    const fixDiff = m.actFixed - m.planFixed;
    if (m.planFixed > 0 && Math.abs(fixDiff) / m.planFixed > 0.05) {
      ins.push({ s: fixDiff > 0 ? "over" : "near", act: true,
        t: T("hh.ins.fixed_off", "Fixkosten weichen um $d vom Plan ab – Plan oder Vertrag prüfen.", "Fixed costs differ from plan by $d – check the plan or the contract.", { d: eur(Math.abs(fixDiff)) }) });
    } else {
      ins.push({ s: "ok", act: false, t: T("hh.ins.fixed_ok", "Fixkosten laufen wie geplant.", "Fixed costs run as planned.") });
    }
    const varDiff = m.actVar - m.planVar;
    const worst = m.cats.filter((c) => c.act > c.plan && c.planFix === 0).sort((a, b) => (b.act - b.plan) - (a.act - a.plan))[0];
    if (varDiff > 0.5 && status(m.planVar, m.actVar) !== "ok") {
      ins.push({ s: status(m.planVar, m.actVar), act: true,
        t: worst
          ? T("hh.ins.var_over_cat", "Variable Kosten $d über Plan, am meisten bei $c.", "Variable costs $d over plan, most in $c.", { d: eur(varDiff), c: CAT_LABELS[worst.key] || worst.key })
          : T("hh.ins.var_over", "Variable Kosten liegen $d über Plan.", "Variable costs are $d over plan.", { d: eur(varDiff) }) });
    } else {
      ins.push({ s: "ok", act: false, t: T("hh.ins.var_ok", "Variable Kosten im Rahmen.", "Variable costs within range.") });
    }
    const wo = m.owners.filter((o) => o.act != null).map((o) => ({ o, d: o.act - o.plan }))
      .filter((x) => status(x.o.plan, x.o.act) === "over").sort((a, b) => b.d - a.d)[0];
    if (wo) {
      ins.push({ s: "over", act: true, t: T("hh.ins.owner_over", "$n liegt $d über dem eigenen Plan.", "$n is $d over their own plan.", { n: ownerName(wo.o), d: eur(wo.d) }) });
    }
    const insHtml = ins.map((i) => `<div class="ins st-${i.s}"><i></i><span>${escHtml(i.t)}</span>
<span class="need">${i.act ? T("hh.ins.act", "hier ansehen", "take a look") : T("hh.ins.none", "kein Handlungsbedarf", "no action needed")}</span></div>`).join("");

    return `<div class="card st-${st}">
<div class="h">${title}<span class="sub">${T("hh.plan.month", "Haushaltsplan", "Household plan")}</span></div>
<div class="hero"><div><div class="big">${eur(m.actTotal)}</div>
<div class="cap">${T("hh.verdict.of", "ausgegeben, geplant $p", "spent, planned $p", { p: eur(m.planTotal) })} · ${escHtml(verdict)}</div></div>
<span class="chip">${stLabel(st)}</span></div>
<div class="meter" role="img" aria-label="${title}"><i style="width:${Math.min(100, m.actTotal / max * 100)}%"></i><b style="left:${m.planTotal / max * 100}%"></b></div>
<div class="scale"><span>${T("hh.actual.word", "Ist", "Actual")}</span><span>${T("hh.plan.word", "Plan", "Plan")} ${eur(m.planTotal)}</span></div>
<div class="tiles">${tile(T("hh.fixed", "Fix", "Fixed"), m.planFixed, m.actFixed)}${tile(T("hh.variable", "Variabel", "Variable"), m.planVar, m.actVar)}</div>
</div>
<div class="card"><div class="h">${T("hh.means", "Was das heißt", "What it means")}</div>${insHtml}</div>`;
  }

  /** Ours / each person: plan against actual. */
  _renderOwners(m, escHtml) {
    const { eur } = window._fd;
    const rows = m.owners.map((o) => {
      const has = o.act != null && m.hasActual;
      const s = has ? status(o.plan, o.act) : "ok";
      const name = o.key === OWNER_SHARED ? T("hh.ours.title", "Gemeinsam", "Ours") : o.key;
      const lab = s === "ok" ? T("hh.status.ok", "passt", "fine") : s === "near" ? T("hh.status.near", "knapp", "tight") : T("hh.status.over", "drüber", "over");
      return `<div class="orow st-${s}" style="--oc:${o.color}"><i></i>
<span><b>${escHtml(name)}</b><small class="muted">${T("hh.plan.word", "Plan", "Plan")} ${eur(o.plan)}${has ? "" : ""}</small></span>
<div>${has ? `<em>${eur(o.act)}</em><span class="chip">${lab}</span>` : `<em>${eur(o.plan)}</em>`}</div></div>`;
    }).join("");
    return `<div class="card"><div class="h">${T("hh.owners.title", "Wer trägt was", "Who carries what")}
<span class="sub">${T("hh.owners.sub", "Fixkosten gemeinsam, eigene je Person", "Shared fixed costs, own costs per person")}</span></div>${rows}</div>`;
  }

  /** Categories: plan marker against the actual bar; fixed/variable tag. */
  _renderCategories(m, escHtml) {
    const { eur, CAT_LABELS } = window._fd;
    if (!m.cats.length) return "";
    const items = m.cats.map((c, i) => {
      const s = m.hasActual ? status(c.plan, c.act) : "ok";
      const kind = c.planFix > 0 && c.planVar > 0 ? "" : c.planVar > 0
        ? `<span class="tag">${T("hh.variable", "Variabel", "Variable")}</span>`
        : `<span class="tag fix">${T("hh.fixed", "Fix", "Fixed")}</span>`;
      const max = Math.max(c.plan, c.act, 1) * 1.08;
      const nums = m.hasActual
        ? `<strong>${eur(c.act)}</strong> / ${eur(c.plan)}`
        : `${eur(c.plan)}`;
      return `<div class="cat st-${s}${i >= 5 ? " extra" : ""}">
<div class="top"><b>${escHtml(CAT_LABELS[c.key] || c.key)}${kind}</b><span class="nums">${nums}</span></div>
<div class="cmp"><i style="width:${Math.min(100, (m.hasActual ? c.act : c.plan) / max * 100)}%"></i><b style="left:${c.plan / max * 100}%"></b></div></div>`;
    }).join("");
    return `<div class="card"><div class="h">${T("hh.cats.title", "Nach Kategorie", "By category")}
<span class="sub">${m.hasActual ? T("hh.cats.sub", "Ist / Plan, Strich = Plan", "Actual / plan, line = plan") : T("hh.plan.word", "Plan", "Plan")}</span></div>${items}</div>`;
  }

  /** Shared fixed costs: visible to everybody, also on the phone. */
  _renderSharedList(plan, escHtml) {
    const { eur } = window._fd;
    const items = (plan.positions || []).filter((p) => p.owner === OWNER_SHARED && p.is_active);
    if (!items.length) return "";
    const rows = items.map((p) => `<div class="prow"><span>${escHtml(p.name)}<span class="tag${p.kind === "buffer" ? "" : " fix"}">${p.kind === "buffer" ? T("hh.variable", "Variabel", "Variable") : T("hh.fixed", "Fix", "Fixed")}</span></span><span>${eur(p.effective_amount)}</span></div>`).join("");
    return `<div class="card mob"><div class="h">${T("hh.shared.title", "Gemeinsame Fixkosten", "Shared fixed costs")}
<span class="sub">${eur(plan.costs ? plan.costs.shared : 0)}</span></div>${rows}</div>`;
  }

  _renderPockets(plan, escHtml) {
    const { eur } = window._fd;
    const split = plan.split || {};
    const members = split.members || [];
    if (!members.length) return "";
    const cards = members.map((mm, i) => `
<div class="pocket"><div class="who"><span class="dot" style="background:${PERSON_COLORS[i % PERSON_COLORS.length]}"></span>${escHtml(mm.person)}</div>
<div class="amt">${eur(mm.spielgeld)}</div>
<div class="brk">${T("hh.pocket.share", "Anteil am Rest", "Share of remainder")} ${eur(mm.remainder_share)}<br>− ${T("hh.pocket.own", "eigene Fixkosten", "own fixed costs")} ${eur(mm.individual_costs)}</div></div>`).join("");
    return `<div class="card dcard"><div class="h"><span>${T("hh.pocket.title", "Taschengeld laut Plan", "Pocket money by plan")} <span class="dtag">${T("hh.desktop", "Nur am Desktop", "Desktop only")}</span></span>
<span class="sub">${eur(split.spielgeld_total)} · ${T("hh.pocket.model", "Modell", "Model")} ${escHtml(split.model || "")}</span></div><div class="pockets">${cards}</div></div>`;
  }

  _renderIncome(plan, escHtml) {
    const { eur } = window._fd;
    const pct = (v) => `${(v || 0).toFixed(1)} %`;
    const rows = (plan.income || []).map((e) => `
<tr><td>${escHtml(e.person)}</td><td>${eur(e.deposit)}</td><td>${eur(e.insurance_mandatory)}</td><td>${eur(e.tax_adjustment)}</td><td><strong>${eur(e.net)}</strong></td><td class="muted">${pct(e.share)}</td></tr>`).join("");
    return `<div class="card dcard"><div class="h"><span>${T("hh.income.title", "Einkommen", "Income")} <span class="dtag">${T("hh.desktop", "Nur am Desktop", "Desktop only")}</span></span>
<span class="sub">${eur(plan.income_net_total)} ${T("hh.income.net_total", "netto gesamt", "net in total")}</span></div>
<div class="scroll"><table><thead><tr><th>${T("hh.income.person", "Person", "Person")}</th><th>${T("hh.income.deposit", "Eingang", "Deposit")}</th><th>${T("hh.income.insurance", "Privat-KV", "Private insurance")}</th><th>${T("hh.income.tax", "Steuerausgleich", "Tax adjustment")}</th><th>${T("hh.income.net", "Netto", "Net")}</th><th>${T("hh.income.share", "Anteil", "Share")}</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }

  _renderLedger(plan, escHtml) {
    const { eur } = window._fd;
    const positions = plan.positions || [];
    if (!positions.length) return "";
    const costs = plan.costs || {};
    const groups = new Map();
    for (const p of positions) {
      if (!groups.has(p.owner)) groups.set(p.owner, []);
      groups.get(p.owner).push(p);
    }
    const personIdx = (o) => (plan.persons || []).indexOf(o);
    const label = (o) => (o === OWNER_SHARED ? T("hh.ours.title", "Gemeinsam", "Ours") : o);
    const total = (o) => (o === OWNER_SHARED ? costs.shared : (costs.individual || {})[o]);
    const colorOf = (o) => (o === OWNER_SHARED ? "var(--fd-household)" : PERSON_COLORS[Math.max(0, personIdx(o)) % PERSON_COLORS.length]);

    return [...groups.entries()]
      .sort((a, b) => (a[0] === OWNER_SHARED ? -1 : b[0] === OWNER_SHARED ? 1 : 0))
      .map(([owner, items]) => {
        const rows = items.map((p) => {
          const tags = [`<span class="tag${p.kind === "buffer" ? "" : " fix"}">${p.kind === "buffer" ? T("hh.variable", "Variabel", "Variable") : T("hh.fixed", "Fix", "Fixed")}</span>`];
          if (p.kind === "buffer") {
            tags.push(`<span class="tag">${T("hh.buffer", "Puffer", "Buffer")} ${p.buffer_units || "?"} × ${eur(p.buffer_unit_price)}</span>`);
          }
          if (p.valid_until) tags.push(`<span class="tag">${T("hh.until", "bis", "until")} ${escHtml(p.valid_until)}</span>`);
          if (!p.is_active) tags.push(`<span class="tag">${T("hh.inactive", "inaktiv", "inactive")}</span>`);
          return `<tr><td>${escHtml(p.name)}${tags.join("")}</td><td class="muted">${escHtml(p.category || "")}</td><td>${eur(p.effective_amount)}</td></tr>`;
        }).join("");
        return `<div class="card dcard"><div class="h"><span><span class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:${colorOf(owner)}"></span>${T("hh.ledger.title", "Kosten", "Costs")} — ${escHtml(label(owner))} <span class="dtag">${T("hh.desktop", "Nur am Desktop", "Desktop only")}</span></span>
<span class="sub">${eur(total(owner))}</span></div>
<div class="scroll"><table><thead><tr><th>${T("hh.ledger.position", "Position", "Position")}</th><th>${T("hh.ledger.category", "Kategorie", "Category")}</th><th>${T("hh.ledger.amount", "Betrag", "Amount")}</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
      }).join("");
  }

  _renderTransfer(escHtml) {
    const { eur } = window._fd;
    const tp = this._transfer;
    if (!tp || !tp.accounts || !tp.accounts.length) return "";
    const accounts = tp.accounts;
    const head = accounts
      .map((a) => `<th>${escHtml(a.label)}${a.role === "pass_through" ? `<span class="tag">${T("hh.transfer.pass", "Durchlauf", "Pass-through")}</span>` : ""}</th>`)
      .join("");
    const rows = (tp.rows || []).map((r) => {
      const cells = accounts.map((a) => {
        const v = r.amounts[a.id];
        if (v === undefined) return `<td class="muted">–</td>`;
        return `<td${v === 0 ? ' class="muted"' : ""}>${eur(v)}</td>`;
      }).join("");
      return `<tr class="${r.kind === "subtotal" ? "sub" : ""}"><td>${escHtml(r.label)}</td>${cells}</tr>`;
    }).join("");

    const unplaced = tp.unplaced || [];
    const imbalances = Object.values(tp.imbalances || {});
    let badge;
    if (tp.balanced) {
      badge = `<span class="badge ok">${T("hh.transfer.balanced", "Durchlaufkonto geht auf 0 auf", "Pass-through account nets to 0")}</span>`;
    } else if (unplaced.length) {
      badge = `<span class="badge warn">${T("hh.transfer.unplaced", "Nicht zuordenbar", "Cannot be placed")}: ${unplaced.map((u) => eur(u.amount)).join(", ")}</span>`;
    } else {
      badge = `<span class="badge warn">${T("hh.transfer.off", "Plan geht nicht auf", "Plan does not balance")}: ${imbalances.map((v) => eur(v)).join(", ")}</span>`;
    }
    const unplacedNote = unplaced.length
      ? `<div class="empty">${unplaced.map((u) => escHtml(u.detail || u.reason)).join("<br>")}</div>` : "";
    const settle = Object.entries(tp.settlements || {})
      .filter(([, s]) => Math.abs(s.settlement_delta) > 0.5)
      .map(([person, s]) => `${escHtml(person)}: ${s.settlement_delta > 0 ? T("hh.transfer.advance", "streckt vor", "advances") : T("hh.transfer.carried", "wird getragen", "is carried")} ${eur(Math.abs(s.settlement_delta))}`)
      .join(" · ");

    return `<div class="card dcard"><div class="h"><span>${T("hh.transfer.title", "Monatliche Umbuchungen", "Monthly transfers")} <span class="dtag">${T("hh.desktop", "Nur am Desktop", "Desktop only")}</span></span>${badge}</div>
<div class="scroll"><table><thead><tr><th>${T("hh.transfer.step", "Schritt", "Step")}</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
${unplacedNote}${settle ? `<div class="empty">${settle}</div>` : ""}</div>`;
  }
}

window._fd.defineOnce("fd-budget-plan", FdBudgetPlan);
