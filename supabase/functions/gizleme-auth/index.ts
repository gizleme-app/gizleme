// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
import { createClient } from "jsr:@supabase/supabase-js@2";

const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
const CONF = "gizleme_config";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (o: unknown, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { ...cors, "Content-Type": "application/json" } });
function b64(bytes: ArrayBuffer | Uint8Array){ return btoa(String.fromCharCode(...new Uint8Array(bytes))); }
function unb64(s: string){ return Uint8Array.from(atob(s), c => c.charCodeAt(0)); }
async function sha256b64(bytes: Uint8Array){ return b64(await crypto.subtle.digest("SHA-256", bytes)); }
const USERRE = /^[a-z0-9_.]{3,20}$/;
function normU(u: unknown){ return (u ?? "").toString().trim().toLowerCase(); }
const YEAR = 365 * 24 * 3600 * 1000;
async function newToken(){ const t = b64(crypto.getRandomValues(new Uint8Array(32))); const th = await sha256b64(unb64(t)); return { t, th }; }

// ---- abuse controls ----
function ipOf(req: Request) {
  const h = req.headers;
  return h.get("cf-connecting-ip") || h.get("x-real-ip") || (h.get("x-forwarded-for") || "").split(",")[0].trim() || "";
}
async function rl(key: string, limit: number, windowS: number) {
  try { const { data, error } = await db.rpc("gz_rl_hit", { p_key: key, p_limit: limit, p_window_s: windowS }); if (error) return true; return data !== false; }
  catch { return true; }
}
// A server-side secret (generated once, kept in gizleme_config) lets us answer "salt" for unknown
// usernames with a stable, plausible value, so the salt endpoint no longer reveals which names exist.
let secretCache: string | null = null;
async function authSecret() {
  if (secretCache) return secretCache;
  const { data } = await db.from(CONF).select("value").eq("key", "authsecret").maybeSingle();
  if (data?.value?.k) { secretCache = data.value.k; return secretCache!; }
  const k = b64(crypto.getRandomValues(new Uint8Array(32)));
  await db.from(CONF).upsert({ key: "authsecret", value: { k }, updated_at: new Date().toISOString() }, { onConflict: "key" });
  secretCache = k; return k;
}
async function fakeSalt(u: string) {
  const key = await crypto.subtle.importKey("raw", unb64(await authSecret()), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode("salt|" + u)));
  return b64(mac.slice(0, 16));   // same shape as a real 16-byte salt
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method === "GET") return json({ ok: true, service: "gizleme-auth" });
  let body: any; try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }
  const action = body?.action;
  const ip = ipOf(req);
  try {
    if (action === "check") {
      if (ip && !(await rl("auth:chk:" + ip, 60, 60))) return json({ error: "rate_limited" }, 429);
      const u = normU(body.username);
      if (!USERRE.test(u)) return json({ ok: true, available: false, reason: "format" });
      const { data } = await db.from("gizleme_accounts").select("username_lc").eq("username_lc", u).maybeSingle();
      return json({ ok: true, available: !data });
    }
    if (action === "register") {
      if (ip && !(await rl("auth:reg:" + ip, 10, 3600))) return json({ error: "rate_limited" }, 429);
      const u = normU(body.username);
      const display = (body.display || body.username || "").toString().slice(0, 24);
      const salt = (body.salt || "").toString().slice(0, 64);
      const verifier = (body.verifier || "").toString().slice(0, 128);
      if (!USERRE.test(u)) return json({ error: "invalid_username" }, 400);
      if (!salt || !verifier) return json({ error: "missing_fields" }, 400);
      const ins = await db.from("gizleme_accounts").insert({ username_lc: u, display, salt, verifier });
      if (ins.error) { if ((ins.error.code || "") === "23505" || /duplicate/i.test(ins.error.message)) return json({ error: "taken" }, 409); return json({ error: ins.error.message }, 500); }
      const { t, th } = await newToken();
      await db.from("gizleme_sessions").insert({ token_hash: th, username_lc: u, expires_at: new Date(Date.now() + YEAR).toISOString() });
      return json({ ok: true, token: t, username: u, display });
    }
    if (action === "salt") {
      if (ip && !(await rl("auth:salt:" + ip, 60, 60))) return json({ error: "rate_limited" }, 429);
      const u = normU(body.username);
      if (!USERRE.test(u)) return json({ ok: true, salt: await fakeSalt(u) });
      const { data } = await db.from("gizleme_accounts").select("salt").eq("username_lc", u).maybeSingle();
      return json({ ok: true, salt: data ? data.salt : await fakeSalt(u) });
    }
    if (action === "login") {
      const u = normU(body.username);
      const av = (body.av || "").toString();
      if (!u || !av) return json({ error: "missing" }, 400);
      // per-IP budget on every attempt; per-account budget on FAILED attempts only (10 / 15 min), so a stranger
      // hammering a username with junk cannot lock its owner out — the owner's correct password still works
      if (ip && !(await rl("auth:loginip:" + ip, 60, 900))) return json({ error: "rate_limited" }, 429);
      if (!(await rl("auth:loginfail:" + u, 10, 900))) return json({ error: "rate_limited" }, 429);   // peek: still counts one
      const { data } = await db.from("gizleme_accounts").select("verifier, display").eq("username_lc", u).maybeSingle();
      if (!data) return json({ error: "bad_login" }, 401);
      const calc = await sha256b64(unb64(av));
      if (calc !== data.verifier) return json({ error: "bad_login" }, 401);
      try { await db.rpc("gz_rl_undo", { p_key: "auth:loginfail:" + u }); } catch { /* best effort: a success gives the budget back */ }
      const { t, th } = await newToken();
      await db.from("gizleme_sessions").insert({ token_hash: th, username_lc: u, expires_at: new Date(Date.now() + YEAR).toISOString() });
      return json({ ok: true, token: t, username: u, display: data.display });
    }
    if (action === "changepw" || action === "delete") {
      // Both need the current session AND the current password (av): a stolen session token alone can't do them.
      const token = (body.token || "").toString(); const av = (body.av || "").toString();
      if (!token || !av) return json({ error: "missing" }, 400);
      const th = await sha256b64(unb64(token));
      const { data: sess } = await db.from("gizleme_sessions").select("username_lc, expires_at").eq("token_hash", th).maybeSingle();
      if (!sess || new Date(sess.expires_at).getTime() < Date.now()) return json({ error: "unauthorized" }, 401);
      const u = sess.username_lc as string;
      if (!(await rl("auth:sensitive:" + u, 10, 900))) return json({ error: "rate_limited" }, 429);
      const { data: acc } = await db.from("gizleme_accounts").select("verifier").eq("username_lc", u).maybeSingle();
      if (!acc || (await sha256b64(unb64(av))) !== acc.verifier) return json({ error: "bad_login" }, 401);
      if (action === "changepw") {
        const salt = (body.salt || "").toString().slice(0, 64); const verifier = (body.verifier || "").toString().slice(0, 128);
        if (!salt || !verifier) return json({ error: "missing_fields" }, 400);
        const up = await db.from("gizleme_accounts").update({ salt, verifier }).eq("username_lc", u);
        if (up.error) return json({ error: up.error.message }, 500);
        await db.from("gizleme_sessions").delete().eq("username_lc", u).neq("token_hash", th);   // every other device must log in again
        return json({ ok: true });
      }
      // delete: the account and everything the server holds for it
      const owners: string[] = Array.isArray(body.owners) ? body.owners.map((o: unknown) => (o ?? "").toString().slice(0, 64)).filter(Boolean).slice(0, 50) : [];
      const acct = body.acct ? (body.acct as string).toString().slice(0, 64) : "";
      if (acct) await db.from("gizleme_push_subs").delete().eq("acct", acct);
      if (owners.length) await db.from("gizleme_push_subs").delete().in("owner", owners);
      await db.from("gizleme_vault").delete().eq("username_lc", u);
      await db.from("gizleme_sessions").delete().eq("username_lc", u);
      const del = await db.from("gizleme_accounts").delete().eq("username_lc", u);
      if (del.error) return json({ error: del.error.message }, 500);
      return json({ ok: true });
    }
    if (action === "rename") {
      // Display name (what friends see): free text up to 24 chars; needs a valid session.
      const token = (body.token || "").toString(); const display = (body.display || "").toString().trim().slice(0, 24);
      if (!token || !display) return json({ error: "missing" }, 400);
      const th = await sha256b64(unb64(token));
      const { data: sess } = await db.from("gizleme_sessions").select("username_lc, expires_at").eq("token_hash", th).maybeSingle();
      if (!sess || new Date(sess.expires_at).getTime() < Date.now()) return json({ error: "unauthorized" }, 401);
      if (!(await rl("auth:rename:" + sess.username_lc, 20, 3600))) return json({ error: "rate_limited" }, 429);
      const up = await db.from("gizleme_accounts").update({ display }).eq("username_lc", sess.username_lc);
      if (up.error) return json({ error: up.error.message }, 500);
      return json({ ok: true, display });
    }
    if (action === "validate") {
      const token = (body.token || "").toString(); if (!token) return json({ error: "missing" }, 400);
      const th = await sha256b64(unb64(token));
      const { data } = await db.from("gizleme_sessions").select("username_lc, expires_at").eq("token_hash", th).maybeSingle();
      if (!data) return json({ ok: true, valid: false });
      if (new Date(data.expires_at).getTime() < Date.now()) { await db.from("gizleme_sessions").delete().eq("token_hash", th); return json({ ok: true, valid: false }); }
      const acc = await db.from("gizleme_accounts").select("display").eq("username_lc", data.username_lc).maybeSingle();
      return json({ ok: true, valid: true, username: data.username_lc, display: acc.data?.display || data.username_lc });
    }
    if (action === "logout") {
      const token = (body.token || "").toString();
      if (token) { const th = await sha256b64(unb64(token)); await db.from("gizleme_sessions").delete().eq("token_hash", th); }
      return json({ ok: true });
    }
    return json({ error: "unknown_action" }, 400);
  } catch (e: any) { return json({ error: String(e?.message || e) }, 500); }
});
