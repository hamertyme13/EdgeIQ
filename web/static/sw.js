const CACHE_NAME = "edgeiq-shell-20260811-v230-evidence";
const SHELL_ASSETS = [
  "/",
  "/static/index.html",
  "/static/styles.css",
  "/static/app.js",
  "/static/circuit-audio.js",
  "/static/ui-shell.js",
  "/static/ui-utils.js",
  "/static/edgeiq-icon.png",
  "/static/manifest.webmanifest"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS.map((asset) => new Request(asset, { cache: "reload" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return;
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(new Request(event.request, { cache: "no-store" }))
        .catch(() => caches.match("/static/index.html"))
    );
    return;
  }
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request).then((cached) => cached || caches.match("/")))
  );
});
