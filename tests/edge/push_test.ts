// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// gizleme-push: only real push services may be endpoints; a registration is the device's whole set of keys (a key
// no longer listed is dropped); a notification wakes the other side only — never the sender's device nor the
// sender's account — with a fixed text and a url built here; dead endpoints are pruned; the buckets.
import { assert, assertEquals } from "./assert.ts";
import { call, load, reset, store, table } from "./helpers.ts";
import { dead, resetPush, sent } from "./fake_webpush.ts";

const h = await load("gizleme-push");
const sub = (ep: string) => ({ endpoint: ep, expirationTime: null, keys: { p256dh: "P".repeat(87), auth: "A".repeat(22) }, extra: "dropped" });
const APPLE = "https://web.push.apple.com/abc", FCM = "https://fcm.googleapis.com/fcm/send/xyz";

Deno.test("GET and vapid: the public key, minted once and kept", async () => {
  reset(); resetPush();
  const g = await call(h, null, { method: "GET" });
  assert(g.json.ok && g.json.publicKey.startsWith("PUB"));
  assertEquals((await call(h, { action: "vapid" })).json.publicKey, g.json.publicKey);
  assertEquals((await call(h, { action: "x" })).status, 400);
});

Deno.test("register: endpoints, shapes, the set replaces the device's previous one", async () => {
  reset(); resetPush();
  assertEquals((await call(h, { action: "register", owner: "dev1", notify_keys: ["k1"], sub: sub("https://evil.example/hook") })).json.error, "bad_endpoint");
  assertEquals((await call(h, { action: "register", owner: "dev1", notify_keys: ["k1"], sub: sub("http://web.push.apple.com/x") })).json.error, "bad_endpoint");   // https only
  assertEquals((await call(h, { action: "register", owner: "dev1", notify_keys: [], sub: sub(APPLE) })).json.error, "missing fields");
  assertEquals((await call(h, { action: "register", owner: "dev1", notify_keys: ["k1"], sub: { endpoint: APPLE, keys: { p256dh: 5 } } })).json.error, "bad_sub");
  const r = await call(h, { action: "register", owner: "dev1", acct: "ACCT1", notify_keys: ["k1", "k2", "k2"], sub: sub(APPLE) });
  assertEquals(r.json, { ok: true, registered: 2 });
  const rows = table("gizleme_push_subs");
  assertEquals(rows.map(x => x.notify_key).sort(), ["k1", "k2"]);
  assertEquals(rows[0].sub, { endpoint: APPLE, expirationTime: null, keys: { p256dh: "P".repeat(87), auth: "A".repeat(22) } });   // nothing else of the subscription is kept
  assertEquals(rows[0].acct, "ACCT1");
  const r2 = await call(h, { action: "register", owner: "dev1", acct: "ACCT1", notify_keys: ["k2", "k3"], sub: sub(FCM) });
  assertEquals(r2.json.registered, 2);
  assertEquals(table("gizleme_push_subs").map(x => x.notify_key).sort(), ["k2", "k3"]);   // k1 (a removed contact) can no longer wake dev1
  assertEquals(table("gizleme_push_subs").find(x => x.notify_key === "k2")!.sub.endpoint, FCM);
  // another device under the same key is its own row
  await call(h, { action: "register", owner: "dev2", notify_keys: ["k2"], sub: sub(APPLE) });
  assertEquals(table("gizleme_push_subs").filter(x => x.notify_key === "k2").length, 2);
  assertEquals((await call(h, { action: "unregister", owner: "dev2", notify_key: "k2" })).json, { ok: true });
  assertEquals(table("gizleme_push_subs").filter(x => x.notify_key === "k2").length, 1);
  assertEquals((await call(h, { action: "unregister", owner: "dev1" })).json, { ok: true });
  assertEquals(table("gizleme_push_subs").length, 0);
  assertEquals((await call(h, { action: "unregister" })).status, 400);
});

