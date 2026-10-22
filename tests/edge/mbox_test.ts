// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// gizleme-mbox: deposit and read (ids have one shape each, a copy of a message is one row, the cursor), one call
// for many boxes (oldest first, capped, a row at the cursor's millisecond comes again), blobs and acks with the
// session (grace for older builds until the date, an unknown token never served), the sweeps, the limits.
import { assert, assertEquals, assertMatch } from "./assert.ts";
import { call, load, reset, session, store, table } from "./helpers.ts";

const h = await load("gizleme-mbox");
const BOX = "AAAAAAAAAAAAAAAAAAAAAA", BOX2 = "BBBBBBBBBBBBBBBBBBBBBB";
const mid = (n: number) => n.toString(16).padStart(16, "0");

Deno.test("put: shapes, size, one row per (box, id), a copy changes nothing", async () => {
  reset();
  assertEquals((await call(h, { action: "put", mbox: BOX, mid: mid(1) })).json.error, "missing");
  assertEquals((await call(h, { action: "put", mbox: "short", mid: mid(1), data: { x: 1 } })).json.error, "bad_id");
  assertEquals((await call(h, { action: "put", mbox: BOX, mid: "zz" + mid(1), data: { x: 1 } })).json.error, "bad_id");
  assertEquals((await call(h, { action: "put", mbox: BOX, mid: mid(1), data: { x: "y".repeat(400001) } })).status, 413);
  const r = await call(h, { action: "put", mbox: BOX, mid: mid(1), from: "dev1", data: { iv: "a", ct: "b" } });
  assertEquals(r.json, { ok: true });
  const r2 = await call(h, { action: "put", mbox: BOX, mid: mid(1), from: "dev1", data: { iv: "a", ct: "DIFFERENT" } });
  assertEquals(r2.json, { ok: true });
  const rows = table("gizleme_mbox"); assertEquals(rows.length, 1); assertEquals(rows[0].data.ct, "b");   // the first deposit stands
  assertEquals((await call(h, { action: "put", mbox: BOX, mid: "h" + mid(2), data: { t: "hello" } })).json, { ok: true });   // a prefixed id (hello)
  assertEquals((await call(h, { action: "put", mbox: BOX, mid: mid(3), data: { x: 1 } })).json, { ok: true });
  assertEquals(table("gizleme_mbox").map(x => x.mid), [mid(1), "h" + mid(2), mid(3)]);
});

Deno.test("get: since moves the cursor, bad shapes refused, server error is a 500", async () => {
  reset();
  const t0 = new Date(Date.now() - 3000).toISOString(), t1 = new Date(Date.now() - 2000).toISOString(), t2 = new Date(Date.now() - 1000).toISOString();
  table("gizleme_mbox").push({ mbox: BOX, mid: mid(1), from_user: null, data: { a: 1 }, ts: t0 }, { mbox: BOX, mid: mid(2), from_user: "d", data: { a: 2 }, ts: t1 }, { mbox: BOX2, mid: mid(3), from_user: null, data: { a: 3 }, ts: t2 });
  const all = await call(h, { action: "get", mbox: BOX });
  assertEquals(all.json.items.map((x: { mid: string }) => x.mid), [mid(1), mid(2)]);
  assertEquals(all.json.items[1], { mid: mid(2), from_user: "d", data: { a: 2 }, ts: t1 });
  const later = await call(h, { action: "get", mbox: BOX, since: t0 });
  assertEquals(later.json.items.map((x: { mid: string }) => x.mid), [mid(2)]);
  assertEquals((await call(h, { action: "get", mbox: BOX, since: "not a date" })).json.items.length, 2);   // an unreadable cursor reads everything
  assertEquals((await call(h, { action: "get", mbox: "x" })).json.error, "bad_id");
  store.fail.gizleme_mbox = { message: "timeout" };
  assertEquals((await call(h, { action: "get", mbox: BOX })).status, 500);
});

Deno.test("getmany: one call, rows oldest first across boxes, each box's cursor honoured, the cap says more", async () => {
  reset();
  const base = Date.now() - 100000;
  const ts = (i: number) => new Date(base + i * 10).toISOString();
  for (let i = 0; i < 20; i++) table("gizleme_mbox").push({ mbox: i % 2 ? BOX : BOX2, mid: mid(i), from_user: null, data: { i }, ts: ts(i) });
  const r = await call(h, { action: "getmany", boxes: [{ mbox: BOX, since: ts(9) }, { mbox: BOX2 }, { mbox: "bad" }, { mbox: BOX2 }] });
  assertEquals(r.status, 200); assertEquals(r.json.ok, true); assertEquals(r.json.more, false);
  assertEquals(Object.keys(r.json.items).sort(), [BOX, BOX2].sort());
  assertEquals(r.json.items[BOX].map((x: { data: { i: number } }) => x.data.i), [9, 11, 13, 15, 17, 19]);     // a row at the cursor's millisecond comes again (ids already seen are skipped by the client)
  assertEquals(r.json.items[BOX2].map((x: { data: { i: number } }) => x.data.i), [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]);
  assertEquals((await call(h, { action: "getmany", boxes: [] })).json, { ok: true, items: {} });
  assertEquals((await call(h, { action: "getmany", boxes: "nope" })).json, { ok: true, items: {} });
  // the cap: 1500 rows in one answer, and the flag that says the rest is owed
  reset();
  for (let i = 0; i < 1600; i++) table("gizleme_mbox").push({ mbox: BOX, mid: mid(i), from_user: null, data: { i }, ts: ts(i) });
  const big = await call(h, { action: "getmany", boxes: [{ mbox: BOX }] });
  assertEquals(big.json.items[BOX].length, 1500); assertEquals(big.json.more, true);
  assertEquals(big.json.items[BOX][1499].mid, mid(1499));                          // the oldest 1500: a prefix of what the box is owed
});

