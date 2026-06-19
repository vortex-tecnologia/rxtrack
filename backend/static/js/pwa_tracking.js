/**
 * pwa_tracking.js - Lógica isolada de rastreamento (Heartbeat)
 * Responsável por coletar GPS, bateria e sinal e enviar via WebSocket ou REST API.
 */

let heartbeatInterval = null;
let socketTracking = null;

async function iniciarCoracaoTracking() {
    // Inicia o loop de envio a cada 30 segundos (se não iniciado)
    if (!heartbeatInterval && typeof manifestoAtual !== 'undefined' && manifestoAtual) {
        heartbeatInterval = setInterval(enviarHeartbeat, 30000);
        enviarHeartbeat(); // Envia o primeiro imediatamente
    }

    // Tenta conectar o WebSocket para real-time leve (se não estiver conectado)
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

async function enviarHeartbeat() {
    // Auto-limpeza caso o manifesto seja finalizado ou limpo
    if (typeof manifestoAtual === 'undefined' || !manifestoAtual) {
        console.log("💓 [PWA Tracking] Sem manifesto ativo. Parando heartbeat.");
        if (heartbeatInterval) {
            clearInterval(heartbeatInterval);
            heartbeatInterval = null;
        }
        if (socketTracking) {
            socketTracking.close();
            socketTracking = null;
        }
        return;
    }

    try {
        console.log("💓 [PWA Tracking] Obtendo localização...");
        const coords = await getCoords();
        
        const lat = coords ? coords.lat : null;
        const lng = coords ? coords.lon : null;

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
            console.log("💓 [PWA Tracking] Heartbeat enviado via WS");
        } else {
            console.log("💓 [PWA Tracking] WS offline. Enviando via REST...");
            const url = `${window.API_BASE}manifesto/app/tracking-heartbeat/`;
            const response = await authFetch(url, {
                method: 'POST',
                body: JSON.stringify(payload)
            });
            if (response && response.ok) {
                console.log("💓 [PWA Tracking] Heartbeat enviado via REST com sucesso");
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

