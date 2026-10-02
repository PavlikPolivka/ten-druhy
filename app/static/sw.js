// Minimal service worker: makes the app installable and gives an offline notice.
// Navigations always go to the network first, so Authelia login redirects keep working;
// /api/* is never touched.
const CACHE = 'td-v2';
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

// Proactive check-ins: show the notification; tapping it opens (or focuses) the app on that conversation.
self.addEventListener('push', e => {
  let d = { title: 'Ten druhý', body: '', url: '/' };
  try { d = Object.assign(d, e.data.json()); } catch (err) { if (e.data) d.body = e.data.text(); }
  e.waitUntil(self.registration.showNotification(d.title, {
    body: d.body, icon: '/static/icons/icon-192.png', badge: '/static/icons/icon-192.png', data: { url: d.url }, tag: 'td-checkin',
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    for (const c of list) if ('focus' in c) { c.navigate(url); return c.focus(); }
    return self.clients.openWindow(url);
  }));
});
