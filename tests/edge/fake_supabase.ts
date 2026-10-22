// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// deno-lint-ignore-file no-explicit-any
// A stand-in for supabase-js, enough for what the five Edge Functions do: an in-memory table store behind the
// query chains they use (from().select().eq().maybeSingle(), insert / upsert / update / delete with filters,
// order, limit, in, is, not), rpc() with the three Postgres functions, and a storage bucket. The import map
// in this folder points "jsr:@supabase/supabase-js@2" here, so each function's index.ts runs unchanged.

export type Row = Record<string, any>;
export interface Store {
  tables: Record<string, Row[]>;
  unique: Record<string, string[][]>;            // table -> unique key sets (what Postgres would refuse twice)
  rl: Record<string, { n: number; ws: number }>;  // gz_rl_hit counters
  rpc: Record<string, (args: any) => any>;        // overrides for a test
  fail: Record<string, { message: string; code?: string } | null>;   // table -> error returned by the next operation
  storage: Record<string, { bytes: Uint8Array; created_at: string }>;
  log: { table: string; op: string; filters: any[]; payload?: any }[];
}
export const store: Store = {
  tables: {}, rl: {}, rpc: {}, fail: {}, storage: {}, log: [],
  unique: {
    gizleme_accounts: [["username_lc"]], gizleme_sessions: [["token_hash"]], gizleme_vault: [["username_lc"]],
    gizleme_mbox: [["mbox", "mid"]], gizleme_push_subs: [["notify_key", "owner"]], gizleme_config: [["key"]], gizleme_rl: [["k"]],
  },
};
export function reset() { store.tables = {}; store.rl = {}; store.rpc = {}; store.fail = {}; store.storage = {}; store.log = []; }
export function table(name: string): Row[] { return (store.tables[name] ||= []); }
export function seed(name: string, rows: Row[]) { table(name).push(...rows.map(r => ({ ...r }))); }

function dup(t: string, row: Row, except?: Row) {
  for (const keys of store.unique[t] || []) {
    if (table(t).some(r => r !== except && keys.every(k => r[k] === row[k]))) return keys;
  }
  return null;
}
function match(row: Row, f: any): boolean {
  const v = row[f.col];
  switch (f.op) {
    case "eq": return v === f.val;
    case "neq": return v !== f.val;
    case "gt": return v > f.val;
    case "lt": return v < f.val;
    case "in": return (f.val as any[]).includes(v);
    case "is": return f.val === null ? (v === null || v === undefined) : v === f.val;
    case "notin": return !(f.val as any[]).includes(v);
    default: return true;
  }
}
function project(row: Row, cols: string | null) {
  if (!cols || cols === "*") return { ...row };
  const out: Row = {}; for (const c of cols.split(",").map(s => s.trim()).filter(Boolean)) out[c] = row[c]; return out;
}

class Query implements PromiseLike<any> {
  op = "select"; cols: string | null = null; payload: any = null; opts: any = {}; filters: any[] = [];
  ord: { col: string; asc: boolean } | null = null; lim = Infinity; single = false; returning: string | null = null;
  constructor(public t: string) {}
  select(cols = "*") { if (this.op === "select") this.cols = cols; else this.returning = cols; return this; }
  insert(rows: any, opts: any = {}) { this.op = "insert"; this.payload = rows; this.opts = opts; return this; }
  upsert(rows: any, opts: any = {}) { this.op = "upsert"; this.payload = rows; this.opts = opts; return this; }
  update(vals: any) { this.op = "update"; this.payload = vals; return this; }
  delete() { this.op = "delete"; return this; }
  eq(col: string, val: any) { this.filters.push({ op: "eq", col, val }); return this; }
  neq(col: string, val: any) { this.filters.push({ op: "neq", col, val }); return this; }
  gt(col: string, val: any) { this.filters.push({ op: "gt", col, val }); return this; }
  lt(col: string, val: any) { this.filters.push({ op: "lt", col, val }); return this; }
  in(col: string, val: any[]) { this.filters.push({ op: "in", col, val }); return this; }
  is(col: string, val: any) { this.filters.push({ op: "is", col, val }); return this; }
  not(col: string, op: string, val: any) {   // only the form the functions use: .not(col, "in", "(a,b,c)")
    if (op !== "in") throw new Error("fake: not(" + op + ") unsupported");
    const list = String(val).replace(/^\(|\)$/g, "").split(",").map(s => s.trim()).filter(Boolean);
    this.filters.push({ op: "notin", col, val: list }); return this;
  }
  order(col: string, o: any = {}) { this.ord = { col, asc: o.ascending !== false }; return this; }
  limit(n: number) { this.lim = n; return this; }
  maybeSingle() { this.single = true; return this; }
  then<R1 = any, R2 = never>(ok?: (v: any) => R1 | PromiseLike<R1>, ko?: (e: any) => R2 | PromiseLike<R2>) { return Promise.resolve().then(() => this.run()).then(ok, ko); }
  run(): { data: any; error: any } {
    store.log.push({ table: this.t, op: this.op, filters: this.filters, payload: this.payload });
    const f = store.fail[this.t]; if (f) { store.fail[this.t] = null; return { data: null, error: f }; }
    const rows = table(this.t);
    const hit = () => rows.filter(r => this.filters.every(x => match(r, x)));
    if (this.op === "select") {
      let out = hit();
      if (this.ord) { const { col, asc } = this.ord; out = [...out].sort((a, b) => (a[col] < b[col] ? -1 : a[col] > b[col] ? 1 : 0) * (asc ? 1 : -1)); }
      if (this.lim < out.length) out = out.slice(0, this.lim);
      const data = out.map(r => project(r, this.cols));
      return { data: this.single ? (data[0] ?? null) : data, error: null };
    }
    if (this.op === "insert" || this.op === "upsert") {
      const list: Row[] = Array.isArray(this.payload) ? this.payload : [this.payload];
      const written: Row[] = [];
      for (const row of list) {
        const keys = dup(this.t, row);
        if (keys) {
          if (this.op === "insert") return { data: null, error: { code: "23505", message: 'duplicate key value violates unique constraint "' + this.t + "_" + keys.join("_") + '_key"' } };
          if (this.opts.ignoreDuplicates) continue;
          const i = rows.findIndex(r => keys.every(k => r[k] === row[k])); rows[i] = { ...rows[i], ...row }; written.push(rows[i]); continue;
        }
        const r = { ...row }; rows.push(r); written.push(r);
      }
      return { data: this.returning ? written.map(r => project(r, this.returning)) : null, error: null };
    }
    if (this.op === "update") {
      const out: Row[] = [];
      for (const r of hit()) { const n = { ...r, ...this.payload }; const keys = dup(this.t, n, r); if (keys) return { data: null, error: { code: "23505", message: "duplicate key" } }; Object.assign(r, this.payload); out.push(r); }
      return { data: this.returning ? out.map(r => project(r, this.returning)) : null, error: null };
    }
    if (this.op === "delete") {
      const gone = hit(); store.tables[this.t] = rows.filter(r => !gone.includes(r));
      return { data: this.returning ? gone.map(r => project(r, this.returning)) : null, error: null };
    }
    return { data: null, error: { message: "fake: unknown op" } };
  }
}

