// Service Worker do SAC - Focado em sempre estar Online (Network-First)
const CACHE_NAME = 'sac-cache-v1.0';

self.addEventListener('install', (event) => {
    self.skipWaiting();
    console.log('✅ Service Worker SAC instalado.');
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    return self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    // Apenas requisições GET.
    if (event.request.method !== 'GET') return;
    
    // Ignora rotas que não pertencem ao SAC e API/Websockets
    const url = new URL(event.request.url);
    if (url.pathname.startsWith('/admin') || url.pathname.startsWith('/api') || url.pathname.includes('/ws/')) {
        return;
    }

    // Estratégia Network-First: Tenta a rede, se falhar (offline), busca no cache.
    event.respondWith(
        fetch(event.request)
            .then(networkResponse => {
                // Guarda no cache o que conseguiu na rede
                const responseClone = networkResponse.clone();
                caches.open(CACHE_NAME).then(cache => {
                    cache.put(event.request, responseClone);
                });
                return networkResponse;
            })
            .catch(() => {
                return caches.match(event.request);
            })
    );
});
