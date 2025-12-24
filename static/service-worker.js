// LoveUAD Service Worker v2.0.0
const CACHE_VERSION = 'loveuad-v2';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const DYNAMIC_CACHE = `${CACHE_VERSION}-dynamic`;
const API_CACHE = `${CACHE_VERSION}-api`;

// Files to cache immediately on install
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  // Add other critical static assets
];

// ==================== INSTALL ====================
self.addEventListener('install', event => {
  console.log('[SW] Installing service worker...');
  
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => {
        console.log('[SW] Caching static assets');
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => {
        console.log('[SW] Static assets cached');
        return self.skipWaiting(); // Activate immediately
      })
      .catch(error => {
        console.error('[SW] Installation failed:', error);
      })
  );
});

// ==================== ACTIVATE ====================
self.addEventListener('activate', event => {
  console.log('[SW] Activating service worker...');
  
  event.waitUntil(
    Promise.all([
      // Clean up old caches
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames
            .filter(name => name.startsWith('loveuad-') && name !== STATIC_CACHE && name !== DYNAMIC_CACHE && name !== API_CACHE)
            .map(name => {
              console.log('[SW] Deleting old cache:', name);
              return caches.delete(name);
            })
        );
      }),
      // Take control of all pages immediately
      self.clients.claim()
    ])
  );
});

// ==================== FETCH ====================
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);
  
  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }
  
  // API requests - Network first, cache fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirstStrategy(request, API_CACHE));
    return;
  }
  
  // Static assets - Cache first, network fallback
  if (url.pathname.startsWith('/static/') || STATIC_ASSETS.includes(url.pathname)) {
    event.respondWith(cacheFirstStrategy(request, STATIC_CACHE));
    return;
  }
  
  // HTML pages - Network first, cache fallback
  if (request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(networkFirstStrategy(request, DYNAMIC_CACHE));
    return;
  }
  
  // Default: Network first
  event.respondWith(networkFirstStrategy(request, DYNAMIC_CACHE));
});

// ==================== CACHING STRATEGIES ====================

async function cacheFirstStrategy(request, cacheName) {
  try {
    const cachedResponse = await caches.match(request);
    
    if (cachedResponse) {
      // Return cached version
      console.log('[SW] Cache hit:', request.url);
      
      // Update cache in background
      fetch(request)
        .then(response => {
          if (response.ok) {
            return caches.open(cacheName).then(cache => cache.put(request, response));
          }
        })
        .catch(() => {}); // Ignore background update errors
      
      return cachedResponse;
    }
    
    // Not in cache - fetch from network
    console.log('[SW] Cache miss, fetching:', request.url);
    const networkResponse = await fetch(request);
    
    if (networkResponse.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, networkResponse.clone());
    }
    
    return networkResponse;
  } catch (error) {
    console.error('[SW] Cache-first strategy failed:', error);
    return createErrorResponse('Offline - content unavailable');
  }
}

async function networkFirstStrategy(request, cacheName) {
  try {
    // Try network first
    const networkResponse = await fetch(request);
    
    if (networkResponse.ok) {
      // Cache successful responses
      const cache = await caches.open(cacheName);
      cache.put(request, networkResponse.clone());
    }
    
    return networkResponse;
  } catch (error) {
    // Network failed - try cache
    console.log('[SW] Network failed, trying cache:', request.url);
    const cachedResponse = await caches.match(request);
    
    if (cachedResponse) {
      return cachedResponse;
    }
    
    // No cache available
    return createErrorResponse('Offline - cannot connect to server');
  }
}

function createErrorResponse(message) {
  return new Response(
    JSON.stringify({ error: message, offline: true }),
    {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    }
  );
}

// ==================== PUSH NOTIFICATIONS ====================

