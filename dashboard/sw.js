// Service Worker для Life Dashboard.
// Цель: дашборд должен открываться даже без интернета (последний кэш статики)
// и переживать кратковременные сбои сети для gviz CSV / Open-Meteo.
//
// Стратегии:
//   - HTML / манифест / иконка / sw.js / index.html → cache-first (быстрый старт).
//   - gviz CSV (docs.google.com) → network-first, fallback в кэш.
//   - Open-Meteo → network-first, fallback в кэш.
//   - Всё остальное (favicon, manifest, ассеты) → cache-first.
//
// При выходе новой версии меняй CACHE_NAME — старые кэши будут удалены при
// активации нового SW.

const CACHE_NAME = "life-dashboard-v7";
const CORE_ASSETS = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icon.svg",
];

// --- INSTALL: предкэшируем статику ---------------------------------------
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

// --- ACTIVATE: чистим старые кэши ----------------------------------------
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// --- FETCH: маршрутизация по доменам -------------------------------------
self.addEventListener("fetch", (event) => {
  // Не трогаем не-GET запросы (безопасный дефолт).
  if (event.request.method !== "GET") return;

  const url = new URL(event.request.url);

  // gviz CSV из Google Sheets — network-first, кэшируем последний удачный ответ
  if (url.hostname === "docs.google.com" && url.pathname.includes("/gviz/")) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Open-Meteo — network-first
  if (url.hostname === "api.open-meteo.com") {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Локальные ассеты — cache-first
  if (url.origin === self.location.origin) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // Всё остальное — оставляем как есть (default browser fetch)
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) {
      cache.put(request, fresh.clone());
    }
    return fresh;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) {
    // Параллельно обновляем кэш в фоне (stale-while-revalidate light)
    fetch(request).then((res) => {
      if (res && res.ok) cache.put(request, res.clone());
    }).catch(() => {});
    return cached;
  }
  const fresh = await fetch(request);
  if (fresh && fresh.ok) cache.put(request, fresh.clone());
  return fresh;
}
