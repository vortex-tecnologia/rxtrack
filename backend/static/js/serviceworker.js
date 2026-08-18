// UNIFICADO: Versão v1.47
const CACHE_NAME = 'fluxo-logistica-v1.47';

const filesToCache = [
    '/app/',
    '/login/',
    '/static/css/app_v2.css',
    '/static/css/login.css',
    '/static/js/manifesto_v19.js',
    '/static/js/image_quality_v1.js',
    '/static/js/pwa_tracking.js',
    '/static/css/bootstrap.min.css',
    '/static/css/bootstrap-icons.css',
    '/static/css/fonts/bootstrap-icons.woff',
    '/static/css/fonts/bootstrap-icons.woff2',
    '/static/js/offiline.js',
    '/static/js/bootstrap.bundle.min.js',
    '/static/images/icon-160x160.png',
    '/static/images/icon-512x512.png'
];

// --- INSTALAÇÃO ---
self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('✅ Cache instalado: ', CACHE_NAME);
            return cache.addAll(filesToCache);
        })
    );
});

// --- ATIVAÇÃO ---
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('🗑️ Removendo cache antigo:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    return self.clients.claim();
});

// --- BUSCA (FETCH) ---

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // ⛔ REGRA 0: IGNORAR ROTAS DO PAINEL ADMINISTRATIVO E OPERACIONAL
    if (
        url.pathname.startsWith('/admin') ||
        url.pathname.startsWith('/gestao') ||
        url.pathname.startsWith('/suporte') ||
        url.pathname.startsWith('/static/admin/') ||
        url.pathname === '/'
    ) {
        return; // Retorna imediatamente e repassa nativamente para a rede
    }

    // ⛔ REGRA 1: Ignora requisições de LOGIN ou envio de dados (POST, PUT, DELETE)
    // O Service Worker não deve tentar cachear o corpo de um POST.
    if (event.request.method !== 'GET') {
        return;
    }

    // 2. APIs e DADOS DINÂMICOS: Rede Primeiro (Network First)
    if (url.pathname.includes('/api/') || url.pathname.includes('/status/')) {
        event.respondWith(
            fetch(event.request).catch(() => caches.match(event.request))
        );
        return;
    }

    // 3. LAYOUT E ESTRUTURA: Stale-While-Revalidate (Cache-First com Update em silêncio)
    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            const fetchPromise = fetch(event.request).then((networkResponse) => {

                // ✅ Verificação robusta antes de clonar
                if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
                    return networkResponse;
                }

                // Clona para o cache
                const responseToCache = networkResponse.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, responseToCache);
                });

                return networkResponse;
            }).catch(() => {
                // Silencia erros de rede para não travar o console
            });

            return cachedResponse || fetchPromise;
        })
    );
});

// --- NOTIFICAÇÕES (PUSH) ---
self.addEventListener('push', function (event) {
    let data = {};
    if (event.data) { try { data = event.data.json(); } catch (e) { data.body = event.data.text(); } }

    const options = {
        body: data.body || 'Nova atualização no sistema',
        icon: data.icon || '/static/images/icon-160x160.png',
        badge: '/static/images/icon-160x160.png',
        vibrate: [200, 100, 200],
        data: { url: data.url || '/app/' },
        requireInteraction: true
    };

    event.waitUntil(
        self.registration.showNotification(data.title || 'RXTrack', options)
    );
});

// --- CLIQUE NOTIFICAÇÃO ---
self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    const urlToOpen = event.notification.data.url || '/app/';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(function (clientList) {
                for (let client of clientList) {
                    if (client.url.includes('/app/') && 'focus' in client) {
                        return client.focus();
                    }
                }
                if (clients.openWindow) { return clients.openWindow(urlToOpen); }
            })
    );
});