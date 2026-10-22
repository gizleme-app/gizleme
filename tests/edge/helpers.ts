// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// deno-lint-ignore-file no-explicit-any
// Loads one Edge Function with Deno.serve captured (the file calls it at the top level) and gives a `call`.
import { reset, store } from "./fake_supabase.ts";
export { reset, store, seed, table } from "./fake_supabase.ts";
export type Handler = (req: Request) => Promise<Response> | Response;

export async function load(fn: string): Promise<Handler> {
  Deno.env.set("SUPABASE_URL", "http://fake"); Deno.env.set("SUPABASE_SERVICE_ROLE_KEY", "fake");
  let h: Handler | null = null;
  const real = (Deno as any).serve;
  (Deno as any).serve = (a: any, b?: any) => { h = typeof a === "function" ? a : b; return { finished: Promise.resolve(), shutdown() {}, ref() {}, unref() {}, addr: {} }; };
  try { await import("../../supabase/functions/" + fn + "/index.ts"); } finally { (Deno as any).serve = real; }
  if (!h) throw new Error("Deno.serve was not called by " + fn);
  reset();
  return h;
}
export async function call(h: Handler, body: unknown, opts: { ip?: string; origin?: string; method?: string } = {}) {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.ip) headers["cf-connecting-ip"] = opts.ip;
  if (opts.origin) headers["origin"] = opts.origin;
  const method = opts.method || "POST";
  const req = new Request("http://fake/fn", { method, headers, body: method === "POST" ? (typeof body === "string" ? body : JSON.stringify(body)) : undefined });
  const res = await h(req);
  let json: any = null; try { json = JSON.parse(await res.text()); } catch { /* not json */ }
  return { status: res.status, json, headers: res.headers };
}
export const b64 = (b: Uint8Array) => btoa(String.fromCharCode(...b));
export const unb64 = (s: string) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
export async function sha256b64(bytes: Uint8Array) { return b64(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes as unknown as ArrayBuffer))); }
export async function token(): Promise<{ t: string; th: string }> { const t = b64(crypto.getRandomValues(new Uint8Array(32))); return { t, th: await sha256b64(unb64(t)) }; }
export function future(days = 30) { return new Date(Date.now() + days * 86400000).toISOString(); }
export function past(days = 1) { return new Date(Date.now() - days * 86400000).toISOString(); }
/** a logged-in session for `u` in the sessions table; returns its token */
export async function session(u: string, expires = future()) { const { t, th } = await token(); (store.tables.gizleme_sessions ||= []).push({ token_hash: th, username_lc: u, expires_at: expires }); return t; }