function rpc(name: string, args: any) {
  if (store.rpc[name]) { try { return Promise.resolve({ data: store.rpc[name](args), error: null }); } catch (e: any) { return Promise.resolve({ data: null, error: { message: String(e?.message || e) } }); } }
  if (name === "gz_rl_hit") {   // fixed window: true while under the limit (the first `limit` hits pass), false after
    const now = Date.now(); const c = store.rl[args.p_key];
    if (!c || now - c.ws > args.p_window_s * 1000) { store.rl[args.p_key] = { n: 1, ws: now }; return Promise.resolve({ data: true, error: null }); }
    c.n++; return Promise.resolve({ data: c.n <= args.p_limit, error: null });
  }
  if (name === "gz_rl_undo") { const c = store.rl[args.p_key]; if (c && c.n > 0) c.n--; return Promise.resolve({ data: null, error: null }); }
  if (name === "gz_change_password") {
    const acc = table("gizleme_accounts").find(r => r.username_lc === args.p_user); if (!acc) return Promise.resolve({ data: false, error: null });
    acc.salt = args.p_salt; acc.verifier = args.p_verifier;
    if (args.p_abk) { const v = table("gizleme_vault").find(r => r.username_lc === args.p_user); if (v) v.abk = args.p_abk; else table("gizleme_vault").push({ username_lc: args.p_user, abk: args.p_abk, contacts: null, cver: 0 }); }
    return Promise.resolve({ data: true, error: null });
  }
  return Promise.resolve({ data: null, error: { message: "fake: no rpc " + name } });
}

const storage = {
  from(_bucket: string) {
    return {
      upload(path: string, bytes: Uint8Array, _opts: any) {
        if (store.storage[path]) return Promise.resolve({ data: null, error: { message: "The resource already exists" } });
        store.storage[path] = { bytes, created_at: new Date().toISOString() }; return Promise.resolve({ data: { path }, error: null });
      },
      remove(paths: string[]) { for (const p of paths) delete store.storage[p]; return Promise.resolve({ data: paths.map(name => ({ name })), error: null }); },
      list(prefix: string, _opts: any) {
        const out: any[] = []; const seen = new Set<string>();
        for (const [p, v] of Object.entries(store.storage)) {
          if (prefix && !p.startsWith(prefix + "/")) continue;
          const rest = prefix ? p.slice(prefix.length + 1) : p;
          const i = rest.indexOf("/");
          if (i >= 0) { const folder = rest.slice(0, i); if (!seen.has(folder)) { seen.add(folder); out.push({ name: folder, id: null }); } }
          else out.push({ name: rest, id: p, created_at: v.created_at });
        }
        return Promise.resolve({ data: out, error: null });
      },
    };
  },
};

export function createClient(_url: string, _key: string, _opts?: any) {
  return { from: (t: string) => new Query(t), rpc, storage };
}
