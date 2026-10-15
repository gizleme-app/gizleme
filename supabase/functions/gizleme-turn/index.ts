// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
import { createClient } from "jsr:@supabase/supabase-js@2";

// ICE servers for calls. STUN is always returned (public, free). TURN — needed when both phones sit behind
// strict NATs (common on mobile networks) — is added only when Cloudflare TURN credentials are configured as
// function secrets (CF_TURN_KEY_ID / CF_TURN_KEY_TOKEN): short-lived per-request credentials, nothing stored
// on the client. A TURN relay only ever forwards DTLS-SRTP ciphertext; it cannot hear or see the call.
const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
};
const json = (o: unknown, status = 200) => new Response(JSON.stringify(o), { status, headers: { ...cors, "Content-Type": "application/json" } });
function ipOf(req: Request) { const h = req.headers; return h.get("cf-connecting-ip") || h.get("x-real-ip") || (h.get("x-forwarded-for") || "").split(",")[0].trim() || ""; }
async function rl(key: string, limit: number, windowS: number) {
  try { const { data, error } = await db.rpc("gz_rl_hit", { p_key: key, p_limit: limit, p_window_s: windowS }); if (error) return true; return data !== false; } catch { return true; }
}
const STUN = [{ urls: ["stun:stun.cloudflare.com:3478", "stun:stun.l.google.com:19302"] }];
let credCache: { servers: unknown[]; exp: number } | null = null;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  const ip = ipOf(req);
  if (ip && !(await rl("turn:" + ip, 40, 600))) return json({ error: "rate_limited" }, 429);
  let id = Deno.env.get("CF_TURN_KEY_ID") || "", tok = Deno.env.get("CF_TURN_KEY_TOKEN") || "";
  if (!id || !tok) {   // same place as the VAPID keys: service-role-only config row, never in source
    try { const { data } = await db.from("gizleme_config").select("value").eq("key", "turn").maybeSingle();
      if (data?.value?.id && data?.value?.token) { id = String(data.value.id); tok = String(data.value.token); } } catch { /* fall through */ }
  }
  if (!id || !tok) return json({ ok: true, iceServers: STUN, turn: false, ttl: 600 });
  // one set of short-lived credentials is shared by all callers for ~50 min (ttl 1 h), so Cloudflare is
  // asked once per instance lifetime rather than once per call
  if (credCache && credCache.exp > Date.now()) return json({ ok: true, iceServers: credCache.servers, turn: true, ttl: Math.floor((credCache.exp - Date.now()) / 1000) });
  try {
    const ttl = 900;   // 15 min: a credential that leaks is useful for minutes, not an hour
    const r = await fetch(`https://rtc.live.cloudflare.com/v1/turn/keys/${id}/credentials/generate-ice-servers`, {
      method: "POST", headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" }, body: JSON.stringify({ ttl }),
    });
    if (!r.ok) return json({ ok: true, iceServers: STUN, turn: false, ttl: 600 });
    const j: any = await r.json();
    const list = Array.isArray(j?.iceServers) ? j.iceServers : j?.iceServers ? [j.iceServers] : [];
    const turn = list.filter((s: any) => s && s.urls).map((s: any) => ({ urls: s.urls, username: s.username, credential: s.credential }));
    if (turn.length) credCache = { servers: [...STUN, ...turn], exp: Date.now() + 120 * 1000 };   // re-minted every 2 min
    return json({ ok: true, iceServers: turn.length ? [...STUN, ...turn] : STUN, turn: turn.length > 0, ttl: turn.length ? ttl - 120 : 600 });
  } catch {
    return json({ ok: true, iceServers: STUN, turn: false, ttl: 600 });
  }
});
