// Service Worker — PWA install + offline shell caching + FCM push notifications

// ─── Firebase Messaging (compat SDK for SW context) ───
importScripts('https://www.gstatic.com/firebasejs/11.6.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/11.6.0/firebase-messaging-compat.js');

firebase.initializeApp({
    apiKey: "AIzaSyCvH1nqbrIeakI5P5AuGTuEgDtL3SV_kNo",
    authDomain: "sourdough-monitor-app.firebaseapp.com",
    projectId: "sourdough-monitor-app",
    storageBucket: "sourdough-monitor-app.firebasestorage.app",
    messagingSenderId: "231699057388",
    appId: "1:231699057388:web:7685b1795464dc4cc173c9"
});

const messaging = firebase.messaging();

// Handle background push (app closed or in background)
messaging.onBackgroundMessage((payload) => {
    const { title, body } = payload.notification || {};
    if (title) {
        self.registration.showNotification(title, {
            body: body || '',
            icon: '/icons/icon-192.png',
            badge: '/icons/icon-192.png',
        });
    }
});

// ─── Cache config ───
const CACHE_NAME = 'sourdough-v6';
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

// Notification click: open/focus the app
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          return client.focus();
        }
      }
      return clients.openWindow('/');
    })
  );
});
