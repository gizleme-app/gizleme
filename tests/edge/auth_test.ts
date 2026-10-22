// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// gizleme-auth: the account life cycle as the client drives it — check, register, salt, login, validate,
// rename, changepw, delete, logout — and what the function refuses (bad names, a taken name, a wrong password,
// a stolen token alone, a database error on validate, the rate limits, a foreign origin).
import { assert, assertEquals, assertMatch } from "./assert.ts";
import { call, load, reset, session, sha256b64, store, table, unb64, past } from "./helpers.ts";

const h = await load("gizleme-auth");
const SALT = btoa("0123456789abcdef");
async function creds(pw: string) {   // what the client sends: av = sha256(AK) and verifier = sha256(av bytes)
  const ak = new TextEncoder().encode("AK:" + pw); const av = await sha256b64(ak); const verifier = await sha256b64(unb64(av));
  return { av, verifier };
}

Deno.test("preflight and GET: CORS for the app's origins only", async () => {
  reset();
  const pre = await call(h, null, { method: "OPTIONS", origin: "https://www.gizleme.com" });
  assertEquals(pre.status, 200); assertEquals(pre.headers.get("Access-Control-Allow-Origin"), "https://www.gizleme.com");
  const foreign = await call(h, null, { method: "OPTIONS", origin: "https://evil.example" });
  assertEquals(foreign.headers.get("Access-Control-Allow-Origin"), "https://gizleme.com");   // never echoes a stranger
  const get = await call(h, null, { method: "GET" });
  assertEquals(get.json, { ok: true, service: "gizleme-auth" });
  const bad = await call(h, "{not json");
  assertEquals(bad.status, 400);
});

Deno.test("check: format, free, taken", async () => {
  reset();
  assertEquals((await call(h, { action: "check", username: "Oğ" })).json, { ok: true, available: false, reason: "format" });
  assertEquals((await call(h, { action: "check", username: "Oguz_2026" })).json, { ok: true, available: true });
  table("gizleme_accounts").push({ username_lc: "oguz_2026", display: "Oğuz", salt: SALT, verifier: "v" });
  assertEquals((await call(h, { action: "check", username: "  OGUZ_2026 " })).json, { ok: true, available: false });   // case and spaces normalised
});

Deno.test("register: a session comes back, the name is taken afterwards, fields are required", async () => {
  reset();
  const { verifier } = await creds("password123");
  const r = await call(h, { action: "register", username: "Serap", display: "Serap ✨", salt: SALT, verifier });
  assertEquals(r.status, 200); assert(r.json.ok); assertEquals(r.json.username, "serap"); assertEquals(r.json.display, "Serap ✨");
  assertMatch(r.json.token, /^[A-Za-z0-9+/]{43}=$/);
  const sess = table("gizleme_sessions"); assertEquals(sess.length, 1); assertEquals(sess[0].username_lc, "serap");
  assertEquals(sess[0].token_hash, await sha256b64(unb64(r.json.token)));   // only the hash is stored
  assert(Date.parse(sess[0].expires_at) > Date.now() + 360 * 86400000);
  const again = await call(h, { action: "register", username: "serap", salt: SALT, verifier });
  assertEquals([again.status, again.json.error], [409, "taken"]);
  assertEquals((await call(h, { action: "register", username: "ab", salt: SALT, verifier })).json.error, "invalid_username");
  assertEquals((await call(h, { action: "register", username: "abc", salt: SALT })).json.error, "missing_fields");
});

Deno.test("salt: a real one for an account, a stable fake one for anyone else", async () => {
  reset();
  table("gizleme_accounts").push({ username_lc: "oguz", display: "Oğuz", salt: SALT, verifier: "v" });
  assertEquals((await call(h, { action: "salt", username: "OGUZ" })).json, { ok: true, salt: SALT });
  const a = (await call(h, { action: "salt", username: "nobody" })).json; const b = (await call(h, { action: "salt", username: "nobody" })).json;
  assert(a.ok && a.salt && a.salt === b.salt && a.salt !== SALT);      // same answer each time: the endpoint doesn't say who exists
  assertEquals(unb64(a.salt).length, 16);
  const c = (await call(h, { action: "salt", username: "nobody2" })).json; assert(c.salt !== a.salt);
  assert(table("gizleme_config").some(r => r.key === "authsecret"));     // the secret was minted once and stored
});

