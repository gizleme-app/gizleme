// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
import { createClient } from "jsr:@supabase/supabase-js@2";

const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
const TABLE = "gizleme_mbox";
const CONF = "gizleme_config";
const BUCKET = "vesper-media";
const TTL_DAYS = 14;          // undelivered ciphertext (messages and photo blobs) is deleted after this
const DELIVERED_GRACE_H = 48;  // a delivered message stays this long for the account's other devices, then goes

// Only the app's own origins may call these functions from a browser (the Supabase gateway adds nothing).
const ORIGINS = ["https://gizleme.com", "https://www.gizleme.com"];
const cors = {   // the base; each request gets its own copy with its (allowed) origin — see corsFor
  "Access-Control-Allow-Origin": "https://gizleme.com",
  "Vary": "Origin",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (o: unknown, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { ...cors, "Content-Type": "application/json" } });
function corsFor(req: Request){ const o = req.headers.get("origin") || ""; return { ...cors, "Access-Control-Allow-Origin": ORIGINS.includes(o) ? o : ORIGINS[0] }; }
function clean(s: unknown, n = 512){ return (s ?? "").toString().slice(0, n); }
// ids have one shape each (the client derives them): a mailbox is 16 bytes base64url, a message id 16 hex
// digits with an optional one-letter prefix (h/r/u/n for hellos, receipts and link notices)
const MBOX_RE = /^[A-Za-z0-9_-]{22}$/, MID_RE = /^[a-z]?[a-f0-9]{16}$/;

// ---- abuse controls ----
function ipOf(req: Request) {
  const h = req.headers;
  return h.get("cf-connecting-ip") || h.get("x-real-ip") || (h.get("x-forwarded-for") || "").split(",")[0].trim() || "";
}
async function rl(key: string, limit: number, windowS: number) {
  try { const { data, error } = await db.rpc("gz_rl_hit", { p_key: key, p_limit: limit, p_window_s: windowS }); if (error) return true; return data !== false; }
  catch { return true; }
}

// Expired rows go in the background of one request in twenty (both deletes use their own index), and the
// runtime is told to let the work finish after the response has been sent.
async function sweep(){ try{
  const cutoff = new Date(Date.now() - TTL_DAYS*24*3600*1000).toISOString(); await db.from(TABLE).delete().lt("ts", cutoff);
  const dcut = new Date(Date.now() - DELIVERED_GRACE_H*3600*1000).toISOString(); await db.from(TABLE).delete().lt("delivered_at", dcut);
}catch(_){} }
function later(p: Promise<unknown>){ try { (globalThis as any).EdgeRuntime?.waitUntil?.(p); } catch { /* not available: best effort */ } }
function sweepSoon(){ if (Math.random() < 0.05) later(sweep()); }

// Photo blobs that were never viewed (a viewed photo is deleted by the viewer) expire like messages.
// Runs at most once an hour, piggybacking on normal traffic.
async function sweepStorage(){
  try{
    const { data: c } = await db.from(CONF).select("value").eq("key", "mediasweep").maybeSingle();
    const last = Date.parse(c?.value?.at || "") || 0;
    if (Date.now() - last < 3600 * 1000) return;
    await db.from(CONF).upsert({ key: "mediasweep", value: { at: new Date().toISOString() }, updated_at: new Date().toISOString() }, { onConflict: "key" });
    const cutoff = Date.now() - TTL_DAYS*24*3600*1000;
    const old: string[] = [];
    const scan = async (prefix: string, depth: number) => {
      const { data } = await db.storage.from(BUCKET).list(prefix, { limit: 1000, sortBy: { column: "created_at", order: "asc" } });
      for (const e of data || []) {
        const path = prefix ? prefix + "/" + e.name : e.name;
        if (!e.id) { if (depth < 1) await scan(path, depth + 1); continue; }      // a folder (legacy <room>/ layout)
        const t = Date.parse(e.created_at || "") || 0;
        if (t && t < cutoff) old.push(path);
      }
    };
    await scan("", 0);
    for (let i = 0; i < old.length; i += 100) await db.storage.from(BUCKET).remove(old.slice(i, i + 100));
  }catch(_){}
}

