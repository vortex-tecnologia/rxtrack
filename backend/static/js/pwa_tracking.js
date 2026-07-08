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
    // Tenta carregar o plugin nativo via registerPlugin ou direto do objeto Plugins
    let bgGeo = null;
    if (window.Capacitor) {
        if (window.Capacitor.registerPlugin) {
            try { bgGeo = window.Capacitor.registerPlugin("BackgroundGeolocation"); } catch(e) { alert("registerPlugin erro: " + e.message); }
        }
        if (!bgGeo && window.Capacitor.Plugins) {
            bgGeo = window.Capacitor.Plugins.BackgroundGeolocation;
        }
    } else {
        alert("CRÍTICO: window.Capacitor não existe nesta página!");
    }

    if (bgGeo) {
        if (!capacitorWatcherId && typeof manifestoAtual !== 'undefined' && manifestoAtual) {
            console.log("🔥 [GPS Nativo] Iniciando modo AGRESSIVO (Capacitor BackgroundGeolocation)...");
            
            bgGeo.addWatcher(
                {
                    backgroundMessage: "Rastreamento do QuickTrack ativo.",
                    backgroundTitle: "Coletando GPS para o Manifesto.",
                    requestPermissions: true,
                    stale: false,
                    distanceFilter: 0
                },
                function callback(location, error) {
                    if (error) {
                        alert("Erro no GPS Nativo: " + JSON.stringify(error));
                        return console.error("📍 [Tracking] Erro:", error);
                    }
                    console.log("📍 [Tracking] Coordenada nativa:", location.latitude, location.longitude);
                    enviarHeartbeat(location.latitude, location.longitude);
                }
            ).then(id => {
                capacitorWatcherId = id;
                console.log("📍 [Tracking] Watcher nativo ativo:", id);
            }).catch(e => {
                alert("Falha Crítica ao iniciar GPS Nativo: " + (e.message || JSON.stringify(e)));
                console.error("📍 [Tracking] Erro crítico no addWatcher", e);
            });
            
            // Fallback: timer de 30s chamando o watcher manualmente se necessário
            if (!nativeHeartbeatTimer) {
                nativeHeartbeatTimer = setInterval(() => {
                    enviarHeartbeat(); 
                }, 30000);
            }
        }
    } else {
        // ═══════════════════════════════════════════════════════════
        // MODO PWA (Navegador) - Fallback tradicional com setInterval
        // ═══════════════════════════════════════════════════════════
        if (!heartbeatInterval && typeof manifestoAtual !== 'undefined' && manifestoAtual) {
            heartbeatInterval = setInterval(enviarHeartbeat, 30000);
            enviarHeartbeat(); // Envia o primeiro imediatamente
        }
    }

    // ═══════════════════════════════════════════════════════════
    // WEBSOCKET - Conexão real-time para painel (ambos os modos)
    // ═══════════════════════════════════════════════════════════
    if (!socketTracking && typeof manifestoAtual !== 'undefined' && manifestoAtual) {
        const token = localStorage.getItem('accessToken');
        const ws_scheme = window.location.protocol === "https:" ? "wss" : "ws";
        const filial = typeof filialIdMotorista !== 'undefined' ? filialIdMotorista : 'todas';
        const ws_url = `${ws_scheme}://${window.location.host}/ws/painel-logistico/${filial}/?token=${token}`;

        socketTracking = new WebSocket(ws_url);

        socketTracking.onopen = () => {
            console.log("💓 [PWA Tracking] WS Conectado ao servidor");
        };

        socketTracking.onclose = () => {
            console.warn("💓 [PWA Tracking] WS Conexão perdida. Tentando reconectar em 10s...");
            socketTracking = null;
            setTimeout(iniciarCoracaoTracking, 10000);
        };

        socketTracking.onerror = (err) => {
            console.error("💓 [PWA Tracking] WS erro:", err);
        };
    }
}

/**
 * Para completamente o rastreamento nativo (chamado quando manifesto finaliza)
 */
function pararTrackingNativo() {
    console.log("🛑 [GPS Nativo] Parando rastreamento...");
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
        if (socketTracking) {
            socketTracking.close();
            socketTracking = null;
        }
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
        if ('getBattery' in navigator) {
            try {
                const battery = await navigator.getBattery();
                batteryLevel = Math.round(battery.level * 100);
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
            network: connectionType,
            manifesto_id: manifestoAtual
        };

        if (socketTracking && socketTracking.readyState === WebSocket.OPEN) {
            socketTracking.send(JSON.stringify(payload));
            console.log("💓 [PWA Tracking] Heartbeat enviado via WS", lat, lng);
        } else {
            console.log("💓 [PWA Tracking] WS offline. Enviando via REST...");
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
        }
    } catch (err) {
        console.error("❌ [PWA Tracking] Erro no batimento:", err);
    }
}

// Inicia o monitoramento se já tivermos um manifesto ao carregar o script
if (typeof manifestoAtual !== 'undefined' && manifestoAtual) {
    iniciarCoracaoTracking();
}