Deno.test("login: the right password gives a session, the wrong one counts, ten wrong ones pause the name", async () => {
  reset();
  const good = await creds("password123"), bad = await creds("wrong");
  table("gizleme_accounts").push({ username_lc: "oguz", display: "Oğuz", salt: SALT, verifier: good.verifier });
  const ok = await call(h, { action: "login", username: "Oguz", av: good.av });
  assertEquals([ok.status, ok.json.ok, ok.json.display], [200, true, "Oğuz"]);
  const no = await call(h, { action: "login", username: "oguz", av: bad.av });
  assertEquals([no.status, no.json.error], [401, "bad_login"]);
  assertEquals((await call(h, { action: "login", username: "ghost", av: bad.av })).status, 401);   // unknown name: the same answer
  for (let i = 0; i < 9; i++) await call(h, { action: "login", username: "oguz", av: bad.av });
  const paused = await call(h, { action: "login", username: "oguz", av: bad.av });
  assertEquals([paused.status, paused.json.error], [429, "rate_limited"]);
  // the fake keeps the counter the way gz_rl_hit does: the peek before the lookup sees n >= 10
  table("gizleme_rl").push({ k: "auth:loginfail:oguz", n: 10, ws: new Date().toISOString() });
  assertEquals((await call(h, { action: "login", username: "oguz", av: good.av })).status, 429);   // even the right password waits
  assertEquals((await call(h, { action: "login", username: "oguz" })).status, 400);
});

Deno.test("validate: a verdict only after a successful lookup", async () => {
  reset();
  table("gizleme_accounts").push({ username_lc: "oguz", display: "Oğuz", salt: SALT, verifier: "v" });
  const t = await session("oguz");
  assertEquals((await call(h, { action: "validate", token: t })).json, { ok: true, valid: true, username: "oguz", display: "Oğuz" });
  assertEquals((await call(h, { action: "validate", token: "AAAA" })).json, { ok: true, valid: false });
  const old = await session("oguz", past(1));
  assertEquals((await call(h, { action: "validate", token: old })).json, { ok: true, valid: false });
  assertEquals(table("gizleme_sessions").length, 1);                       // the expired row is gone
  store.fail.gizleme_sessions = { message: "connection refused" };
  const err = await call(h, { action: "validate", token: t });
  assertEquals(err.status, 500); assertEquals(err.json.valid, undefined);   // v42: never "no such session" on a database error
  assertEquals((await call(h, { action: "validate" })).status, 400);
});

Deno.test("rename needs a live session; logout forgets the token", async () => {
  reset();
  table("gizleme_accounts").push({ username_lc: "oguz", display: "Oğuz", salt: SALT, verifier: "v" });
  const t = await session("oguz");
  assertEquals((await call(h, { action: "rename", token: "nope", display: "X" })).status, 401);
  const r = await call(h, { action: "rename", token: t, display: "  Oğuz Seran, the one and only, really  " });
  assertEquals(r.json, { ok: true, display: "Oğuz Seran, the one and" });   // 24 chars, trimmed
  assertEquals(table("gizleme_accounts")[0].display, "Oğuz Seran, the one and");
  assertEquals((await call(h, { action: "logout", token: t })).json, { ok: true });
  assertEquals(table("gizleme_sessions").length, 0);
  assertEquals((await call(h, { action: "rename", token: t, display: "X" })).status, 401);
});