Deno.serve(async (req) => {
  const cors = corsFor(req);
  const json = (o: unknown, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { ...cors, "Content-Type": "application/json" } });
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method === "GET") return json({ ok: true, service: "gizleme-mbox" });
  let body: any; try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }
  const action = body?.action;
  const ip = ipOf(req);
  try {
    if (action === "put") {
      const mbox = clean(body.mbox, 64); const mid = clean(body.mid, 64);
      const from_user = body.from ? clean(body.from, 64) : null;
      const data = body.data;
      if (!mbox || !mid || !data || typeof data !== "object") return json({ error: "missing" }, 400);
      if (!MBOX_RE.test(mbox) || !MID_RE.test(mid)) return json({ error: "bad_id" }, 400);
      if (JSON.stringify(data).length > 400000) return json({ error: "too_big" }, 413);
      if (!(await rl("mbox:put:" + mbox, 120, 60))) return json({ error: "rate_limited" }, 429);
      if (ip && !(await rl("mbox:putip:" + ip, 300, 60))) return json({ error: "rate_limited" }, 429);
      const { error } = await db.from(TABLE).upsert({ mbox, mid, from_user, data, ts: new Date().toISOString() }, { onConflict: "mbox,mid", ignoreDuplicates: true });
      if (error) return json({ error: error.message }, 500);
      sweepSoon(); later(sweepStorage());
      return json({ ok: true });
    }
    if (action === "get") {
      const mbox = clean(body.mbox, 64); if (!mbox) return json({ error: "missing" }, 400);
      if (!MBOX_RE.test(mbox)) return json({ error: "bad_id" }, 400);
      if (ip && !(await rl("mbox:getip:" + ip, 400, 60))) return json({ error: "rate_limited" }, 429);
      const d = body.since ? new Date(body.since) : null;
      const since = d && !isNaN(d.getTime()) ? d.toISOString() : new Date(0).toISOString();
      const { data, error } = await db.from(TABLE).select("mid, from_user, data, ts").eq("mbox", mbox).gt("ts", since).order("ts", { ascending: true }).limit(300);
      if (error) return json({ error: error.message }, 500);
      sweepSoon();
      return json({ ok: true, items: data || [] });
    }
    if (action === "putblob") {
      // Encrypted photo blob (AES-GCM ciphertext; the key travels inside the message, never here).
      // Uploads go through this function so the bucket accepts nothing from the public anon key.
      if (ip && !(await rl("mbox:blobip:" + ip, 30, 60))) return json({ error: "rate_limited" }, 429);
      const b64 = clean(body.data, 2800000);
      if (!b64) return json({ error: "missing" }, 400);
      let bytes: Uint8Array; try { bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0)); } catch { return json({ error: "bad_data" }, 400); }
      if (bytes.length > 2000000) return json({ error: "too_big" }, 413);
      const path = Array.from(crypto.getRandomValues(new Uint8Array(24)), b => b.toString(16).padStart(2, "0")).join("") + ".bin";
      const { error } = await db.storage.from(BUCKET).upload(path, bytes, { contentType: "application/octet-stream", upsert: false });
      if (error) return json({ error: error.message }, 500);
      later(sweepStorage());
      return json({ ok: true, path });
    }
    if (action === "delblob") {
      // The viewer deletes a view-once photo after showing it. Paths are random and unlistable.
      const path = clean(body.path, 128);
      if (!/^[a-f0-9]{48}\.bin$/.test(path) && !/^[A-Z0-9a-z]{1,40}\/[a-f0-9]{16}\.bin$/.test(path)) return json({ error: "bad_path" }, 400);
      if (ip && !(await rl("mbox:delip:" + ip, 60, 60))) return json({ error: "rate_limited" }, 429);
      await db.storage.from(BUCKET).remove([path]);
      return json({ ok: true });
    }
    if (action === "ack") {
      // "a device of the account has it": the ciphertext is kept DELIVERED_GRACE_H more for the account's
      // other devices, then deleted by the sweep — rather than lingering for the full TTL.
      const mbox = clean(body.mbox, 64); const mids: string[] = Array.isArray(body.mids) ? body.mids.map((m: unknown)=>clean(m,64)).filter(Boolean).slice(0, 300) : [];
      if (!mbox || !mids.length) return json({ ok: true });
      if (!MBOX_RE.test(mbox)) return json({ error: "bad_id" }, 400);
      if (ip && !(await rl("mbox:ackip:" + ip, 400, 60))) return json({ error: "rate_limited" }, 429);
      await db.from(TABLE).update({ delivered_at: new Date().toISOString() }).eq("mbox", mbox).in("mid", mids).is("delivered_at", null);
      sweepSoon();
      return json({ ok: true });
    }
    return json({ error: "unknown_action" }, 400);
  } catch (e: any) { return json({ error: String(e?.message || e) }, 500); }
});