Deno.test("putblob / delblob / ack: the session (grace until the date for a request without one, never for an unknown token)", async () => {
  reset();
  const t = await session("oguz");
  const bytes = btoa("x".repeat(1000));
  const r = await call(h, { action: "putblob", token: t, data: bytes });
  assertEquals(r.status, 200); assertMatch(r.json.path, /^[a-f0-9]{48}\.bin$/);
  assertEquals(Object.keys(store.storage), [r.json.path]); assertEquals(store.storage[r.json.path].bytes.length, 1000);
  assertEquals((await call(h, { action: "putblob", token: "AAAA", data: bytes })).status, 401);   // a token that is present but unknown
  const grace = await call(h, { action: "putblob", data: bytes });                                  // an older build, no token: served until the grace date
  assertEquals(grace.status, Date.now() < Date.parse("2026-12-15T00:00:00Z") ? 200 : 401);
  assertEquals((await call(h, { action: "putblob", token: t, data: "" })).json.error, "missing");
  assertEquals((await call(h, { action: "putblob", token: t, data: "not base64 !!!" })).json.error, "bad_data");
  assertEquals((await call(h, { action: "putblob", token: t, data: btoa("x".repeat(2000001)) })).status, 413);
  assertEquals((await call(h, { action: "delblob", token: t, path: "../etc" })).json.error, "bad_path");
  assertEquals((await call(h, { action: "delblob", token: "AAAA", path: r.json.path })).status, 401);
  assertEquals((await call(h, { action: "delblob", token: t, path: r.json.path })).json, { ok: true });
  assert(!store.storage[r.json.path]);
  // ack: delivered_at set once, only for the named ids of that box
  const now = new Date().toISOString();
  table("gizleme_mbox").push({ mbox: BOX, mid: mid(1), data: {}, ts: now, delivered_at: null }, { mbox: BOX, mid: mid(2), data: {}, ts: now, delivered_at: null }, { mbox: BOX2, mid: mid(1), data: {}, ts: now, delivered_at: null });
  assertEquals((await call(h, { action: "ack", token: "AAAA", mbox: BOX, mids: [mid(1)] })).status, 401);
  assertEquals((await call(h, { action: "ack", token: t, mbox: BOX, mids: [mid(1), "junk"] })).json, { ok: true });
  assertEquals(table("gizleme_mbox").map(x => !!x.delivered_at), [true, false, false]);
  assertEquals((await call(h, { action: "ack", token: t, mbox: BOX, mids: [] })).json, { ok: true });
});

Deno.test("limits: 120 deposits a minute per box, 300 per address; an unknown action", async () => {
  reset();
  for (let i = 0; i < 120; i++) assertEquals((await call(h, { action: "put", mbox: BOX, mid: mid(i), data: { i } })).status, 200);
  assertEquals((await call(h, { action: "put", mbox: BOX, mid: mid(999), data: {} })).status, 429);
  assertEquals((await call(h, { action: "put", mbox: BOX2, mid: mid(999), data: {} })).status, 200);   // another box has its own budget
  for (let i = 0; i < 300; i++) assertEquals((await call(h, { action: "put", mbox: "CDE"[i % 3].repeat(22), mid: mid(i), data: {} }, { ip: "1.1.1.1" })).status, 200);   // three boxes, under their own budget
  assertEquals((await call(h, { action: "put", mbox: "F".repeat(22), mid: mid(1), data: {} }, { ip: "1.1.1.1" })).status, 429);
  assertEquals((await call(h, { action: "nothing" })).status, 400);
  assertEquals((await call(h, null, { method: "GET" })).json, { ok: true, service: "gizleme-mbox" });
});

Deno.test("sweeps: expired rows and delivered-and-aged rows go, old blobs too (once an hour)", async () => {
  reset();
  const old = new Date(Date.now() - 15 * 86400000).toISOString(), fresh = new Date().toISOString(), aged = new Date(Date.now() - 49 * 3600000).toISOString();
  table("gizleme_mbox").push({ mbox: BOX, mid: mid(1), data: {}, ts: old, delivered_at: null }, { mbox: BOX, mid: mid(2), data: {}, ts: fresh, delivered_at: aged }, { mbox: BOX, mid: mid(3), data: {}, ts: fresh, delivered_at: fresh }, { mbox: BOX, mid: mid(4), data: {}, ts: fresh, delivered_at: null });
  store.storage["a".repeat(48) + ".bin"] = { bytes: new Uint8Array(1), created_at: old };
  store.storage["b".repeat(48) + ".bin"] = { bytes: new Uint8Array(1), created_at: fresh };
  // the sweep runs in the background of one request in twenty: force the dice
  const rnd = Math.random; Math.random = () => 0;
  try { await call(h, { action: "put", mbox: BOX2, mid: mid(9), data: {} }); } finally { Math.random = rnd; }
  await new Promise(r => setTimeout(r, 20));   // the background work (no EdgeRuntime here: it simply runs)
  assertEquals(table("gizleme_mbox").map(x => x.mid).sort(), [mid(3), mid(4), mid(9)].sort());
  assertEquals(Object.keys(store.storage), ["b".repeat(48) + ".bin"]);
  assert(table("gizleme_config").some(r => r.key === "mediasweep"));   // and not again within the hour
  store.storage["c".repeat(48) + ".bin"] = { bytes: new Uint8Array(1), created_at: old };
  await call(h, { action: "putblob", token: await session("x"), data: btoa("y") });
  await new Promise(r => setTimeout(r, 20));
  assert(store.storage["c".repeat(48) + ".bin"]);
});