Deno.test("notify: the other side only, a fixed text, the url built here, dead endpoints pruned", async () => {
  reset(); resetPush();
  await call(h, { action: "register", owner: "me", acct: "A", notify_keys: ["k1"], sub: sub(APPLE) });
  await call(h, { action: "register", owner: "my-other-phone", acct: "A", notify_keys: ["k1"], sub: sub(FCM) });
  await call(h, { action: "register", owner: "her", acct: "B", notify_keys: ["k1"], sub: sub("https://updates.push.services.mozilla.com/wpush/v2/x") });
  await call(h, { action: "register", owner: "her-laptop", notify_keys: ["k1"], sub: sub("https://wns2-par02p.notify.windows.com/w/?token=x") });
  assertEquals((await call(h, { action: "notify" })).status, 400);
  const r = await call(h, { action: "notify", notify_key: "k1", from: "me", from_acct: "A", kind: "msg", tag: "t1", url: "https://gizleme.com/#i=STOLEN" });
  assertEquals(r.json, { ok: true, sent: 2, targets: 2, pruned: 0 });
  assertEquals(sent.map(s => s.sub.endpoint).sort(), ["https://updates.push.services.mozilla.com/wpush/v2/x", "https://wns2-par02p.notify.windows.com/w/?token=x"]);
  const payload = JSON.parse(sent[0].payload);
  assertEquals(payload, { title: "Gizleme", body: "New message", kind: "msg", tag: "t1", url: "https://gizleme.com/#n=k1" });   // never the request's url
  assertEquals(sent[0].opts, { TTL: 1800, urgency: "high" });
  // v42: the per-direction keys carry no sender marker — then only the device itself is excluded
  resetPush();
  const r2 = await call(h, { action: "notify", notify_key: "k1", from: "me", kind: "chat" });
  assertEquals([r2.json.sent, r2.json.targets], [3, 3]);
  assertEquals(JSON.parse(sent[0].payload).body, "A contact wants to chat");
  // a call rings with a short life; a dead endpoint is forgotten
  resetPush(); dead.add(FCM);
  const r3 = await call(h, { action: "notify", notify_key: "k1", from: "her", kind: "call" });
  assertEquals(r3.json, { ok: true, sent: 2, targets: 3, pruned: 1 });
  assertEquals(sent[0].opts.TTL, 45); assertEquals(JSON.parse(sent[0].payload).body, "Incoming call");
  assertEquals(table("gizleme_push_subs").map(x => x.owner).sort(), ["her", "her-laptop", "me"]);
  await call(h, { action: "notify", notify_key: "k1", from: "x", kind: "missed" });
  assertEquals(JSON.parse(sent[sent.length - 1].payload).body, "Missed call");
  assertEquals(JSON.parse(sent[sent.length - 1].payload).tag, "k1");   // no tag given: the key's prefix
});

Deno.test("notify: at most 8 devices per key, 12 message wakes per key per 10 min (calls 40), 120 per address", async () => {
  reset(); resetPush();
  for (let i = 0; i < 12; i++) await call(h, { action: "register", owner: "d" + i, notify_keys: ["k"], sub: sub(APPLE + i) });
  const r = await call(h, { action: "notify", notify_key: "k", from: "nobody" });
  assertEquals([r.json.sent, r.json.targets], [8, 8]);
  for (let i = 0; i < 11; i++) assertEquals((await call(h, { action: "notify", notify_key: "k", from: "nobody" })).json.limited, undefined);
  const capped = await call(h, { action: "notify", notify_key: "k", from: "nobody" });
  assertEquals(capped.json, { ok: true, sent: 0, targets: 0, limited: true });               // said, not an error: the client falls back
  for (let i = 0; i < 40; i++) assertEquals((await call(h, { action: "notify", notify_key: "k", from: "nobody", kind: "call" })).json.limited, undefined);   // its own bucket
  assertEquals((await call(h, { action: "notify", notify_key: "k", from: "nobody", kind: "call" })).json.limited, true);
  store.rl = {};
  for (let i = 0; i < 120; i++) assertEquals((await call(h, { action: "notify", notify_key: "k" + i, from: "nobody" }, { ip: "1.1.1.1" })).status, 200);
  assertEquals((await call(h, { action: "notify", notify_key: "other", from: "nobody" }, { ip: "1.1.1.1" })).status, 429);
  store.rl = {};
  for (let i = 0; i < 60; i++) assertEquals((await call(h, { action: "register", owner: "r" + i, notify_keys: ["k"], sub: sub(APPLE) }, { ip: "3.3.3.3" })).status, 200);
  assertEquals((await call(h, { action: "register", owner: "r99", notify_keys: ["k"], sub: sub(APPLE) }, { ip: "3.3.3.3" })).status, 429);
});
