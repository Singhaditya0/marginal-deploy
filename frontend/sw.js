// sw.js — Marginal's service worker.
// Purpose: makes the site "installable" (a real requirement for the
// browser's install/download prompt) and lets the app shell load
// instantly on repeat visits. API calls always go to the network —
// documents and answers should never come from a stale cache.

const CACHE_NAME = "marginal-shell-v1";
const SHELL_ASSETS = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls — always hit the network so uploads, summaries,
  // and answers stay current and session-specific.
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  // App shell: cache-first, falling back to network, and updating the
  // cache in the background so the next load picks up any changes.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request)
        .then((response) => {
          if (response && response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
