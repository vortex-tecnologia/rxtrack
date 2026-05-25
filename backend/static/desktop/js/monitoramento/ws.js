const ws_scheme = window.location.protocol === "https:" ? "wss" : "ws";
const filialPrefix = window.FILIAL_ATIVA || 'todas';
const ws_url = ws_scheme + "://" + window.location.host + "/ws/painel-logistico/" + filialPrefix + "/";

let socket;
let mapaRastreamento = null;
let marcadorMotorista = null;
let monitorandoManifestoId = null;

function conectarWebSocket() {
    console.log("🔌 Tentando conectar WebSocket em:", ws_url);
    socket = new WebSocket(ws_url);

    socket.onopen = function() {
        console.log("✅ WS Conectado!");
        const status = document.getElementById('status-ws');
        if (status) {
            status.classList.replace('bg-danger', 'bg-success');
            status.innerHTML = '<i class="fas fa-circle me-2 animate-pulse"></i>CONECTADO';
        }
    };

    socket.onmessage = function(e) {
        try {
            console.log("📩 WS Mensagem recebida:", e.data);
            const data = JSON.parse(e.data);
            
            // 1. TRATAR STATUS DO MOTORISTA (HEARTBEAT)
            if (data.type === 'status_motorista') {
                const status = data.dados;
                const mID = status.manifesto_id ? status.manifesto_id.toString().trim() : null;
                
                if (!mID) return;

                console.log("💓 Status recebido para:", mID, status);

                // Atualiza Tabela (se existir no DOM)
                updateBatteryIcon(mID, status.battery);
                updateNetworkStatus(mID, status.network);
                updateLastSeen(mID, status.last_seen);

                // Atualiza Mapa Modal (se estiver aberto para este manifesto)
                if (monitorandoManifestoId === mID && mapaRastreamento) {
                    atualizarPosicaoMapa(status);
                }
                return;
            }

            // 2. TRATAR ATUALIZAÇÃO DE MANIFESTO (SIGNAL)
            if (data.dados && data.type !== 'status_motorista') {
                const mID = data.dados.manifesto_id;
                // ... lógica de atualização de progresso na tabela ...
                const progressBar = document.getElementById(`progress-bar-${mID}`);
                if (progressBar) progressBar.style.width = (data.dados.porcentagem || 0) + '%';
            }
        } catch (err) {
            console.error("❌ Erro ao processar mensagem WS:", err);
        }
    };

    function updateBatteryIcon(mID, level) {
        const container = document.getElementById(`battery-mft-${mID}`);
        if (!container) return;

        let iconClass = "bi-battery";
        let colorClass = "text-muted";

        if (level !== null && level !== undefined) {
            const l = parseInt(level);
            if (l > 80) { iconClass = "bi-battery-full"; colorClass = "text-success"; }
            else if (l > 50) { iconClass = "bi-battery-half"; colorClass = "text-info"; }
            else if (l > 20) { iconClass = "bi-battery-half"; colorClass = "text-warning"; }
            else { iconClass = "bi-battery-low"; colorClass = "text-danger"; }
        }

        // Seletor específico para a parte da bateria para evitar sobrescrever a rede
        let batteryPart = container.querySelector('.battery-part');
        if (!batteryPart) {
            // Se não existe a estrutura, criamos mantendo a rede
            const networkBadge = container.querySelector('.badge');
            container.innerHTML = `
                <div class="d-flex flex-column align-items-center">
                    <div class="battery-part"></div>
                    ${networkBadge ? networkBadge.outerHTML : ''}
                </div>
            `;
            batteryPart = container.querySelector('.battery-part');
        }

        batteryPart.innerHTML = `
            <i class="bi ${iconClass} ${colorClass}" style="font-size: 1.2rem;"></i>
            <small class="${colorClass}">${level !== null ? level + '%' : '--%'}</small>
        `;
    }

    function updateNetworkStatus(mID, network) {
        const el = document.getElementById(`network-mft-${mID}`);
        if (!el) return;
        el.innerText = (network && network !== 'unknown') ? network.toUpperCase() : '--';
        
        // Adiciona uma corzinha dependendo do sinal
        if (network === '4g' || network === 'wifi') el.className = 'badge bg-success text-white border-0 mt-1';
        else if (network === '3g') el.className = 'badge bg-info text-white border-0 mt-1';
        else el.className = 'badge bg-light text-dark border-0 mt-1';
    }

    function updateLastSeen(mID, isoDate) {
        const el = document.getElementById(`last-seen-mft-${mID}`);
        if (!el) return;

        try {
            const date = new Date(isoDate);
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            el.innerHTML = `<div class="text-primary fw-bold" style="font-size: 0.9rem; text-align: center;">${timeStr}</div>`;
        } catch (e) {
            console.error("Erro data:", e);
        }
    }

    socket.onclose = function() {
        console.log("WS desconectado. Reconectando em 5s...");
        const status = document.getElementById('status-ws');
        if (status) {
            status.classList.replace('bg-success', 'bg-danger');
            status.innerHTML = '<i class="fas fa-exclamation-triangle me-2"></i>DESCONECTADO';
        }
        setTimeout(conectarWebSocket, 5000);
    };

    socket.onerror = function(error) {
        console.error("❌ Erro WS:", error);
    };
}

