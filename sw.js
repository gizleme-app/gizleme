// Service worker — installability + Web Push. Network-first, no stale caching of
// the app shell (the app must always load the latest encrypted build).
const CACHE = "gizleme-v2";
self.addEventListener("install", e => { self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  e.respondWith(fetch(req).catch(() => caches.match(req)));
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
