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

                // Salva os dados no elemento tr da tabela para acesso rápido ao abrir o modal
                const tr = document.querySelector(`tr[data-manifesto-id="${mID}"]`);
                if (tr) {
                    if (status.lat !== undefined && status.lat !== null) tr.setAttribute('data-lat', status.lat);
                    if (status.lng !== undefined && status.lng !== null) tr.setAttribute('data-lng', status.lng);
                    if (status.battery !== undefined && status.battery !== null) tr.setAttribute('data-bateria', status.battery);
                    if (status.network !== undefined && status.network !== null) tr.setAttribute('data-rede', status.network);
                    if (status.last_seen) tr.setAttribute('data-ultimo-acesso', status.last_seen);
                }

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
                const d = data.dados;
                const mID = d.manifesto_id;
                
                if (d.remover) {
                    const card = document.getElementById(`card-mft-${mID}`);
                    if (card) {
                        card.classList.add('fade-out');
                        setTimeout(() => card.remove(), 600);
                    }
                    return; // Ignora o resto se for remover
                }

                let cardContainer = document.getElementById(`card-mft-${mID}`);

                // Se não existe, criamos um novo
                if (!cardContainer) {
                    criarNovoCardManifesto(d);
                    cardContainer = document.getElementById(`card-mft-${mID}`);
                }

                // Atualiza a barrinha azul
                const progressBar = document.getElementById(`progress-bar-${mID}`);
                if (progressBar) progressBar.style.width = (d.porcentagem || 0) + '%';
                
                // Atualiza os números
                const baixadasEl = document.getElementById(`baixadas-${mID}`);
                if (baixadasEl) baixadasEl.innerText = d.baixadas;

                const totalEl = document.getElementById(`total-${mID}`);
                if (totalEl) totalEl.innerText = d.total;

                const percentEl = document.getElementById(`percent-${mID}`);
                if (percentEl) percentEl.innerText = d.porcentagem;

                // Efeito de flash (pulsada no card)
                if (cardContainer) {
                    const innerCard = cardContainer.querySelector('.card');
                    if (innerCard) {
                        innerCard.classList.remove('card-update-flash');
                        void innerCard.offsetWidth; // força reflow para reiniciar animação
                        innerCard.classList.add('card-update-flash');
                    }
                }
                
                // Re-avalia o último sinal para o card atualizado
                if (typeof atualizarUltimoSinalTorre === 'function') {
                    atualizarUltimoSinalTorre();
                }
            }
        } catch (err) {
            console.error("❌ Erro ao processar mensagem WS:", err);
        }
    };

    function criarNovoCardManifesto(d) {
        const grid = document.getElementById('grid-monitoramento');
        if (!grid) return;

        // Remove a mensagem de "Nenhum manifesto" caso exista
        const emptyMsg = grid.querySelector('.col-12.text-center.py-5');
        if (emptyMsg) {
            emptyMsg.remove();
        }

        const html = `
            <div class="col-12 col-md-6 col-lg-4 col-xl-3" id="card-mft-${d.manifesto_id}">
                <div class="card h-100 border-0 shadow-sm position-relative overflow-hidden" style="border-radius: 15px;">
                    <div class="progress position-absolute top-0 start-0 w-100" style="height: 4px; border-radius: 0;">
                        <div id="progress-bar-${d.manifesto_id}" class="progress-bar bg-primary" role="progressbar"
                            style="width: ${d.porcentagem || 0}%"></div>
                    </div>

                    <div class="card-body pt-4">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <div class="d-flex align-items-center">
                                <div class="flex-shrink-0">
                                    ${d.foto_motorista ? 
                                    `<img src="${d.foto_motorista}" class="rounded-circle" style="width: 48px; height: 48px; object-fit: cover; border: 2px solid #0d6efd;">` 
                                    : 
                                    `<div class="bg-soft-primary p-3 rounded-circle d-flex justify-content-center align-items-center" style="width: 48px; height: 48px;">
                                        <i class="fas fa-truck-moving text-primary"></i>
                                    </div>`
                                    }
                                </div>
                                <div class="ms-3">
                                    <h6 class="mb-0 fw-bold">${d.motorista_nome || 'Desconhecido'}</h6>
                                    <small class="text-muted">Manifesto: #${d.manifesto_id}</small>
                                    <small class="text-muted d-block mt-1" style="font-size: 9px;" id="data-registro-${d.manifesto_id}">
                                        <i class="bi bi-clock pe-1"></i>${d.data_registro || ''}
                                    </small>
                                </div>
                            </div>
                            
                            <!-- Ícone de Alerta para Manifesto Antigo (Renderizado via JS e Servidor) -->
                            <div id="alerta-antigo-${d.manifesto_id}" class="align-self-center px-2">
                                ${d.is_antigo ? 
                                `<i class="fas fa-exclamation-triangle text-warning fs-3" 
                                   title="Manifesto criado há ${d.dias_criado} dia(s) e não finalizado" 
                                   data-bs-toggle="tooltip" 
                                   style="cursor: help; animation: pulse 2s infinite;"></i>` : ''}
                            </div>

                            <div id="sinal-torre-${d.manifesto_id}" class="last-seen-torre" 
                                 data-iso="${d.ultimo_acesso_iso || ''}"
                                 data-criacao="${d.data_criacao_iso || ''}">
                                <!-- JS will render this -->
                            </div>
                        </div>

                        <div class="row text-center bg-light rounded-3 py-2 g-0">
                            <div class="col-6 border-end">
                                <small class="text-muted d-block">Total</small>
                                <span class="fw-bold" id="total-${d.manifesto_id}">${d.total || 0}</span>
                            </div>
                            <div class="col-6">
                                <small class="text-muted d-block">Baixadas</small>
                                <span class="fw-bold text-success" id="baixadas-${d.manifesto_id}">
                                    ${d.baixadas || 0}</span>
                            </div>
                        </div>

                        <div class="mt-3 d-flex justify-content-between align-items-center">
                            <div class="text-primary fw-bold fs-5">
                                <span id="percent-${d.manifesto_id}">
                                    ${d.porcentagem || 0}</span>%
                            </div>
                            <button class="btn btn-sm btn-outline-primary"
                                onclick="abrirRastreio('${d.manifesto_id}', '${d.motorista_nome || ''}', '${d.baixadas || 0}', '${d.total || 0}')">
                                <i class="bi bi-geo-alt me-1"></i> Rastrear
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        grid.insertAdjacentHTML('afterbegin', html);
    }

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
        if (el) {
            try {
                const date = new Date(isoDate);
                const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                el.innerHTML = `<div class="text-primary fw-bold" style="font-size: 0.9rem; text-align: center;">${timeStr}</div>`;
            } catch (e) {
                console.error("Erro data:", e);
            }
        }
        
        const elTorre = document.getElementById(`sinal-torre-${mID}`);
        if (elTorre) {
            elTorre.setAttribute('data-iso', isoDate);
                    if (typeof atualizarUltimoSinalTorre === 'function') {
                atualizarUltimoSinalTorre();
            }
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

// --- LÓGICA DE ÚLTIMO SINAL DA TORRE DE CONTROLE ---
function formatTimeDiff(ms) {
    const mins = Math.floor(ms / 60000);
    const hours = Math.floor(mins / 60);
    const days = Math.floor(hours / 24);
    
    if (mins < 60) {
        if (mins <= 5) return 'Sinal agora';
        return `Há ${mins}m`;
    } else if (hours < 24) {
        return `Há ${hours}h`;
    } else {
        return `Há ${days}d`;
    }
}

function atualizarUltimoSinalTorre() {
    const cards = document.querySelectorAll('[id^="card-mft-"]');
    cards.forEach(card => {
        const mID = card.id.replace('card-mft-', '');
        const elSinal = document.getElementById(`sinal-torre-${mID}`);
        if (!elSinal) return;
        
        const now = new Date();
        
        // --- LÓGICA DE ALERTA DE MANIFESTO ANTIGO ---
        let alertaContainer = document.getElementById(`alerta-antigo-${mID}`);
        
        // Resiliência: se o HTML estiver em cache e a div não existir, cria ela dinamicamente
        if (!alertaContainer) {
            alertaContainer = document.createElement('div');
            alertaContainer.id = `alerta-antigo-${mID}`;
            alertaContainer.className = 'align-self-center px-2';
            elSinal.parentNode.insertBefore(alertaContainer, elSinal);
        }

        const dataCriacaoIso = elSinal.getAttribute('data-criacao');
        
        if (dataCriacaoIso) {
            try {
                const criacaoDate = new Date(dataCriacaoIso);
                const diffCriacaoHours = (now - criacaoDate) / (1000 * 60 * 60);
                
                // Se o manifesto foi criado há mais de 24 horas, exibimos um alerta
                if (diffCriacaoHours > 24) {
                    alertaContainer.innerHTML = `
                        <i class="fas fa-exclamation-triangle text-warning fs-3" 
                           title="Manifesto criado há ${Math.floor(diffCriacaoHours/24)} dia(s) e não finalizado" 
                           data-bs-toggle="tooltip" 
                           style="cursor: help; animation: pulse 2s infinite;"></i>
                    `;
                    // Inicializa tooltip se o bootstrap estiver disponível
                    if (typeof bootstrap !== 'undefined' && !alertaContainer.hasAttribute('data-tooltip-init')) {
                        new bootstrap.Tooltip(alertaContainer.querySelector('[data-bs-toggle="tooltip"]'));
                        alertaContainer.setAttribute('data-tooltip-init', 'true');
                    }
                } else {
                    alertaContainer.innerHTML = '';
                }
            } catch(e) {
                console.error('Erro na data de criação', e);
            }
        }
        
        const isoDate = elSinal.getAttribute('data-iso');
        if (!isoDate || isoDate.trim() === '') {
            elSinal.innerHTML = `
                <div style="border: 1px solid #ccc; background-color: #f8f9fa; border-radius: 20px; padding: 2px 10px; display: inline-block; min-width: 80px; text-align: center;">
                    <span style="color: #6c757d; font-weight: bold; font-size: 13px;">--:--</span>
                </div>
                <div style="font-size: 11px; color: #6c757d; margin-top: 4px; text-align: center;">
                    Sem sinal
                </div>
            `;
            card.classList.remove('card-danger-pulse');
            return;
        }
        
        try {
            const date = new Date(isoDate);
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            
            const now = new Date();
            const diffMs = now - date;
            
            const diffHours = diffMs / (1000 * 60 * 60);
            
            let bgColor = '';
            let textColor = '';
            let isRedPulsing = false;
            
            if (diffHours <= 1.5 || diffMs < 0) { // < 0 caso horário do celular esteja à frente do servidor
                bgColor = 'rgba(25, 135, 84, 0.1)'; // green soft
                textColor = '#198754';
            } else if (diffHours <= 4) {
                bgColor = 'rgba(255, 193, 7, 0.1)'; // yellow soft
                textColor = '#ffc107';
            } else {
                bgColor = 'rgba(220, 53, 69, 0.1)'; // red soft
                textColor = '#dc3545';
                if (diffHours > 24) {
                    isRedPulsing = true;
                }
            }
            
            const textDiff = diffMs < 0 ? 'Sinal agora' : formatTimeDiff(diffMs);
            
            elSinal.innerHTML = `
                <div style="border: 1px solid ${textColor}; background-color: ${bgColor}; border-radius: 20px; padding: 2px 10px; display: inline-block; min-width: 80px; text-align: center;">
                    <i class="fas fa-circle" style="color: ${textColor}; font-size: 8px; vertical-align: middle; margin-right: 4px;"></i>
                    <span style="color: ${textColor}; font-weight: bold; font-size: 13px;">${timeStr}</span>
                </div>
                <div style="font-size: 11px; color: #6c757d; margin-top: 4px; text-align: center;">
                    ${textDiff}
                </div>
            `;
            
            if (isRedPulsing) {
                card.classList.add('card-danger-pulse');
            } else {
                card.classList.remove('card-danger-pulse');
            }
        } catch(e) {
            console.error('Erro na data Torre', e);
        }
    });
}

// --- FUNÇÕES DO MAPA REAL-TIME ---

function abrirRastreamentoRealTime(manifestoId, motoristaNome, initialLat, initialLng) {
    monitorandoManifestoId = manifestoId;
    document.getElementById('rastreamento-titulo').innerText = `Rastreando: ${motoristaNome}`;
    document.getElementById('rastreamento-mft').innerText = manifestoId;

    // Carrega dados em tempo real da tabela, se disponíveis
    const tr = document.querySelector(`tr[data-manifesto-id="${manifestoId}"]`);
    let lat = initialLat;
    let lng = initialLng;
    let battery = null;
    let network = '';
    let lastSeen = null;

    if (tr) {
        lat = tr.getAttribute('data-lat') || lat;
        lng = tr.getAttribute('data-lng') || lng;
        battery = tr.getAttribute('data-bateria') || null;
        network = tr.getAttribute('data-rede') || '';
        lastSeen = tr.getAttribute('data-ultimo-acesso') || null;
    }

    const modal = new bootstrap.Modal(document.getElementById('modalRastreamento'));
    modal.show();

    // Aguarda o modal abrir para inicializar o mapa (Leaflet precisa do container visível)
    document.getElementById('modalRastreamento').addEventListener('shown.bs.modal', function () {
        initMapaRastreamento(lat, lng);

        // Preenche o overlay de status com as últimas informações conhecidas
        document.getElementById('mapa-status-bat').innerText = battery ? battery + '%' : '--%';
        document.getElementById('mapa-status-rede').innerText = network || '--';
        if (lastSeen) {
            try {
                const timeStr = new Date(lastSeen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                document.getElementById('mapa-status-visto').innerText = timeStr;
            } catch (e) {
                document.getElementById('mapa-status-visto').innerText = '--';
            }
        } else {
            document.getElementById('mapa-status-visto').innerText = '--';
        }
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