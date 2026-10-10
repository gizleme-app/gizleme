// Minimal service worker — enables installability. Network-first, no stale caching
// of the app shell (the app must always load the latest encrypted build).
const CACHE = "gizleme-v1";
self.addEventListener("install", e => { self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  e.respondWith(
    fetch(req).catch(() => caches.match(req))
  );
});
