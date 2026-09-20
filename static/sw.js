/* PROTrader service worker.
   Caches the app shell (page + chart library + icons) so the terminal opens
   instantly and even offline; market data always goes to the network.
   Bump CACHE_VERSION whenever the shell changes to evict the old copy. */
const CACHE_VERSION = 'protrader-shell-v9';
const VENDOR = '/vendor/lightweight-charts.standalone.production.js?v=5.0.9';
const SHELL = ['/', '/mobile', VENDOR, '/static/manifest.webmanifest', '/static/icon-192.png', '/static/icon-512.png'];

self.addEventListener('install', e => {
  // cache:'reload' bypasses the HTTP cache so a version bump really refetches.
  e.waitUntil(caches.open(CACHE_VERSION)
    .then(c => c.addAll(SHELL.map(u => new Request(u, { cache: 'reload' }))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const isShell = url => url.pathname === '/' || url.pathname === '/mobile'
  || url.pathname.startsWith('/vendor/') || url.pathname.startsWith('/static/');

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;            // live data: network only
  if (!isShell(url) && e.request.mode !== 'navigate') return;

  // Shell: answer from cache immediately (instant launch, even when the
  // host is asleep or the network is poor) and revalidate in the background
  // so the next open has the latest deploy.
  e.respondWith((async () => {
    const cache = await caches.open(CACHE_VERSION);
    const key = e.request.mode === 'navigate' ? new Request(url.pathname) : e.request;
    const cached = await cache.match(key, { ignoreSearch: false });
    const refresh = fetch(e.request, { cache: 'no-cache' }).then(res => {
      if (res && res.ok) cache.put(key, res.clone());
      return res;
    }).catch(() => null);
    if (cached) { e.waitUntil(refresh); return cached; }
    const live = await refresh;
    if (live) return live;
    // nothing cached and offline: fall back to the app page for navigations
    const fallback = e.request.mode === 'navigate' ? await cache.match('/') : null;
    return fallback || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
  })());
});
