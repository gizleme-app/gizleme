// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
import webpush from "npm:web-push@3.6.7";
import { createClient } from "jsr:@supabase/supabase-js@2";

const db = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  { auth: { persistSession: false } }
);

const SUBS = "gizleme_push_subs";
const CONF = "gizleme_config";
const ORIGIN = "https://gizleme.com";

// VAPID keypair: generated once on first run, kept server-side in gizleme_config.
// The private key never appears in source, in the client, or in any response.
let vapidCache: { publicKey: string; privateKey: string } | null = null;
async function getVapid() {
  if (vapidCache) return vapidCache;
  const { data } = await db.from(CONF).select("value").eq("key", "vapid").maybeSingle();
  if (data?.value?.publicKey && data?.value?.privateKey) {
    vapidCache = data.value; return vapidCache;
  }
  // first run: whoever inserts first wins, and every instance then uses the stored pair — two cold instances
  // each keeping their own would sign pushes with a key the subscriptions were not made for
  const keys = webpush.generateVAPIDKeys();
  await db.from(CONF).upsert({ key: "vapid", value: keys, updated_at: new Date().toISOString() }, { onConflict: "key", ignoreDuplicates: true });
  const { data: again } = await db.from(CONF).select("value").eq("key", "vapid").maybeSingle();
  vapidCache = (again?.value?.publicKey && again?.value?.privateKey) ? again.value : keys; return vapidCache!;
}
async function configured() {
  const v = await getVapid();
  webpush.setVapidDetails("mailto:admin@gizleme.com", v.publicKey, v.privateKey);
  return v.publicKey;
}

// Only the app's own origins may call these functions from a browser (the Supabase gateway adds nothing).
const ORIGINS = ["https://gizleme.com", "https://www.gizleme.com"];
const cors = {   // the base; each request gets its own copy with its (allowed) origin — see corsFor
  "Access-Control-Allow-Origin": "https://gizleme.com",
  "Vary": "Origin",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
};
const json = (o: unknown, status = 200) =>
  new Response(JSON.stringify(o), { status, headers: { ...cors, "Content-Type": "application/json" } });
function corsFor(req: Request){ const o = req.headers.get("origin") || ""; return { ...cors, "Access-Control-Allow-Origin": ORIGINS.includes(o) ? o : ORIGINS[0] }; }
function clean(s: unknown, n = 512): string { return (s ?? "").toString().slice(0, n); }

// ---- abuse controls ----
function ipOf(req: Request) {
  const h = req.headers;
  return h.get("cf-connecting-ip") || h.get("x-real-ip") || (h.get("x-forwarded-for") || "").split(",")[0].trim() || "";
}
// Fixed-window counter in Postgres (gz_rl_hit, service-role only). Fails open if the DB call errors.
async function rl(key: string, limit: number, windowS: number) {
  try { const { data, error } = await db.rpc("gz_rl_hit", { p_key: key, p_limit: limit, p_window_s: windowS }); if (error) return true; return data !== false; }
  catch { return true; }
}
// Only real browser push services may be registered as endpoints: the function must never become a
// generic HTTP relay (anyone could otherwise register an arbitrary URL and have us POST to it).
const PUSH_HOSTS = [".push.apple.com", "fcm.googleapis.com", ".notify.windows.com", ".push.services.mozilla.com", ".samsungosp.com"];
function endpointOk(ep: unknown) {
  try { const u = new URL(String(ep)); if (u.protocol !== "https:") return false; const h = u.hostname.toLowerCase();
    return PUSH_HOSTS.some(s => s.startsWith(".") ? h.endsWith(s) : h === s); } catch { return false; }
}
// A notification tap only ever opens Gizleme on the chat of that notify key: the url is built here, never
// taken from the request (a client-supplied "#i=" invite or "#g=" group link would be acted on by the app).
function targetUrl(nk: string) { return ORIGIN + "/#n=" + encodeURIComponent(nk); }

