// Gizleme — end-to-end encrypted messaging in the browser. https://gizleme.com
// Copyright (C) 2026 Oğuz Seran
// SPDX-License-Identifier: AGPL-3.0-only
// This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero
// General Public License as published by the Free Software Foundation, version 3. It is distributed WITHOUT
// ANY WARRANTY; see the LICENSE file for details.
// Service worker — installability, offline shell, Web Push.
// Network-first for everything (the app must always load the latest encrypted build); the precached
// shell is only served when the network fails, so the installed app opens offline instead of erroring.
const CACHE = "gizleme-v27";
const SHELL = ["/", "/index.html", "/app.js", "/i18n.js", "/vendor/supabase-2.117.2.js", "/vendor/qrcode-1.4.4.js", "/manifest.webmanifest",
               "/watermark.png", "/watermark-eyes.png", "/logo-head.png", "/logo-word.png", "/logo-dot.png", "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE && k !== "gizleme-meta").map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;          // Supabase requests pass straight through
  e.respondWith((async () => {
    try {
      const res = await fetch(req);
      if (res && res.ok && (req.mode === "navigate" || SHELL.includes(url.pathname))) {
        try { const c = await caches.open(CACHE); c.put(req.mode === "navigate" ? "/index.html" : req, res.clone()); } catch (_) {}
      }
      return res;
    } catch (_) {
      const cached = await caches.match(req.mode === "navigate" ? "/index.html" : req);
      return cached || Response.error();
    }
  })());
});

// A notification may only ever open Gizleme itself: whatever a payload says, the target is forced to
// this origin (defence in depth — the push function already pins it server-side).
function safeTarget(u) {
  try { const x = new URL(u || "/", self.location.origin); if (x.origin === self.location.origin) return x.href; } catch (_) {}
  return self.location.origin + "/";
}

// The page sends the names it uses for contacts (nicknames first), until when a muted chat stays quiet, and
// sentence templates in its language; kept in a small cache entry so a push can use them even after the worker
// was restarted. Names and times only. It also sends the unread count, so a push can add one to the app icon.
const META = "gizleme-meta";
const JSONH = { headers: { "Content-Type": "application/json" } };
self.addEventListener("message", e => {
  const m = e.data || {};
  if (m.type === "badge") { e.waitUntil(badgeStore(Math.max(0, Math.floor(+m.n || 0)))); return; }
  if (m.type !== "names") return;
  e.waitUntil(caches.open(META).then(c => c.put("/names.json", new Response(JSON.stringify({ names: m.names || {}, muted: m.muted || {}, tmpl: m.tmpl || {} }), JSONH))));
});
async function loadNames() {
  try { const c = await caches.open(META); const r = await c.match("/names.json"); return r ? await r.json() : null; } catch (_) { return null; }
}
async function badgeStore(n) { try { const c = await caches.open(META); await c.put("/badge.json", new Response(JSON.stringify({ n }), JSONH)); } catch (_) {} }
async function badgeLoad() { try { const c = await caches.open(META); const r = await c.match("/badge.json"); return r ? (+(await r.json()).n || 0) : 0; } catch (_) { return 0; } }
function pushNk(d) { try { const u = new URL(d.url || "", self.location.origin); const h = (u.hash || "").replace(/^#/, ""); if (h.indexOf("n=") === 0) return decodeURIComponent(h.slice(2)); } catch (_) {} return ""; }
// a muted chat: its message (and "wants to chat") notifications arrive without sound or vibration; calls ring
async function mutedPush(d, meta) {
  if (d.kind === "call" || !meta || !meta.muted) return false;
  const nk = pushNk(d); if (!nk) return false;
  try { const u = +meta.muted[await nkHash(nk)] || 0; return u > Date.now(); } catch (_) { return false; }
}
// "New message from Baba" rather than the sender's own name and language: compose the text here when the
// contact is known; otherwise keep what the sender wrote.
async function nkHash(nk) { const b = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(nk)));
  return btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
async function composeBody(d, meta) {
  const fallback = String(d.body || "A contact wants to chat").slice(0, 140);
  if (!meta || !meta.tmpl) return fallback;
  const nk = pushNk(d);
  const kind = d.kind === "chat" ? "chat" : d.kind === "call" ? "call" : "msg";
  let name = ""; if (nk && meta.names) { try { name = meta.names[await nkHash(nk)] || ""; } catch (_) { name = ""; } }
  const t = meta.tmpl;
  const tpl = kind === "chat" ? t.chat : kind === "call" ? t.call : t.msg;
  if (name && tpl) return String(tpl).replace("{name}", name).slice(0, 140);
  if (name) return String("{name}").replace("{name}", name).slice(0, 140);
  if (!nk) return fallback;
  const any = kind === "chat" ? t.anyChat : kind === "call" ? t.anyCall : t.anyMsg;
  return String(any || fallback).slice(0, 140);
}
self.__composeBody = composeBody;   // exposed for tests

// A push wakes the device even when the app is closed, and shows a notification.
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { try { d = { body: e.data.text() }; } catch (__) { d = {}; } }
  e.waitUntil((async () => {
    const meta = await loadNames();
    const quiet = await mutedPush(d, meta);
    if (!quiet && d.kind !== "call" && d.kind !== "chat") {          // one more unread message on the app icon
      const n = (await badgeLoad()) + 1; await badgeStore(n);
      try { if (self.navigator.setAppBadge) await self.navigator.setAppBadge(n); } catch (_) {}
    }
    return self.registration.showNotification("Gizleme", {
      body: await composeBody(d, meta),
      tag: String(d.tag || "gizleme").slice(0, 64),
      renotify: !quiet,
      silent: quiet,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: safeTarget(d.url) },
    });
  })());
});

// Tapping the notification focuses an open tab or opens the app.
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = safeTarget(e.notification.data && e.notification.data.url);
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if ("focus" in c) { try { await c.focus(); if ("navigate" in c) { try { await c.navigate(url); } catch (_) {} } return; } catch (_) {} }
    }
    if (self.clients.openWindow) return self.clients.openWindow(url);
  })());
});
