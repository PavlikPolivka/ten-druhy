// Minimal service worker: makes the app installable and gives an offline notice.
// Navigations always go to the network first, so Authelia login redirects keep working;
// /api/* is never touched.
const CACHE = 'td-v1';
const SHELL = ['/static/icons/icon-192.png', '/static/icons/icon-512.png', '/static/offline.html'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/static/offline.html')));
    return;
  }
  if (url.pathname.startsWith('/static/icons/')) {
    e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
  }
});
