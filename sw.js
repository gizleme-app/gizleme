// Service worker — installability, offline shell, Web Push.
// Network-first for everything (the app must always load the latest encrypted build); the precached
// shell is only served when the network fails, so the installed app opens offline instead of erroring.
const CACHE = "gizleme-v3";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/watermark.png", "/watermark-eyes.png",
               "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;          // let the CDN / Supabase requests pass straight through
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

// A push wakes the device even when the app is closed, and shows a notification.
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { try { d = { body: e.data.text() }; } catch (__) { d = {}; } }
  const title = d.title || "Gizleme";
  e.waitUntil(self.registration.showNotification(title, {
    body: d.body || "A contact wants to chat",
    tag: d.tag || "gizleme",
    renotify: true,
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: d.url || "https://gizleme.com" },
  }));
});

// Tapping the notification focuses an open tab or opens the app.
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "https://gizleme.com";
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if ("focus" in c) { try { await c.focus(); if ("navigate" in c) { try { await c.navigate(url); } catch (_) {} } return; } catch (_) {} }
    }
    if (self.clients.openWindow) return self.clients.openWindow(url);
  })());
});