Deno.test("changepw: session AND password, one transaction, the other sessions go", async () => {
  reset();
  const cur = await creds("password123"), nxt = await creds("newpass456");
  table("gizleme_accounts").push({ username_lc: "oguz", display: "Oğuz", salt: SALT, verifier: cur.verifier });
  table("gizleme_vault").push({ username_lc: "oguz", abk: { iv: "old", ct: "old" }, contacts: null, cver: 3 });
  const mine = await session("oguz"), other = await session("oguz");
  assertEquals((await call(h, { action: "changepw", token: mine, av: "wrong", salt: "s2", verifier: nxt.verifier })).json.error, "bad_login");
  assertEquals((await call(h, { action: "changepw", token: "stolen", av: cur.av, salt: "s2", verifier: nxt.verifier })).status, 401);
  assertEquals((await call(h, { action: "changepw", token: mine, av: cur.av, verifier: nxt.verifier })).json.error, "missing_fields");
  const r = await call(h, { action: "changepw", token: mine, av: cur.av, salt: "s2", verifier: nxt.verifier, abk: { iv: "n", ct: "n", extra: "dropped" } });
  assertEquals(r.json, { ok: true });
  assertEquals(table("gizleme_accounts")[0].verifier, nxt.verifier); assertEquals(table("gizleme_accounts")[0].salt, "s2");
  assertEquals(table("gizleme_vault")[0].abk, { iv: "n", ct: "n" });
  const left = table("gizleme_sessions"); assertEquals(left.length, 1); assertEquals(left[0].token_hash, await sha256b64(unb64(mine)));
  assertEquals((await call(h, { action: "validate", token: other })).json.valid, false);
  // the transaction refusing (no such account) is "unauthorized", a failing one is a 500 — never a half change
  store.rpc.gz_change_password = () => false;
  assertEquals((await call(h, { action: "changepw", token: mine, av: nxt.av, salt: "s3", verifier: cur.verifier })).status, 401);
  store.rpc.gz_change_password = () => { throw new Error("deadlock"); };
  assertEquals((await call(h, { action: "changepw", token: mine, av: nxt.av, salt: "s3", verifier: cur.verifier })).status, 500);
});

Deno.test("delete: everything the server holds for the account, and only with the password", async () => {
  reset();
  const cur = await creds("password123");
  table("gizleme_accounts").push({ username_lc: "oguz", display: "Oğuz", salt: SALT, verifier: cur.verifier });
  table("gizleme_accounts").push({ username_lc: "serap", display: "Serap", salt: SALT, verifier: "v" });
  table("gizleme_vault").push({ username_lc: "oguz", abk: {}, contacts: {}, cver: 1 }, { username_lc: "serap", abk: {}, contacts: {}, cver: 1 });
  table("gizleme_push_subs").push({ notify_key: "k1", owner: "dev1", acct: "A", sub: {} }, { notify_key: "k2", owner: "dev9", acct: "A", sub: {} }, { notify_key: "k1", owner: "devS", acct: "S", sub: {} });
  const t = await session("oguz"); await session("oguz"); await session("serap");
  assertEquals((await call(h, { action: "delete", token: t, av: "wrong" })).status, 401);
  const r = await call(h, { action: "delete", token: t, av: cur.av, owners: ["dev1"], acct: "A" });
  assertEquals(r.json, { ok: true });
  assertEquals(table("gizleme_accounts").map(a => a.username_lc), ["serap"]);
  assertEquals(table("gizleme_vault").map(a => a.username_lc), ["serap"]);
  assertEquals(table("gizleme_sessions").map(a => a.username_lc), ["serap"]);
  assertEquals(table("gizleme_push_subs").map(a => a.owner), ["devS"]);   // by account marker and by device
});

Deno.test("rate limits: check is slow per IP, register ten an hour", async () => {
  reset();
  for (let i = 0; i < 20; i++) assertEquals((await call(h, { action: "check", username: "x" + i + "yz" }, { ip: "1.2.3.4" })).status, 200);
  assertEquals((await call(h, { action: "check", username: "another" }, { ip: "1.2.3.4" })).status, 429);
  assertEquals((await call(h, { action: "check", username: "another" }, { ip: "5.6.7.8" })).status, 200);   // another address is fine
  const { verifier } = await creds("pw");
  for (let i = 0; i < 10; i++) assertEquals((await call(h, { action: "register", username: "user" + i, salt: SALT, verifier }, { ip: "9.9.9.9" })).status, 200);
  assertEquals((await call(h, { action: "register", username: "user11", salt: SALT, verifier }, { ip: "9.9.9.9" })).status, 429);
  // a counter the database can't keep fails open: the service stays up without its limits
  store.rpc.gz_rl_hit = () => { throw new Error("down"); };
  assertEquals((await call(h, { action: "check", username: "another" }, { ip: "1.2.3.4" })).status, 200);
  assertEquals((await call(h, { action: "nothing" })).json.error, "unknown_action");
});
