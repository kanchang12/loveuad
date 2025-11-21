// This is the "Offline page" service worker

importScripts('https://storage.googleapis.com/workbox-cdn/releases/5.1.2/workbox-sw.js');

const CACHE = "pwabuilder-page";

// TODO: replace the following with the correct offline fallback page i.e.: const offlineFallbackPage = "offline.html";
const offlineFallbackPage = "ToDo-replace-this-name.html";

// MODIFIED: This listener now also handles messages for showing local 'alarm' notifications.
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  } else if (event.data && event.data.type === 'SHOW_ALARM_NOTIFICATION') {
    // Handles local 'alarm' notifications triggered from the main app thread
    const { title, options } = event.data.payload;
    event.waitUntil(
      self.registration.showNotification(title, options)
    );
  }
});

self.addEventListener('install', async (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.add(offlineFallbackPage))
  );
});

if (workbox.navigationPreload.isSupported()) {
  workbox.navigationPreload.enable();
}

self.addEventListener('fetch', (event) => {
  if (event.request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const preloadResp = await event.preloadResponse;

        if (preloadResp) {
          return preloadResp;
        }

        const networkResp = await fetch(event.request);
        return networkResp;
      } catch (error) {

        const cache = await caches.open(CACHE);
        const cachedResp = await cache.match(offlineFallbackPage);
        return cachedResp;
      }
    })());
  }
});

// =========================================================================================================
// NEW: Handlers for push notifications (server-sent) and user clicks
// =========================================================================================================

// 1. Listen for 'push' events (Server-Sent Push Notifications)
self.addEventListener('push', (event) => {
  const title = 'PWA Notification';
  const iconUrl = '/images/icon-192x192.png'; // IMPORTANT: Update to a real icon path from your project

  let options = {
    body: 'You have a new update from the app.',
    icon: iconUrl,
    badge: iconUrl,
    vibrate: [200, 100, 200],
    data: {
      url: '/' // Default URL to open on click
    }
  };

  // If the server sent a payload, use it
  if (event.data) {
    try {
      const data = event.data.json();
      options.body = data.body || options.body;
      options.title = data.title || title;
      options.data.url = data.url || options.data.url;
    } catch (e) {
      options.body = event.data.text() || options.body;
    }
  }

  // The event.waitUntil ensures the service worker stays alive until the notification is shown
  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

// 2. Listen for 'notificationclick' events (User taps the notification)
self.addEventListener('notificationclick', (event) => {
  event.notification.close(); // Close the notification banner

  const urlToOpen = event.notification.data.url || '/';

  // This handles opening a new window or focusing an existing one
  event.waitUntil(
    clients.matchAll({
      type: 'window'
    })
    .then((clientList) => {
      // Look for an existing client (tab/window) to focus
      for (const client of clientList) {
        // If a client's URL contains the target URL, focus it
        if (client.url.includes(urlToOpen) && 'focus' in client) {
          return client.focus();
        }
      }
      // If no matching tab is found, open a new one
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});
