/**
 * fd-contract-filter — pure filter logic of the contracts tab (#118).
 *
 * JavaScript twin of contract_filter.py (validate_spec / apply / totals). The
 * cases in tests/fixtures/contract_filter_cases.json run against both. A plain
 * script (no import/export) so the kit can load it with import() and a test
 * can run it in a bare vm context; it publishes window._fd.contractFilter.
 */
(function () {
  const KINDS = ["contract", "subscription", "regular", "irregular"];
  const STATUSES = ["active", "overdue", "ended", "candidate"];
  const SORTS = ["deadline", "amount"];
  const AGGREGATES = ["month", "year"];
  const OWNER_TOKENS = ["me", "partner", "shared"];
  const OWNER_ALIASES = { ich: "me", wir: "shared", haushalt: "shared", household: "shared" };
  const NO_NOTICE = ["regular", "irregular"];
  const STATUS_OF_RAW = { active: "active", missing: "overdue", ended: "ended" };
  const MAX_Q = 100, MAX_ITEMS = 20, MAX_ITEM = 60, MAX_AMOUNT = 1000000;

  function defaultSpec() {
    return { q: "", kinds: [], statuses: [], categories: [], labels: [], owners: [],
      amount_min: null, amount_max: null, sort: "deadline", aggregate: null };
  }

  /** Lower case, ä ö ü ß -> ae oe ue ss, other accents dropped (same as fold() in Python). */
  function fold(text) {
    const s = String(text == null ? "" : text).toLowerCase()
      .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss");
    return s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  }

  function err(errors, field, reason, value) {
    const o = { field, reason };
    if (value != null) o.value = String(value).slice(0, MAX_ITEM);
    errors.push(o);
  }

  function number(v) {
    if (typeof v !== "number" || !Number.isFinite(v) || v < 0 || v > MAX_AMOUNT) return null;
    return v;
  }

  function items(raw, field, allowed, errors) {
    if (raw == null) return [];
    if (!Array.isArray(raw)) { err(errors, field, "not_a_list"); return []; }
    const out = [];
    for (const item of raw.slice(0, MAX_ITEMS)) {
      if (typeof item !== "string" || !item.trim() || item.length > MAX_ITEM) {
        err(errors, field, "invalid_value", typeof item === "string" ? item : null);
        continue;
      }
      let value = item.trim();
      if (allowed != null) {
        value = Array.isArray(allowed) ? (allowed.includes(value) ? value : null)
          : (Object.prototype.hasOwnProperty.call(allowed, fold(value)) ? allowed[fold(value)] : null);
        if (value == null) { err(errors, field, "unknown_value", item); continue; }
      }
      if (!out.includes(value)) out.push(value);
    }
    if (raw.length > MAX_ITEMS) err(errors, field, "too_many");
    return out;
  }

  /** {spec, errors}; valid parts kept, invalid ones dropped and reported. No vocabulary check. */
  function validateSpec(raw) {
    const spec = defaultSpec();
    const errors = [];
    if (raw == null || typeof raw !== "object" || Array.isArray(raw)) {
      err(errors, "_", "not_an_object");
      return { spec, errors };
    }
    for (const key of Object.keys(raw)) if (!(key in spec)) err(errors, key.slice(0, MAX_ITEM), "unknown_field");
    if (raw.q != null) {
      if (typeof raw.q === "string") spec.q = raw.q.split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_Q);
      else err(errors, "q", "invalid_value");
    }
    spec.kinds = items(raw.kinds, "kinds", KINDS, errors);
    spec.statuses = items(raw.statuses, "statuses", STATUSES, errors);
    spec.categories = items(raw.categories, "categories", null, errors);
    spec.labels = items(raw.labels, "labels", null, errors);
    const owners = items(raw.owners, "owners", null, errors).map((o) => OWNER_ALIASES[fold(o)] || o);
    spec.owners = owners.filter((o, i) => owners.indexOf(o) === i);
    let lo = null, hi = null;
    for (const name of ["amount_min", "amount_max"]) {
      const v = raw[name];
      if (v == null) continue;
      const n = number(v);
      if (n == null) err(errors, name, "invalid_value", typeof v === "string" ? v : null);
      else if (name === "amount_min") lo = n; else hi = n;
    }
    if (lo != null && hi != null && lo > hi) { err(errors, "amount_max", "below_min"); hi = null; }
    spec.amount_min = lo; spec.amount_max = hi;
    if (SORTS.includes(raw.sort)) spec.sort = raw.sort;
    else if (raw.sort != null) err(errors, "sort", "invalid_value", typeof raw.sort === "string" ? raw.sort : null);
    if (AGGREGATES.includes(raw.aggregate)) spec.aggregate = raw.aggregate;
    else if (raw.aggregate != null) err(errors, "aggregate", "invalid_value", typeof raw.aggregate === "string" ? raw.aggregate : null);
    return { spec, errors };
  }

  function isDefault(spec) {
    const base = defaultSpec();
    return Object.keys(base).filter((k) => k !== "sort" && k !== "aggregate")
      .every((k) => JSON.stringify(spec[k]) === JSON.stringify(base[k]));
  }

  function statusOf(c) {
    const raw = STATUS_OF_RAW[String(c.status || "active")] || "active";
    return c.candidate && raw !== "ended" ? "candidate" : raw;
  }
  const kindOf = (c) => c.kind || "contract";
  const monthly = (c) => Math.abs(Number(c.monthly_equivalent || 0));
  const nameOf = (c) => fold(c.display_name || c.creditor);
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const round2 = (x) => Number(x.toFixed(2));

  function haystack(c) {
    const parts = [c.display_name, c.creditor, c.display_name_detected];
    if (Array.isArray(c.remittance)) parts.push(...c.remittance);
    return fold(parts.filter(Boolean).join(" "));
  }

  function ownerSet(owners, me, persons) {
    const out = new Set();
    for (const o of owners) {
      if (o === "me") { if (me) out.add(me); }
      else if (o === "partner") { for (const p of persons || []) if (p && p !== me && p !== "shared") out.add(p); }
      else out.add(o);
    }
    return out;
  }

  function totals(list, explicitStatus) {
    const out = { fixed: { monthly: 0, yearly: 0, count: 0 }, regular: { monthly: 0, yearly: 0, count: 0 } };
    for (const c of list) {
      if (!explicitStatus && statusOf(c) === "ended") continue;
      const g = out[NO_NOTICE.includes(kindOf(c)) ? "regular" : "fixed"];
      const y = c.annual_total != null ? c.annual_total : c.annual_cost;
      g.yearly = round2(g.yearly + Number(y || 0));
      g.count += 1;
    }
    for (const g of Object.values(out)) g.monthly = round2(g.yearly / 12);
    out.yearly = round2(out.fixed.yearly + out.regular.yearly);
    out.monthly = round2(out.yearly / 12);
    out.count = out.fixed.count + out.regular.count;
    return out;
  }

  /** {items, totals} for a validated spec; ctx = {me, persons}. */
  function apply(contracts, spec, ctx) {
    const { me = null, persons = [] } = ctx || {};
    const words = fold(spec.q).split(/\s+/).filter(Boolean);
    const wanted = new Set(spec.statuses.length ? spec.statuses : ["active", "overdue", "ended"]);
    const owners = spec.owners.length ? ownerSet(spec.owners, me, persons) : null;
    const lo = spec.amount_min, hi = spec.amount_max;
    const shown = contracts.filter((c) => {
      if (!wanted.has(statusOf(c))) return false;
      if (spec.kinds.length && !spec.kinds.includes(kindOf(c))) return false;
      if (spec.categories.length && !spec.categories.includes(c.category)) return false;
      if (spec.labels.length && !(c.labels || []).some((l) => spec.labels.includes(l))) return false;
      if (owners && !owners.has(c.owner)) return false;
      const m = monthly(c);
      if ((lo != null && m < lo) || (hi != null && m > hi)) return false;
      if (words.length) {
        const hay = haystack(c);
        if (!words.every((w) => hay.includes(w))) return false;
      }
      return true;
    });
    const ended = (c) => (statusOf(c) === "ended" ? 1 : 0);
    if (spec.sort === "amount") {
      shown.sort((a, b) => cmp(ended(a), ended(b)) || cmp(monthly(b), monthly(a)) || cmp(nameOf(a), nameOf(b)) || cmp(String(a.id), String(b.id)));
    } else {
      shown.sort((a, b) => cmp(ended(a), ended(b)) || cmp(a.next_deadline == null, b.next_deadline == null)
        || cmp(String(a.next_deadline || ""), String(b.next_deadline || "")) || cmp(nameOf(a), nameOf(b)) || cmp(String(a.id), String(b.id)));
    }
    return { items: shown, totals: totals(shown, spec.statuses.length > 0) };
  }

  const api = { KINDS, STATUSES, SORTS, defaultSpec, fold, validateSpec, isDefault, statusOf, apply, totals };
  if (typeof window !== "undefined") {
    window._fd = window._fd || {};
    window._fd.contractFilter = api;
  }
})();
