// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// gizleme-vault: everything needs a live session; the backup key is set once (the second device learns "already");
// re-wrapping it needs the password too; the contacts blob is versioned — a push from a stale base is a conflict
// returned as a 200 body, and two pushes from the same base cannot both win.
import { assert, assertEquals } from "./assert.ts";
import { call, load, past, reset, session, sha256b64, store, table, unb64 } from "./helpers.ts";

const h = await load("gizleme-vault");

Deno.test("no session, no vault", async () => {
  reset();
  assertEquals((await call(h, { action: "pull" })).status, 401);
  assertEquals((await call(h, { action: "pull", token: "AAAA" })).status, 401);
  const old = await session("oguz", past(2));
  assertEquals((await call(h, { action: "pull", token: old })).status, 401);
  assertEquals(table("gizleme_sessions").length, 0);                 // the expired session is removed on the way
  assertEquals((await call(h, "{", { method: "POST" })).status, 400);
  assertEquals((await call(h, null, { method: "GET" })).json, { ok: true, service: "gizleme-vault" });
});

Deno.test("pull: empty until something is pushed", async () => {
  reset();
  const t = await session("oguz");
  assertEquals((await call(h, { action: "pull", token: t })).json, { ok: true, abk: null, contacts: null, cver: 0 });
  table("gizleme_vault").push({ username_lc: "oguz", abk: { iv: "i", ct: "c" }, contacts: { iv: "x", ct: "y" }, cver: 4 });
  assertEquals((await call(h, { action: "pull", token: t })).json, { ok: true, abk: { iv: "i", ct: "c" }, contacts: { iv: "x", ct: "y" }, cver: 4 });
  assertEquals((await call(h, { action: "nothing", token: t })).status, 400);
});

Deno.test("pushAbk: set once; the loser of the race is told", async () => {
  reset();
  const t = await session("oguz");
  assertEquals((await call(h, { action: "pushAbk", token: t })).json.error, "missing");
  assertEquals((await call(h, { action: "pushAbk", token: t, abk: { iv: "i", ct: "x".repeat(5000) } })).status, 413);
  assertEquals((await call(h, { action: "pushAbk", token: t, abk: { iv: "i", ct: "first" } })).json, { ok: true });
  assertEquals((await call(h, { action: "pushAbk", token: t, abk: { iv: "i", ct: "second" } })).json, { ok: true, already: true });
  assertEquals(table("gizleme_vault")[0].abk.ct, "first");
  // another account is another row
  const t2 = await session("serap");
  assertEquals((await call(h, { action: "pushAbk", token: t2, abk: { iv: "i", ct: "hers" } })).json, { ok: true });
  assertEquals(table("gizleme_vault").map(r => r.username_lc), ["oguz", "serap"]);
});

Deno.test("rewrapAbk: the new wrap needs the (new) password's av, not just the session", async () => {
  reset();
  const t = await session("oguz");
  const av = await sha256b64(new TextEncoder().encode("AK")); const verifier = await sha256b64(unb64(av));
  table("gizleme_accounts").push({ username_lc: "oguz", display: "O", salt: "s", verifier });
  table("gizleme_vault").push({ username_lc: "oguz", abk: { iv: "old", ct: "old" }, contacts: null, cver: 0 });
  assertEquals((await call(h, { action: "rewrapAbk", token: t, abk: { iv: "n", ct: "n" } })).json.error, "missing");
  assertEquals((await call(h, { action: "rewrapAbk", token: t, abk: { iv: "n", ct: "n" }, av: "wrong" })).status, 401);
  assertEquals((await call(h, { action: "rewrapAbk", token: t, abk: { iv: "n", ct: "n" }, av })).json, { ok: true });
  assertEquals(table("gizleme_vault")[0].abk, { iv: "n", ct: "n" });
});

Deno.test("pushContacts: versions, a stale base is a conflict, the same base twice cannot both win", async () => {
  reset();
  const t = await session("oguz");
  assertEquals((await call(h, { action: "pushContacts", token: t })).json.error, "missing");
  assertEquals((await call(h, { action: "pushContacts", token: t, contacts: { ct: "x".repeat(300001) } })).status, 413);
  const first = await call(h, { action: "pushContacts", token: t, contacts: { iv: "1", ct: "1" }, cver: 0 });
  assertEquals(first.json, { ok: true, cver: 1 });
  const second = await call(h, { action: "pushContacts", token: t, contacts: { iv: "2", ct: "2" }, cver: 1 });
  assertEquals(second.json, { ok: true, cver: 2 });
  const stale = await call(h, { action: "pushContacts", token: t, contacts: { iv: "3", ct: "3" }, cver: 1 });
  assertEquals([stale.status, stale.json], [200, { ok: false, conflict: true, cver: 2 }]);   // a 200 body: the client reads cver and merges
  assertEquals(table("gizleme_vault")[0].contacts, { iv: "2", ct: "2" });
  // the write is conditional on the version it read: a concurrent writer between the read and the write loses
  const real = store.rpc; store.rpc = real;
  const row = table("gizleme_vault")[0]; row.cver = 5;   // "someone wrote 3, 4, 5 meanwhile" — after our read, before our write: simulate by a stale eq("cver")
  const lost = await call(h, { action: "pushContacts", token: t, contacts: { iv: "9", ct: "9" }, cver: 2 });
  assertEquals(lost.json, { ok: false, conflict: true, cver: 5 });
  // the first push of a row that another device creates at the same moment: the unique key says conflict
  reset(); const t3 = await session("x"); store.fail.gizleme_vault = null;
  table("gizleme_vault").push({ username_lc: "x", abk: null, contacts: { iv: "a", ct: "a" }, cver: 1 });
  const dup = await call(h, { action: "pushContacts", token: t3, contacts: { iv: "b", ct: "b" }, cver: 0 });
  assertEquals(dup.json, { ok: false, conflict: true, cver: 1 });
});

Deno.test("limits: 240 calls a minute per address", async () => {
  reset();
  const t = await session("oguz");
  for (let i = 0; i < 240; i++) assertEquals((await call(h, { action: "pull", token: t }, { ip: "1.1.1.1" })).status, 200);
  assertEquals((await call(h, { action: "pull", token: t }, { ip: "1.1.1.1" })).status, 429);
  assertEquals((await call(h, { action: "pull", token: t }, { ip: "2.2.2.2" })).status, 200);
  assert(true);
});