self.addEventListener('push', event => {
  console.log('[SW] Push notification received');
  
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = { title: 'LoveUAD', body: event.data.text() };
    }
  }
  
  const title = data.title || 'Medication Reminder';
  const options = {
    body: data.body || 'Time to take your medication',
    icon: '/static/icon-192.png',
    badge: '/static/badge-72.png',
    vibrate: [300, 100, 300, 100, 300], // Strong vibration pattern
    tag: data.tag || `medication-${Date.now()}`,
    requireInteraction: true, // Keep notification until user interacts
    actions: [
      {
        action: 'taken',
        title: '✓ Mark as Taken',
        icon: '/static/check-icon.png'
      },
      {
        action: 'snooze',
        title: '⏰ Snooze 15 min',
        icon: '/static/snooze-icon.png'
      }
    ],
    data: {
      medicationId: data.medicationId,
      medicationName: data.medicationName,
      scheduledTime: data.scheduledTime,
      timestamp: Date.now(),
      url: data.url || '/'
    }
  };
  
  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

// ==================== NOTIFICATION CLICK ====================

self.addEventListener('notificationclick', event => {
  console.log('[SW] Notification clicked:', event.action);
  
  event.notification.close();
  
  const data = event.notification.data;
  
  if (event.action === 'taken') {
    // Mark medication as taken
    event.waitUntil(
      fetch('/api/health/medication-taken', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          medicationName: data.medicationName,
          scheduledTime: data.scheduledTime,
          takenAt: new Date().toISOString()
        })
      })
      .then(response => {
        console.log('[SW] Medication marked as taken');
        // Show confirmation notification
        return self.registration.showNotification('✓ Medication Taken', {
          body: `${data.medicationName} recorded`,
          icon: '/static/icon-192.png',
          tag: 'medication-confirmation'
        });
      })
      .catch(error => {
        console.error('[SW] Failed to mark medication:', error);
      })
    );
  } else if (event.action === 'snooze') {
    // Snooze notification
    event.waitUntil(
      new Promise(resolve => {
        setTimeout(() => {
          self.registration.showNotification(event.notification.title, {
            body: `Snoozed: ${data.medicationName}`,
            icon: '/static/icon-192.png',
            badge: '/static/badge-72.png',
            vibrate: [300, 100, 300, 100, 300],
            tag: data.tag,
            requireInteraction: true,
            data: data
          });
          resolve();
        }, 15 * 60 * 1000); // 15 minutes
      })
    );
  } else {
    // Default action - open app
    event.waitUntil(
      clients.openWindow(data.url || '/')
    );
  }
});

// ==================== BACKGROUND SYNC ====================

self.addEventListener('sync', event => {
  console.log('[SW] Background sync triggered:', event.tag);
  
  if (event.tag === 'sync-medications') {
    event.waitUntil(syncPendingMedications());
  }
});

async function syncPendingMedications() {
  try {
    // Get pending medication logs from IndexedDB or cache
    const cache = await caches.open(API_CACHE);
    const requests = await cache.keys();
    
    const pendingSync = requests.filter(req => 
      req.url.includes('/api/medications/pending') ||
      req.url.includes('/api/health/medication-taken')
    );
    
    for (const request of pendingSync) {
      try {
        await fetch(request);
        await cache.delete(request);
        console.log('[SW] Synced:', request.url);
      } catch (error) {
        console.error('[SW] Sync failed:', request.url, error);
      }
    }
    
    console.log('[SW] Background sync completed');
  } catch (error) {
    console.error('[SW] Background sync error:', error);
    throw error; // Retry sync
  }
}

// ==================== MESSAGE HANDLING ====================

self.addEventListener('message', event => {
  console.log('[SW] Message received:', event.data);
  
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  
  if (event.data && event.data.type === 'CLEAR_CACHE') {
    event.waitUntil(
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames.map(cache => caches.delete(cache))
        );
      })
    );
  }
  
  if (event.data && event.data.type === 'CACHE_URLS') {
    const urls = event.data.urls || [];
    event.waitUntil(
      caches.open(DYNAMIC_CACHE).then(cache => {
        return cache.addAll(urls);
      })
    );
  }
});

console.log('[SW] Service worker loaded');