// --- FUNÇÕES DO MAPA REAL-TIME ---

function abrirRastreamentoRealTime(manifestoId, motoristaNome, initialLat, initialLng) {
    monitorandoManifestoId = manifestoId;
    document.getElementById('rastreamento-titulo').innerText = `Rastreando: ${motoristaNome}`;
    document.getElementById('rastreamento-mft').innerText = manifestoId;

    const modal = new bootstrap.Modal(document.getElementById('modalRastreamento'));
    modal.show();

    // Aguarda o modal abrir para inicializar o mapa (Leaflet precisa do container visível)
    document.getElementById('modalRastreamento').addEventListener('shown.bs.modal', function () {
        initMapaRastreamento(initialLat, initialLng);
    }, { once: true });

    // Limpeza ao fechar
    document.getElementById('modalRastreamento').addEventListener('hidden.bs.modal', function () {
        monitorandoManifestoId = null;
        if (mapaRastreamento) {
            mapaRastreamento.remove();
            mapaRastreamento = null;
            marcadorMotorista = null;
        }
    }, { once: true });
}

function initMapaRastreamento(lat, lng) {
    const parsedLat = parseFloat(lat);
    const parsedLng = parseFloat(lng);
    const defaultLat = !isNaN(parsedLat) ? parsedLat : -23.5505;
    const defaultLng = !isNaN(parsedLng) ? parsedLng : -46.6333;

    if (mapaRastreamento) mapaRastreamento.remove();

    mapaRastreamento = L.map('mapa-rastreamento').setView([defaultLat, defaultLng], 15);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(mapaRastreamento);

    // Força o Leaflet a recalcular o tamanho do container (resolve problema de mapa cinza/cortado)
    setTimeout(() => {
        mapaRastreamento.invalidateSize();
    }, 200);

    const iconTruck = L.icon({
        iconUrl: 'https://cdn-icons-png.flaticon.com/512/2554/2554978.png',
        iconSize: [40, 40],
        iconAnchor: [20, 20]
    });

    marcadorMotorista = L.marker([defaultLat, defaultLng], { icon: iconTruck }).addTo(mapaRastreamento);
    
    if (isNaN(parsedLat) || isNaN(parsedLng)) {
        marcadorMotorista.bindPopup("<b>Aguardando primeiro sinal de GPS...</b>").openPopup();
    }
}

function atualizarPosicaoMapa(dados) {
    if (!mapaRastreamento || !marcadorMotorista) return;

    const latlng = [dados.lat, dados.lng];
    marcadorMotorista.setLatLng(latlng);
    mapaRastreamento.panTo(latlng);

    // Atualiza Overlay do Mapa
    document.getElementById('mapa-status-bat').innerText = dados.battery ? dados.battery + '%' : '--%';
    document.getElementById('mapa-status-rede').innerText = dados.network || '--';
    
    if (dados.last_seen) {
        const timeStr = new Date(dados.last_seen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        document.getElementById('mapa-status-visto').innerText = timeStr;
    }
}

conectarWebSocket();