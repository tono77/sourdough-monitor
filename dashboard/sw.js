// Service Worker — enables PWA install + offline shell caching
const CACHE_NAME = 'sourdough-v5';
const SHELL_ASSETS = [
  '/',
  '/index.html',
  '/css/main.css',
  '/css/charts.css',
  '/css/lightbox.css',
  '/js/app.js',
  '/js/charts.js',
  '/js/gallery.js',
  '/js/calibration.js',
  '/js/utils.js',
  '/js/measurement-detail.js',
  '/manifest.json',
];

// Install: cache shell assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Activate: clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch: network-first for API/Firebase, cache-first for shell assets
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Skip non-GET and cross-origin API requests (Firebase, Google, etc.)
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached => {
      const fetching = fetch(event.request).then(response => {
        // Update cache with fresh version
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => cached); // Offline fallback to cache

      return cached || fetching;
    })
  );
});
