// Service Worker for SimplePWA
const CACHE_NAME = 'SimplePWA-v1';
const FILES_TO_CACHE = [
  'index.html',
  'app.js'
];

// Install event: cache essential files
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(FILES_TO_CACHE))
      .then(() => self.skipWaiting())
  );
});

// Activate event: clean up old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(cacheNames => Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      ))
      .then(() => self.clients.claim())
  );
});

// Fetch event: serve cached files when offline
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => response || fetch(event.request))
  );
});

// Background sync or alarm handling
self.addEventListener('sync', event => {
  if (event.tag === 'alarm-sync') {
    // Handle alarm-related background tasks
    // Ensure alarms work reliably even in silent mode
    event.waitUntil(
      // Custom logic to trigger alarms or notifications
    );
  }
});

// Optional: listen to push notifications or messages for alarms
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'TRIGGER_ALARM') {
    // Logic to trigger alarms/notifications in silent mode
    self.registration.showNotification('Alarm', {
      body: 'Your alarm is ringing!',
      silent: false
    });
  }
});
