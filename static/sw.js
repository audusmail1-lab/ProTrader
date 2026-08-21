/* PROTrader service worker.
   Caches the app shell (page + chart library + icons) so the terminal opens
   instantly and even offline; market data always goes to the network.
   Bump CACHE_VERSION whenever the shell changes to evict the old copy. */
const CACHE_VERSION = 'protrader-shell-v1';
const SHELL = [
  '/mobile',
  '/vendor/lightweight-charts.standalone.production.js',
  '/static/manifest.webmanifest',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;

  // Live data and streams: network only, never cached.
  if (url.pathname.startsWith('/api/')) return;

  // Shell: network first so a deploy shows up on the next open, cache as
  // the fallback when offline.
  e.respondWith(
    fetch(e.request).then(res => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE_VERSION).then(c => c.put(e.request, copy));
      }
      return res;
    }).catch(() => caches.match(e.request))
  );
});
