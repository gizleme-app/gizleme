// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
import { createClient } from "jsr:@supabase/supabase-js@2";

const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
const TABLE = "gizleme_vault";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (o: unknown, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { ...cors, "Content-Type": "application/json" } });
function b64(bytes: ArrayBuffer | Uint8Array){ return btoa(String.fromCharCode(...new Uint8Array(bytes))); }
function unb64(s: string){ return Uint8Array.from(atob(s), c => c.charCodeAt(0)); }
async function sha256b64(bytes: Uint8Array){ return b64(await crypto.subtle.digest("SHA-256", bytes)); }
function sizeOk(o: unknown, max = 300000){ try { return JSON.stringify(o).length <= max; } catch { return false; } }

// ---- abuse controls ----
function ipOf(req: Request) {
  const h = req.headers;
  return h.get("cf-connecting-ip") || h.get("x-real-ip") || (h.get("x-forwarded-for") || "").split(",")[0].trim() || "";
}
async function rl(key: string, limit: number, windowS: number) {
  try { const { data, error } = await db.rpc("gz_rl_hit", { p_key: key, p_limit: limit, p_window_s: windowS }); if (error) return true; return data !== false; }
  catch { return true; }
}

async function userFromToken(token: string){
  if (!token) return null;
  let th: string; try { th = await sha256b64(unb64(token)); } catch { return null; }
  const { data } = await db.from("gizleme_sessions").select("username_lc, expires_at").eq("token_hash", th).maybeSingle();
  if (!data) return null;
  if (new Date(data.expires_at).getTime() < Date.now()) { await db.from("gizleme_sessions").delete().eq("token_hash", th); return null; }
  return data.username_lc as string;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method === "GET") return json({ ok: true, service: "gizleme-vault" });
  let body: any; try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }
  const ip = ipOf(req);
  if (ip && !(await rl("vault:ip:" + ip, 240, 60))) return json({ error: "rate_limited" }, 429);
  const u = await userFromToken((body?.token || "").toString());
  if (!u) return json({ error: "unauthorized" }, 401);
  const action = body?.action;
  try {
    if (action === "pull") {
      const { data } = await db.from(TABLE).select("abk, contacts, cver").eq("username_lc", u).maybeSingle();
      return json({ ok: true, abk: data?.abk ?? null, contacts: data?.contacts ?? null, cver: data?.cver ?? 0 });
    }
    if (action === "pushAbk") {
      const abk = body.abk;
      if (!abk || typeof abk !== "object") return json({ error: "missing" }, 400);
      if (!sizeOk(abk, 4000)) return json({ error: "too_big" }, 413);
      const { data } = await db.from(TABLE).select("abk").eq("username_lc", u).maybeSingle();
      if (data && data.abk) return json({ ok: true, already: true });   // set-once
      const up = await db.from(TABLE).upsert({ username_lc: u, abk, updated_at: new Date().toISOString() }, { onConflict: "username_lc" });
      if (up.error) return json({ error: up.error.message }, 500);
      return json({ ok: true });
    }
    if (action === "rewrapAbk") {
      // After a password change: the same ABK, wrapped under the key derived from the new password.
      // Needs the (new) password's av as well, so a session token alone can't replace the wrapped key.
      const abk = body.abk; const av = (body.av || "").toString();
      if (!abk || typeof abk !== "object" || !av) return json({ error: "missing" }, 400);
      if (!sizeOk(abk, 4000)) return json({ error: "too_big" }, 413);
      const { data: acc } = await db.from("gizleme_accounts").select("verifier").eq("username_lc", u).maybeSingle();
      if (!acc || (await sha256b64(unb64(av))) !== acc.verifier) return json({ error: "bad_login" }, 401);
      const up = await db.from(TABLE).update({ abk, updated_at: new Date().toISOString() }).eq("username_lc", u);
      if (up.error) return json({ error: up.error.message }, 500);
      return json({ ok: true });
    }
    if (action === "pushContacts") {
      const contacts = body.contacts; const base = Number(body.cver) || 0;
      if (!contacts || typeof contacts !== "object") return json({ error: "missing" }, 400);
      if (!sizeOk(contacts)) return json({ error: "too_big" }, 413);
      const { data } = await db.from(TABLE).select("cver").eq("username_lc", u).maybeSingle();
      const cur = data?.cver ?? 0;
      // optimistic concurrency returned as a 200 body so the client can read the current version and retry
      if (data && base !== cur) return json({ ok: false, conflict: true, cver: cur });
      const next = cur + 1;
      const up = await db.from(TABLE).upsert({ username_lc: u, contacts, cver: next, updated_at: new Date().toISOString() }, { onConflict: "username_lc" });
      if (up.error) return json({ error: up.error.message }, 500);
      return json({ ok: true, cver: next });
    }
    return json({ error: "unknown_action" }, 400);
  } catch (e: any) { return json({ error: String(e?.message || e) }, 500); }
});
