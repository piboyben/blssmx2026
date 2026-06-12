
const CACHE_NAME = 'bayune-maths-v1';
const ASSETS = [
  '/',
  '/manifest.json',
  '/static/manifest.json',
  '/static/sw.js'
];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => 
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;

  // Never cache HTML pages, login, logout, or API routes
  const isHtml = e.request.headers.get('accept')?.includes('text/html');
  const isAuthOrApi = e.request.url.includes('/login') || e.request.url.includes('/logout') || e.request.url.includes('/api/');
  
  if (isHtml || isAuthOrApi) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Cache everything else (CSS, JS, images, fonts)
  e.respondWith(
    caches.match(e.request).then(res => 
      res || fetch(e.request).then(networkRes => {
        if (networkRes && networkRes.status === 200) {
          const clone = networkRes.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
        }
        return networkRes;
      }).catch(() => caches.match('/'))
    ).catch(() => caches.match('/'))
  );
});