Deno.serve(async (req) => {
  const cors = corsFor(req);
  const json = (o: unknown, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { ...cors, "Content-Type": "application/json" } });
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  const pub = await configured();
  if (req.method === "GET") return json({ ok: true, publicKey: pub, hasIp: !!ipOf(req) });

  let body: any;
  try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }
  const action = body?.action;
  const ip = ipOf(req);

  try {
    if (action === "vapid") return json({ ok: true, publicKey: pub });

    if (action === "register") {
      if (ip && !(await rl("push:reg:" + ip, 60, 600))) return json({ error: "rate_limited" }, 429);
      const owner = clean(body.owner, 64);
      const acct = body.acct ? clean(body.acct, 64) : null;
      const keys: string[] = Array.isArray(body.notify_keys) ? body.notify_keys.map((k: unknown) => clean(k, 64)).filter(Boolean) : [];
      const sub = body.sub;
      if (!owner || !sub || !sub.endpoint || keys.length === 0) return json({ error: "missing fields" }, 400);
      if (!endpointOk(sub.endpoint)) return json({ error: "bad_endpoint" }, 400);
      const slim = { endpoint: String(sub.endpoint), expirationTime: sub.expirationTime ?? null, keys: sub.keys };
      if (typeof sub.endpoint !== "string" || sub.endpoint.length > 1024 || !sub.keys || typeof sub.keys.p256dh !== "string" || typeof sub.keys.auth !== "string" || sub.keys.p256dh.length > 200 || sub.keys.auth.length > 64) return json({ error: "bad_sub" }, 400);
      const slimKeys = { p256dh: sub.keys.p256dh, auth: sub.keys.auth }; slim.keys = slimKeys;
      // the list is this device's complete set of contacts: keys it no longer lists (a removed contact) are
      // dropped, so a former contact cannot keep waking the device
      const rows = [...new Set(keys)].slice(0, 200).map((nk) => ({ notify_key: nk, owner, acct, sub: slim, name: null, updated_at: new Date().toISOString() }));
      const { error } = await db.from(SUBS).upsert(rows, { onConflict: "notify_key,owner" });
      if (error) return json({ error: error.message }, 500);
      const keep = rows.map(r => r.notify_key).filter(k => /^[A-Za-z0-9_-]+$/.test(k));
      if (keep.length) await db.from(SUBS).delete().eq("owner", owner).not("notify_key", "in", "(" + keep.join(",") + ")");
      return json({ ok: true, registered: rows.length });
    }

    if (action === "unregister") {
      const owner = clean(body.owner, 64);
      if (!owner) return json({ error: "missing owner" }, 400);
      if (body.notify_key) await db.from(SUBS).delete().eq("notify_key", clean(body.notify_key, 64)).eq("owner", owner);
      else await db.from(SUBS).delete().eq("owner", owner);
      return json({ ok: true });
    }

    if (action === "notify") {
      const notify_key = clean(body.notify_key, 64);
      const from = clean(body.from, 64);
      const from_acct = body.from_acct ? clean(body.from_acct, 64) : "";
      if (!notify_key) return json({ error: "missing notify_key" }, 400);
      const kind = body.kind === "chat" ? "chat" : body.kind === "call" ? "call" : body.kind === "missed" ? "missed" : "msg";
      const ringing = kind === "call" || kind === "missed";
      // a call rings again every few seconds while it isn't answered: its own, larger bucket (messages keep theirs)
      if (!(await rl((ringing ? "push:ntc:" : "push:nt:") + notify_key, ringing ? 40 : 12, 600))) return json({ ok: true, sent: 0, targets: 0, limited: true });
      if (ip && !(await rl("push:ntip:" + ip, 120, 600))) return json({ error: "rate_limited" }, 429);
      const { data, error } = await db.from(SUBS).select("owner, acct, sub").eq("notify_key", notify_key);
      if (error) return json({ error: error.message }, 500);
      // never wake the sending device, nor the sender's other devices (same account marker)
      // at most 8 devices per notify key (a contact pair has a handful): no amplification through bulk registrations
      const targets = (data || []).filter((r: any) => r.owner !== from && !(from_acct && r.acct && r.acct === from_acct)).slice(0, 8);
      const payload = JSON.stringify({
        title: "Gizleme",
        body:  kind === "call" ? "Incoming call" : kind === "missed" ? "Missed call" : kind === "chat" ? "A contact wants to chat" : "New message",   // fixed text: the receiving device puts the name on it
        kind,
        tag:   clean(body.tag, 64)   || notify_key.slice(0, 12),
        url:   targetUrl(notify_key),
      });
      let sent = 0; const dead: string[] = [];
      for (const r of targets) {
        // a ringing alert is only worth delivering while the call can still be answered
        try { await webpush.sendNotification(r.sub, payload, { TTL: kind === "call" ? 45 : 1800, urgency: "high" }); sent++; }
        catch (e: any) { const sc = e?.statusCode; if (sc === 404 || sc === 410) dead.push(r.owner); }
      }
      if (dead.length) await db.from(SUBS).delete().eq("notify_key", notify_key).in("owner", dead);
      return json({ ok: true, sent, targets: targets.length, pruned: dead.length });
    }

    return json({ error: "unknown action" }, 400);
  } catch (e: any) {
    return json({ error: String(e?.message || e) }, 500);
  }
});
