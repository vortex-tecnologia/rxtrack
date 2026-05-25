/**
 * pwa_tracking.js - Lógica isolada de rastreamento (Heartbeat)
 * Responsável por coletar GPS, bateria e sinal e enviar via WebSocket.
 */

async function iniciarCoracaoTracking() {
    // Só inicia se houver manifesto ativo e não estiver conectado
    if (socketTracking || !manifestoAtual) return; 

    const token = localStorage.getItem('accessToken');
    const ws_scheme = window.location.protocol === "https:" ? "wss" : "ws";
    // Usamos a filial do motorista ou 'todas'
    const filial = typeof filialIdMotorista !== 'undefined' ? filialIdMotorista : 'todas';
    const ws_url = `${ws_scheme}://${window.location.host}/ws/painel-logistico/${filial}/?token=${token}`;

    // Log removido por segurança (expunha token JWT na URL)
    socketTracking = new WebSocket(ws_url);

    socketTracking.onopen = () => {
        console.log("💓 [PWA Tracking] Conectado ao servidor");
        if (heartbeatInterval) clearInterval(heartbeatInterval);
        heartbeatInterval = setInterval(enviarHeartbeat, 30000); // 30 segundos
        enviarHeartbeat(); 
    };

    socketTracking.onclose = () => {
        console.warn("💓 [PWA Tracking] Conexão perdida. Reconectando em 10s...");
        socketTracking = null;
        if (heartbeatInterval) clearInterval(heartbeatInterval);
        setTimeout(iniciarCoracaoTracking, 10000);
    };
}

async function enviarHeartbeat() {
    if (!socketTracking || socketTracking.readyState !== WebSocket.OPEN) {
        console.warn("💓 [PWA Tracking] Socket não pronto.");
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

        // Log removido por segurança (expunha GPS e bateria)
        socketTracking.send(JSON.stringify(payload));
    } catch (err) {
        console.error("❌ [PWA Tracking] Erro no batimento:", err);
    }
}

// Inicia o monitoramento se já tivermos um manifesto ao carregar o script
if (typeof manifestoAtual !== 'undefined' && manifestoAtual) {
    iniciarCoracaoTracking();
}
