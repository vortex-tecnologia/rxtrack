/**
 * pwa_tracking.js - Lógica isolada de rastreamento (Heartbeat)
 * Responsável por coletar GPS, bateria e sinal e enviar via WebSocket ou REST API.
 * 
 * MODO AGRESSIVO (estilo Uber/iFood/Waze):
 * - No APK: Foreground Service nativo + loop de 30s que NUNCA para em background
 * - No PWA: setInterval de 30s (funciona enquanto a aba estiver aberta)
 */

if (typeof heartbeatInterval === 'undefined') {
    window.heartbeatInterval = null;
}
if (typeof socketTracking === 'undefined') {
    window.socketTracking = null;
}
if (typeof capacitorWatcherId === 'undefined') {
    window.capacitorWatcherId = null;
}
// Timer agressivo de 30s que roda JUNTO com o watcher nativo
if (typeof nativeHeartbeatTimer === 'undefined') {
    window.nativeHeartbeatTimer = null;
}
// Cache da última posição recebida pelo GPS nativo
if (typeof ultimaPosicaoNativa === 'undefined') {
    window.ultimaPosicaoNativa = null;
}

async function iniciarCoracaoTracking() {
    // ═══════════════════════════════════════════════════════════
    // COMUNICAÇÃO COM O IFRAME (NATIVO)
    // ═══════════════════════════════════════════════════════════
    if (window.parent !== window) {
        if (!capacitorWatcherId && typeof manifestoAtual !== 'undefined' && manifestoAtual) {
            console.log("🔥 [GPS Nativo] Enviando comando para o App Nativo (Iframe Pai)...");
            window.parent.postMessage({
                type: 'START_NATIVE_GPS',
                payload: {
                    manifesto: manifestoAtual,
                    baseUrl: window.API_BASE.replace('api/', '')
                }
            }, '*');
            capacitorWatcherId = "iframe_mode";
            
            // Fallback: garante envio pela própria janela caso falhe o nativo
            if (!nativeHeartbeatTimer) {
                nativeHeartbeatTimer = setInterval(() => { enviarHeartbeat(); }, 30000);
            }
        }
    } else {
        // ═══════════════════════════════════════════════════════════
        // MODO PWA (Navegador Desktop/Web)
        // ═══════════════════════════════════════════════════════════
        if (!heartbeatInterval && typeof manifestoAtual !== 'undefined' && manifestoAtual) {
            console.log("💓 [PWA Tracking] Iniciando fallback JS");
            heartbeatInterval = setInterval(enviarHeartbeat, 30000);
            enviarHeartbeat(); // Primeiro imediato
        }
    }

    // ═══════════════════════════════════════════════════════════
    // REST API - O envio agora é 100% via REST authFetch
    // ═══════════════════════════════════════════════════════════
    // WebSocket foi removido para evitar problemas com Tenant Middleware em background
}

/**
 * Para completamente o rastreamento nativo (chamado quando manifesto finaliza)
 */
function pararTrackingNativo() {
    console.log("🛑 [GPS Nativo] Parando rastreamento...");
    
    // Parar o Motor Java Nativo (Nova Arquitetura)
    if (window.parent !== window) {
        window.parent.postMessage({ type: 'STOP_NATIVE_GPS' }, '*');
    }

    if (window.Capacitor) {
        let bgGeo = null;
        if (window.Capacitor.registerPlugin) {
            try { bgGeo = window.Capacitor.registerPlugin("BackgroundGeolocation"); } catch(e) {}
        }
        if (!bgGeo && window.Capacitor.Plugins) {
            bgGeo = window.Capacitor.Plugins.BackgroundGeolocation;
        }
        if (bgGeo && capacitorWatcherId) {
            bgGeo.removeWatcher({ id: capacitorWatcherId });
            capacitorWatcherId = null;
        }
    }
    if (nativeHeartbeatTimer) {
        clearInterval(nativeHeartbeatTimer);
        nativeHeartbeatTimer = null;
    }
    window.ultimaPosicaoNativa = null;
}

async function enviarHeartbeat(overrideLat = null, overrideLng = null) {
    // Auto-limpeza caso o manifesto seja finalizado ou limpo
    if (typeof manifestoAtual === 'undefined' || !manifestoAtual) {
        console.log("💓 [PWA Tracking] Sem manifesto ativo. Parando heartbeat.");
        if (heartbeatInterval) {
            clearInterval(heartbeatInterval);
            heartbeatInterval = null;
        }
        pararTrackingNativo();
        return;
    }

    try {
        let lat = overrideLat;
        let lng = overrideLng;

        if (lat === null || lng === null) {
            console.log("💓 [PWA Tracking] Obtendo localização via navegador...");
            const coords = await getCoords();
            lat = coords ? coords.lat : null;
            lng = coords ? coords.lon : null;
        }

        let batteryLevel = null;
        let isCharging = false;
        if ('getBattery' in navigator) {
            try {
                const battery = await navigator.getBattery();
                batteryLevel = Math.round(battery.level * 100);
                isCharging = battery.charging;
            } catch (e) {}
        }

        let connectionType = 'unknown';
        if (navigator.connection) {
            connectionType = navigator.connection.effectiveType || navigator.connection.type || 'conectado';
        } else if (navigator.onLine) {
            connectionType = 'online';
        }

        const payload = {
            type: 'heartbeat',
            lat: lat,
            lng: lng,
            battery: batteryLevel,
            is_charging: isCharging,
            network: connectionType,
            manifesto_id: manifestoAtual
        };

        console.log("💓 [PWA Tracking] Enviando via REST...");
        const url = `${window.API_BASE}manifesto/app/tracking-heartbeat/`;
        const response = await authFetch(url, {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        
        if (response && response.ok) {
            console.log("💓 [PWA Tracking] Heartbeat enviado via REST com sucesso", lat, lng);
        } else {
            console.warn("💓 [PWA Tracking] Falha ao enviar via REST:", response ? response.status : 'sem resposta');
        }
    } catch (err) {
        console.error("❌ [PWA Tracking] Erro no batimento:", err);
    }
}

// Inicia o monitoramento se já tivermos um manifesto ao carregar o script
if (typeof manifestoAtual !== 'undefined' && manifestoAtual) {
    iniciarCoracaoTracking();
} else {
    // Garante que o GPS Nativo (Java) seja desligado se a página carregar sem manifesto (ex: pós finalização)
    pararTrackingNativo();
}
