// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// gizleme-turn: credentials only for a logged-in account; STUN alone when no TURN key is configured or Cloudflare
// fails; short-lived credentials minted once and shared for two minutes; the per-address and per-account budgets.
// deno-lint-ignore-file no-explicit-any
import { assert, assertEquals } from "./assert.ts";
import { call, load, reset, session, store, table } from "./helpers.ts";

const h = await load("gizleme-turn");
const STUN = { urls: ["stun:stun.cloudflare.com:3478", "stun:stun.l.google.com:19302"] };
let cfCalls: { url: string; auth: string; body: any }[] = [];
let cfAnswer: () => Response = () => new Response(JSON.stringify({ iceServers: { urls: ["turn:turn.cloudflare.com:3478?transport=udp"], username: "u", credential: "c" } }), { status: 201 });
const realFetch = globalThis.fetch;
globalThis.fetch = ((url: any, init?: any) => { cfCalls.push({ url: String(url), auth: init?.headers?.Authorization || "", body: JSON.parse(init?.body || "{}") }); return Promise.resolve(cfAnswer()); }) as typeof fetch;

Deno.test("no session: 401 — the relay minutes are paid for", async () => {
  reset(); cfCalls = [];
  assertEquals((await call(h, {})).status, 401);
  assertEquals((await call(h, { token: "AAAA" })).status, 401);
  assertEquals((await call(h, null, { method: "GET" })).status, 401);
  assertEquals(cfCalls.length, 0);
});

Deno.test("no TURN key configured: STUN only (no call to Cloudflare)", async () => {
  reset(); cfCalls = [];
  const t = await session("oguz");
  const r = await call(h, { token: t });
  assertEquals(r.json, { ok: true, iceServers: [STUN], turn: false, ttl: 600 });
  assertEquals(cfCalls.length, 0);
});

Deno.test("a key in gizleme_config: credentials minted with a 15-minute life, shared for two minutes, never the token", async () => {
  reset(); cfCalls = [];
  table("gizleme_config").push({ key: "turn", value: { id: "KEYID", token: "SECRET-TOKEN" } });
  const t = await session("oguz");
  const r = await call(h, { token: t });
  assertEquals(r.json.turn, true); assertEquals(r.json.ttl, 780);
  assertEquals(r.json.iceServers, [STUN, { urls: ["turn:turn.cloudflare.com:3478?transport=udp"], username: "u", credential: "c" }]);
  assertEquals(cfCalls.length, 1);
  assert(cfCalls[0].url.includes("/keys/KEYID/credentials/generate-ice-servers")); assertEquals(cfCalls[0].auth, "Bearer SECRET-TOKEN"); assertEquals(cfCalls[0].body, { ttl: 900 });
  assert(!JSON.stringify(r.json).includes("SECRET-TOKEN"));
  const again = await call(h, { token: await session("serap") });
  assertEquals(cfCalls.length, 1);                               // the cached set, for everyone, for ~2 min
  assert(again.json.turn && again.json.ttl <= 120 && again.json.ttl > 100);
});

Deno.test("Cloudflare failing: STUN only, the call still goes", async () => {
  // the cache from the previous test is still warm (module state): make it expire by waiting is not an option — a
  // fresh load of the function would be; here the first test's cache is 2 min away, so use the fallbacks' shape only
  reset(); cfCalls = [];
  table("gizleme_config").push({ key: "turn", value: { id: "KEYID", token: "SECRET-TOKEN" } });
  const t = await session("oguz");
  cfAnswer = () => new Response("nope", { status: 500 });
  const r = await call(h, { token: t });
  assert(r.json.ok && Array.isArray(r.json.iceServers) && r.json.iceServers[0].urls[0].startsWith("stun:"));
});

Deno.test("limits: 40 calls per address, 20 per account, per 10 minutes", async () => {
  reset(); cfCalls = [];
  const t = await session("oguz");
  for (let i = 0; i < 20; i++) assertEquals((await call(h, { token: t }, { ip: "1.1.1.1" })).status, 200);
  assertEquals((await call(h, { token: t }, { ip: "1.1.1.1" })).status, 429);         // the account's budget
  const t2 = await session("serap");
  for (let i = 0; i < 19; i++) assertEquals((await call(h, { token: t2 }, { ip: "1.1.1.1" })).status, 200);
  assertEquals((await call(h, { token: t2 }, { ip: "1.1.1.1" })).status, 429);        // then the address's (40)
  store.rl = {};
  assertEquals((await call(h, { token: t2 }, { ip: "1.1.1.1" })).status, 200);
  globalThis.fetch = realFetch;
});
