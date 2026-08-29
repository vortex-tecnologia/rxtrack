const ws_scheme = window.location.protocol === "https:" ? "wss" : "ws";
const filialPrefix = window.FILIAL_ATIVA || 'todas';
const ws_url = ws_scheme + "://" + window.location.host + "/ws/painel-logistico/" + filialPrefix + "/";

let socket;
let mapaRastreamento = null;
let marcadorMotorista = null;
let monitorandoManifestoId = null;
let motoristaNomeAtual = '';

function conectarWebSocket() {
    console.log("🔌 Tentando conectar WebSocket em:", ws_url);
    socket = new WebSocket(ws_url);

    socket.onopen = function () {
        console.log("✅ WS Conectado!");
        const status = document.getElementById('status-ws');
        if (status) {
            status.classList.replace('bg-danger', 'bg-success');
            status.innerHTML = '<i class="fas fa-circle me-2 animate-pulse"></i>CONECTADO';
        }
    };

    socket.onmessage = function (e) {
        try {
            console.log("📩 WS Mensagem recebida:", e.data);
            const data = JSON.parse(e.data);

            // 0. TRATAR SINCRONIZAÇÃO DE EXPANSÃO/RECOLHIMENTO DE PILHA (STACK)
            if (data.type === 'toggle_stack') {
                const payload = data.dados || data;
                const motId = String(payload.motorista_id || '');
                if (motId) {
                    if (payload.expanded) {
                        stacksExpandidos.add(motId);
                    } else {
                        stacksExpandidos.delete(motId);
                    }
                    if (typeof reavaliarStacks === 'function') {
                        reavaliarStacks();
                    }
                }
                return;
            }

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
                    if (status.is_charging !== undefined && status.is_charging !== null) tr.setAttribute('data-carregando', status.is_charging);
                    if (status.network !== undefined && status.network !== null) tr.setAttribute('data-rede', status.network);
                    if (status.last_seen) tr.setAttribute('data-ultimo-acesso', status.last_seen);
                }

                // Atualiza Tabela (se existir no DOM)
                updateBatteryIcon(mID, status.battery, status.is_charging);
                updateNetworkStatus(mID, status.network);
                updateLastSeen(mID, status.last_seen);

                // Atualiza Mapa Modal (se estiver aberto para este manifesto)
                if (monitorandoManifestoId === mID && marcadorMotorista) {
                    const lat = parseFloat(status.lat);
                    const lng = parseFloat(status.lng);
                    if (!isNaN(lat) && !isNaN(lng)) {
                        marcadorMotorista.setLatLng([lat, lng]);
                        if (typeof mapaEntrega !== 'undefined' && mapaEntrega) {
                            mapaEntrega.panTo([lat, lng]);
                        } else if (mapaRastreamento) {
                            mapaRastreamento.panTo([lat, lng]);
                        }
                    }
                    // Atualiza Tooltip e Popup do marcador no mapa
                    atualizarTooltipEPopupMarcador(motoristaNomeAtual, status.last_seen, status.battery, status.network, status.is_charging);

                    // Atualiza overlay de status do modal (se existir)
                    const batEl = document.getElementById('mapa-status-bat');
                    const redeEl = document.getElementById('mapa-status-rede');
                    const vistoEl = document.getElementById('mapa-status-visto');
                    if (batEl) {
                        batEl.innerText = status.battery ? status.battery + '%' : '--%';
                        if (status.is_charging) batEl.innerText += ' ⚡';
                    }
                    if (redeEl) redeEl.innerText = status.network || '--';
                    if (vistoEl && status.last_seen) {
                        try {
                            vistoEl.innerText = new Date(status.last_seen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                        } catch (e) { }
                    }
                }
                return;
            }

            // 2. TRATAR ATUALIZAÇÃO DE MANIFESTO (SIGNAL)
            if (data.dados && data.type !== 'status_motorista') {
                const d = data.dados;
                const mID = d.manifesto_id;
                const fId = d.filial_id ? String(d.filial_id) : '';
                const fNome = d.filial_nome || '';

                // Garante que a filial tem um card no cabeçalho (Criação Dinâmica via WS)
                if (fId) {
                    const contagemExata = (d.total_ativos_filial !== undefined && d.total_ativos_filial !== null) ? d.total_ativos_filial : 0;
                    garantirCardFilial(fId, fNome, contagemExata);
                    if (d.total_ativos_filial !== undefined && d.total_ativos_filial !== null) {
                        atualizarContadorFilial(fId, d.total_ativos_filial);
                    }
                }

                if (d.remover) {
                    const card = document.getElementById(`card-mft-${mID}`);
                    if (card && !card.dataset.removendo) {
                        card.dataset.removendo = 'true';
                        card.classList.add('fade-out');
                        setTimeout(() => {
                            card.remove();
                            if (typeof aplicarFiltroFilialNaGrid === 'function') {
                                aplicarFiltroFilialNaGrid();
                            }
                            if (typeof reavaliarStacks === 'function') {
                                reavaliarStacks();
                            }
                        }, 500);
                    }
                    return; // Ignora o resto se for remover
                }

                let cardContainer = document.getElementById(`card-mft-${mID}`);

                // Se não existe, criamos um novo
                if (!cardContainer) {
                    criarNovoCardManifesto(d);
                    cardContainer = document.getElementById(`card-mft-${mID}`);
                    if (typeof aplicarFiltroFilialNaGrid === 'function') {
                        aplicarFiltroFilialNaGrid();
                    }
                } else if (d.status && cardContainer.getAttribute('data-status') !== d.status) {
                    cardContainer.setAttribute('data-status', d.status);
                    if (typeof reavaliarStacks === 'function') {
                        reavaliarStacks();
                    }
                }

                let devePiscar = false;

                // Atualiza a barrinha azul
                const progressBar = document.getElementById(`progress-bar-${mID}`);
                if (progressBar) progressBar.style.width = (d.porcentagem || 0) + '%';

                // Atualiza os números
                const baixadasEl = document.getElementById(`baixadas-${mID}`);
                if (baixadasEl) {
                    if (parseInt(baixadasEl.innerText) !== parseInt(d.baixadas)) devePiscar = true;
                    baixadasEl.innerText = d.baixadas;
                }

                const totalEl = document.getElementById(`total-${mID}`);
                if (totalEl) {
                    if (parseInt(totalEl.innerText) !== parseInt(d.total)) devePiscar = true;
                    totalEl.innerText = d.total;
                }

                const percentEl = document.getElementById(`percent-${mID}`);
                if (percentEl) percentEl.innerText = d.porcentagem;

                // Atualiza status do manifesto
                if (d.status) {
                    if (cardContainer) cardContainer.setAttribute('data-status', d.status);
                    const elTorre = document.getElementById(`sinal-torre-${mID}`);
                    if (elTorre) elTorre.setAttribute('data-status', d.status);
                }

                // Atualiza a hora do sinal na torre
                if (d.ultimo_acesso_iso) {
                    const elTorre = document.getElementById(`sinal-torre-${mID}`);
                    if (elTorre) {
                        elTorre.setAttribute('data-iso', d.ultimo_acesso_iso);
                    }
                }

                // Atualiza alerta de manifesto antigo
                if (d.is_antigo !== undefined) {
                    const alertaContainer = document.getElementById(`alerta-antigo-${mID}`);
                    if (alertaContainer) {
                        alertaContainer.innerHTML = d.is_antigo ?
                            `<i class="fas fa-exclamation-triangle text-warning fs-3" 
                               title="Manifesto criado há ${d.dias_criado} dia(s) e não finalizado" 
                               data-bs-toggle="tooltip" 
                               style="cursor: help; animation: pulse 2s infinite;"></i>` : '';
                    }
                }

                // Atualiza badge de canhotos ilegíveis em tempo real
                const badgeIlegivel = document.getElementById(`badge-ilegivel-${mID}`);
                const countIlegivel = document.getElementById(`count-ilegivel-${mID}`);
                if (badgeIlegivel && countIlegivel) {
                    const totalIlegivel = parseInt(d.total_ilegivel || 0);
                    countIlegivel.innerText = totalIlegivel;
                    if (totalIlegivel > 0) {
                        badgeIlegivel.classList.remove('d-none');
                        badgeIlegivel.setAttribute('title', `${totalIlegivel} foto(s) de canhoto ilegível(is) precisando de atenção`);
                    } else {
                        badgeIlegivel.classList.add('d-none');
                    }
                }

                // Efeito de flash (pulsada no card) apenas se mudou baixadas ou total
                if (cardContainer && devePiscar) {
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

                // Atualiza em tempo real o modal de detalhes caso esteja aberto para este manifesto
                if (typeof manifestoAbertoDetalhesId !== 'undefined' && manifestoAbertoDetalhesId) {
                    if ((manifestoAbertoDetalhesId === String(mID) || manifestoAbertoDetalhesId === String(d.manifesto_id)) && typeof carregarConteudoModalDetalhes === 'function') {
                        carregarConteudoModalDetalhes(manifestoAbertoDetalhesId, true);
                    }
                }
            }
        } catch (err) {
            console.error("❌ Erro ao processar mensagem WS:", err);
        }
    };

    function garantirCardFilial(filialId, filialNome, initialCount = 0) {
        if (!filialId) return;
        const sId = String(filialId);
        let btn = document.getElementById(`btn-filial-${sId}`);
        if (!btn) {
            const container = document.getElementById('container-filiais-torre');
            if (container) {
                const isAtivo = (window.filialAtivaTorreId === sId);
                const btnHtml = `
                    <button type="button" 
                            class="card-filial-btn btn ${isAtivo ? 'active-filial-card' : 'inactive-filial-card'} d-flex align-items-center gap-2"
                            id="btn-filial-${sId}"
                            data-filial-id="${sId}"
                            data-filial-nome="${filialNome || 'Filial'}"
                            onclick="selecionarFilialTorre('${sId}')">
                        <i class="bi bi-building"></i>
                        <span class="filial-nome-text fw-bold">${filialNome || 'Filial'}</span>
                        <span class="badge ${isAtivo ? 'bg-white text-primary' : 'bg-primary-subtle text-primary border'} fw-bold rounded-pill px-2 py-1 badge-filial-count" 
                              id="badge-count-filial-${sId}">
                            ${initialCount}
                        </span>
                    </button>
                `;
                container.insertAdjacentHTML('beforeend', btnHtml);
            }
        }
    }

    function atualizarContadorFilial(filialId, valorExatoOuDelta) {
        if (!filialId) return;
        const sId = String(filialId);
        const badge = document.getElementById(`badge-count-filial-${sId}`);
        if (badge) {
            let novo;
            if (typeof valorExatoOuDelta === 'number' && valorExatoOuDelta >= 0) {
                novo = valorExatoOuDelta;
            } else {
                let atual = parseInt(badge.innerText.trim(), 10) || 0;
                novo = Math.max(0, atual + (valorExatoOuDelta || 0));
            }
            badge.innerText = novo;
            
            badge.classList.remove('filial-badge-pulse');
            void badge.offsetWidth;
            badge.classList.add('filial-badge-pulse');
        }
    }

    function criarNovoCardManifesto(d) {
        const grid = document.getElementById('grid-monitoramento');
        if (!grid) return;

        // Remove a mensagem de "Nenhum manifesto" caso exista
        const emptyMsg = grid.querySelector('.col-12.text-center.py-5');
        if (emptyMsg) {
            emptyMsg.remove();
        }

        const deveEsconder = (window.filialAtivaTorreId && String(d.filial_id) !== String(window.filialAtivaTorreId));
        const html = `
            <div class="col-12 col-md-6 col-lg-4 col-xl-3 manifesto-card-item" 
                 id="card-mft-${d.manifesto_id}"
                 data-status="${d.status || 'AGUARDANDO'}"
                 data-motorista-id="${d.motorista_id || ''}"
                 data-criacao="${d.data_criacao_iso || ''}"
                 data-filial-id="${d.filial_id || ''}"
                 data-filial-nome="${d.filial_nome || ''}"
                 style="${deveEsconder ? 'display: none;' : ''}">
                <div class="card h-100 border-0 shadow-sm position-relative overflow-hidden" style="border-radius: 15px;">
                    <div class="progress position-absolute top-0 start-0 w-100" style="height: 4px; border-radius: 0;">
                        <div id="progress-bar-${d.manifesto_id}" class="progress-bar bg-primary" role="progressbar"
                            style="width: ${d.porcentagem || 0}%"></div>
                    </div>

                    <div class="card-body pt-4">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <div class="d-flex align-items-center flex-grow-1 me-2" style="min-width: 0;">
                                <div class="flex-shrink-0">
                                    ${d.foto_motorista ?
                `<img src="${d.foto_motorista}" class="rounded-circle" style="width: 44px; height: 44px; object-fit: cover; border: 2px solid #0d6efd;">`
                :
                `<div class="bg-soft-primary p-2 rounded-circle d-flex justify-content-center align-items-center" style="width: 44px; height: 44px;">
                                        <i class="fas fa-truck-moving text-primary"></i>
                                    </div>`
            }
                                </div>
                                <div class="ms-2 flex-grow-1" style="min-width: 0;">
                                    <h6 class="mb-0 fw-bold d-flex align-items-center gap-1" style="min-width: 0;">
                                        <span class="text-truncate" title="${d.motorista_nome || 'Desconhecido'}" style="max-width: 150px;">${d.motorista_nome || 'Desconhecido'}</span>
                                        ${d.icone_dispositivo || ''}
                                    </h6>
                                    <div class="d-flex flex-wrap align-items-center gap-1 mt-0">
                                        <small class="text-muted text-nowrap" style="font-size: 0.78rem;">#${d.manifesto_id}</small>
                                        ${d.placa_veiculo ? `
                                            <span class="badge bg-light text-dark border px-1 py-0 d-inline-flex align-items-center gap-1" style="font-size: 0.62rem; font-weight: 600; border-radius: 4px;" title="Veículo: ${d.placa_veiculo}">
                                                <i class="fas ${['TRUCK', 'CARRETA', 'CAVALO'].includes(d.tipo_veiculo) ? 'fa-truck' : 'fa-car'} text-secondary" style="font-size: 0.6rem;"></i>
                                                ${d.placa_veiculo}
                                            </span>
                                        ` : ''}
                                        ${d.motorista_categoria === 'AGREGADO' ?
                `<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle px-1 py-0" style="font-size: 0.6rem; font-weight: 700; border-radius: 4px;">AGREGADO</span>` :
                d.motorista_categoria === 'DEDICADO' ?
                    `<span class="badge bg-info-subtle text-info-emphasis border border-info-subtle px-1 py-0" style="font-size: 0.6rem; font-weight: 700; border-radius: 4px;">DEDICADO</span>` :
                    `<span class="badge bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle px-1 py-0" style="font-size: 0.6rem; font-weight: 700; border-radius: 4px;">EMPRESA</span>`
            }
                                    </div>
                                    <small class="text-muted d-block mt-0" style="font-size: 9px;" id="data-registro-${d.manifesto_id}">
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
                                 data-status="${d.status || 'AGUARDANDO'}"
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
                            <div class="d-flex gap-2 align-items-center">
                                <button class="btn btn-sm btn-outline-secondary d-flex align-items-center gap-1 position-relative"
                                    onclick="abrirDetalhesManifestoTorre('${d.manifesto_id}')" title="Ver Notas / Itens do Manifesto">
                                    <i class="bi bi-card-list"></i> Manifesto
                                    <span id="badge-ilegivel-${d.manifesto_id}" 
                                          class="position-absolute badge rounded-pill bg-danger shadow-sm badge-pulse-alert ${(d.total_ilegivel && d.total_ilegivel > 0) ? '' : 'd-none'}"
                                          style="top: -7px; right: -7px;"
                                          title="${d.total_ilegivel || 0} foto(s) de canhoto ilegível(is) precisando de atenção">
                                        <span id="count-ilegivel-${d.manifesto_id}">${d.total_ilegivel || 0}</span>
                                        <span class="visually-hidden">canhotos ilegíveis</span>
                                    </span>
                                </button>
                                <button class="btn btn-sm btn-outline-primary d-flex align-items-center gap-1"
                                    onclick="abrirRastreio('${d.manifesto_id}', '${d.motorista_nome || ''}', '${d.baixadas || 0}', '${d.total || 0}')">
                                    <i class="bi bi-geo-alt"></i> Rastrear
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        grid.insertAdjacentHTML('afterbegin', html);

        if (typeof reavaliarStacks === 'function') {
            reavaliarStacks();
        }
    }

    function updateBatteryIcon(mID, level, isCharging) {
        const container = document.getElementById(`battery-mft-${mID}`);
        if (!container) return;

        let iconClass = "bi-battery";
        let colorClass = "text-muted";

        if (level !== null && level !== undefined) {
            const l = parseInt(level);
            if (isCharging) {
                iconClass = "bi-battery-charging";
                colorClass = "text-success";
            } else {
                if (l > 80) { iconClass = "bi-battery-full"; colorClass = "text-success"; }
                else if (l > 50) { iconClass = "bi-battery-half"; colorClass = "text-info"; }
                else if (l > 20) { iconClass = "bi-battery-half"; colorClass = "text-warning"; }
                else { iconClass = "bi-battery-low"; colorClass = "text-danger"; }
            }
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

    socket.onclose = function () {
        console.log("WS desconectado. Reconectando em 5s...");
        const status = document.getElementById('status-ws');
        if (status) {
            status.classList.replace('bg-success', 'bg-danger');
            status.innerHTML = '<i class="fas fa-exclamation-triangle me-2"></i>DESCONECTADO';
        }
        setTimeout(conectarWebSocket, 5000);
    };

    socket.onerror = function (error) {
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

                // Pulsação do CARD baseada na idade do manifesto (não do login do motorista)
                // >= 24h: pulsa vermelho | >= 12h: pulsa amarelo | < 12h: sem pulsação
                card.classList.remove('card-danger-pulse', 'card-warning-pulse');
                if (diffCriacaoHours >= 24) {
                    card.classList.add('card-danger-pulse');
                    alertaContainer.innerHTML = `
                        <i class="bi bi-exclamation-triangle-fill text-danger fs-3" 
                           title="Manifesto criado há ${Math.floor(diffCriacaoHours / 24)} dia(s) e não finalizado" 
                           data-bs-toggle="tooltip" 
                           style="cursor: help; animation: pulse 2s infinite;"></i>
                    `;
                    if (typeof bootstrap !== 'undefined' && !alertaContainer.hasAttribute('data-tooltip-init')) {
                        new bootstrap.Tooltip(alertaContainer.querySelector('[data-bs-toggle="tooltip"]'));
                        alertaContainer.setAttribute('data-tooltip-init', 'true');
                    }
                } else if (diffCriacaoHours >= 12) {
                    card.classList.add('card-warning-pulse');
                    alertaContainer.innerHTML = `
                        <i class="bi bi-exclamation-triangle-fill text-warning fs-3" 
                           title="Manifesto aberto há ${Math.floor(diffCriacaoHours)}h sem finalizar" 
                           data-bs-toggle="tooltip" 
                           style="cursor: help; animation: pulse 2s infinite;"></i>
                    `;
                    if (typeof bootstrap !== 'undefined' && !alertaContainer.hasAttribute('data-tooltip-init')) {
                        new bootstrap.Tooltip(alertaContainer.querySelector('[data-bs-toggle="tooltip"]'));
                        alertaContainer.setAttribute('data-tooltip-init', 'true');
                    }
                } else {
                    alertaContainer.innerHTML = '';
                }
            } catch (e) {
                console.error('Erro na data de criação', e);
            }
        }

        const statusManifesto = elSinal.getAttribute('data-status') || (card.getAttribute('data-status'));
        if (statusManifesto === 'AGUARDANDO') {
            elSinal.innerHTML = `
                <div style="border: 1px solid #ffc107; background-color: rgba(255, 193, 7, 0.15); border-radius: 20px; padding: 2px 10px; display: inline-block; min-width: 80px; text-align: center;">
                    <i class="fas fa-hourglass-half" style="color: #b78103; font-size: 9px; vertical-align: middle; margin-right: 4px;"></i>
                    <span style="color: #856404; font-weight: bold; font-size: 11px;">AGUARDANDO</span>
                </div>
                <div style="font-size: 11px; color: #6c757d; margin-top: 4px; text-align: center; font-weight: 500;">
                    Não iniciado
                </div>
            `;
            card.classList.remove('card-danger-pulse', 'card-warning-pulse');
            return;
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
            card.classList.remove('card-danger-pulse', 'card-warning-pulse');
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

            if (diffHours <= 1.5 || diffMs < 0) { // < 0 caso horário do celular esteja à frente do servidor
                bgColor = 'rgba(25, 135, 84, 0.1)'; // green soft
                textColor = '#198754';
            } else if (diffHours <= 4) {
                bgColor = 'rgba(255, 193, 7, 0.1)'; // yellow soft
                textColor = '#ffc107';
            } else {
                bgColor = 'rgba(220, 53, 69, 0.1)'; // red soft
                textColor = '#dc3545';
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

            // Pulsação do card controlada apenas pela idade do manifesto (bloco acima)
        } catch (e) {
            console.error('Erro na data Torre', e);
        }
    });
}

// --- FUNÇÕES DO MAPA REAL-TIME ---

function atualizarTooltipEPopupMarcador(motoristaNome, lastSeen, battery, network, isCharging) {
    if (!marcadorMotorista) return;

    let timeStr = '--';
    if (lastSeen) {
        try {
            timeStr = (typeof lastSeen === 'string' && lastSeen.includes(':') && lastSeen.length <= 5)
                ? lastSeen
                : new Date(lastSeen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            if (timeStr === 'Invalid Date') timeStr = lastSeen;
        } catch (e) {
            timeStr = lastSeen;
        }
    }

    const nome = motoristaNome || motoristaNomeAtual || 'Motorista';

    const contentHover = `<div style="text-align: center; padding: 2px 4px; font-family: system-ui, -apple-system, sans-serif;">
        <strong style="color: #212529; font-size: 13px;">${nome}</strong>
        <div style="color: #0d6efd; font-size: 12px; font-weight: bold; margin-top: 2px;">
            <i class="fas fa-clock"></i> Último Sinal: ${timeStr}
        </div>
    </div>`;

    const contentClick = `<div style="text-align: center; padding: 4px 6px; min-width: 170px; font-family: system-ui, -apple-system, sans-serif;">
        <div style="font-weight: bold; font-size: 14px; color: #212529; margin-bottom: 6px;">
            🚚 ${nome}
        </div>
        <div style="font-size: 13px; line-height: 1.6; color: #495057; text-align: left; border-top: 1px solid #eee; padding-top: 6px; margin-top: 4px;">
            <div><i class="fas fa-clock text-primary me-1"></i> <strong>Último Sinal:</strong> <span class="badge bg-primary" style="font-size: 11px;">${timeStr}</span></div>
            ${battery !== null && battery !== undefined ? `<div style="margin-top:2px;"><i class="fas fa-battery-half text-success me-1"></i> <strong>Bateria:</strong> ${battery}% ${isCharging ? '⚡' : ''}</div>` : ''}
            ${network ? `<div style="margin-top:2px;"><i class="fas fa-signal text-info me-1"></i> <strong>Sinal:</strong> ${network}</div>` : ''}
        </div>
    </div>`;

    if (marcadorMotorista.getTooltip()) {
        marcadorMotorista.setTooltipContent(contentHover);
    } else {
        marcadorMotorista.bindTooltip(contentHover, {
            direction: 'top',
            offset: [0, -20],
            opacity: 0.95
        });
    }

    if (marcadorMotorista.getPopup()) {
        marcadorMotorista.setPopupContent(contentClick);
    } else {
        marcadorMotorista.bindPopup(contentClick);
    }
}

function abrirRastreamentoRealTime(manifestoId, motoristaNome, initialLat, initialLng) {
    monitorandoManifestoId = manifestoId.toString();
    motoristaNomeAtual = motoristaNome || '';
    document.getElementById('rastreamento-titulo').innerText = `Rastreando: ${motoristaNome}`;
    document.getElementById('rastreamento-mft').innerText = manifestoId;

    const modal = new bootstrap.Modal(document.getElementById('modalRastreamento'));
    modal.show();

    // Aguarda o modal abrir para inicializar o mapa (Leaflet precisa do container visível)
    document.getElementById('modalRastreamento').addEventListener('shown.bs.modal', function () {
        // Busca a posição atual do caminhão via API REST
        fetch(`/api/rastreio/${manifestoId}/`)
            .then(res => res.ok ? res.json() : Promise.reject('Erro HTTP'))
            .then(data => {
                let lat = initialLat;
                let lng = initialLng;
                let battery = null;
                let network = '';
                let lastSeen = null;
                let isCharging = false;

                // Se a API retornou posição atual do GPS nativo, usa ela
                if (data.posicao_atual) {
                    lat = data.posicao_atual.lat;
                    lng = data.posicao_atual.lng;
                    battery = data.posicao_atual.battery;
                    network = data.posicao_atual.network;
                    lastSeen = data.posicao_atual.last_seen;
                    isCharging = data.posicao_atual.is_charging || false;
                }

                // Fallback: tenta ler dos atributos data-* da tabela (se existir)
                const tr = document.querySelector(`tr[data-manifesto-id="${manifestoId}"]`);
                if (tr) {
                    lat = lat || tr.getAttribute('data-lat');
                    lng = lng || tr.getAttribute('data-lng');
                    battery = battery || tr.getAttribute('data-bateria');
                    network = network || tr.getAttribute('data-rede');
                    lastSeen = lastSeen || tr.getAttribute('data-ultimo-acesso');
                }

                initMapaRastreamento(lat, lng);

                let timeStr = '--';
                if (lastSeen) {
                    try {
                        timeStr = (typeof lastSeen === 'string' && lastSeen.includes(':') && lastSeen.length <= 5)
                            ? lastSeen
                            : new Date(lastSeen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                        if (timeStr === 'Invalid Date') timeStr = lastSeen;
                    } catch (e) {
                        timeStr = lastSeen;
                    }
                }

                // Preenche o overlay de status
                document.getElementById('mapa-status-bat').innerText = battery ? battery + '%' : '--%';
                document.getElementById('mapa-status-rede').innerText = network || '--';
                document.getElementById('mapa-status-visto').innerText = timeStr;

                // Atualiza Tooltip (hover) e Popup (click) do ícone do caminhão
                atualizarTooltipEPopupMarcador(motoristaNome, lastSeen, battery, network, isCharging);
            })
            .catch(err => {
                console.error('Erro ao buscar posição atual:', err);
                // Fallback: inicializa com as coordenadas do template
                initMapaRastreamento(initialLat, initialLng);
                document.getElementById('mapa-status-bat').innerText = '--%';
                document.getElementById('mapa-status-rede').innerText = '--';
                document.getElementById('mapa-status-visto').innerText = '--';
                atualizarTooltipEPopupMarcador(motoristaNome, null, null, null, false);
            });
    }, { once: true });

    // Limpeza ao fechar
    document.getElementById('modalRastreamento').addEventListener('hidden.bs.modal', function () {
        monitorandoManifestoId = null;
        motoristaNomeAtual = '';
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
        marcadorMotorista.bindTooltip("Aguardando sinal de GPS...", { direction: 'top', offset: [0, -20] });
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

    let timeStr = '--';
    if (dados.last_seen) {
        try {
            timeStr = new Date(dados.last_seen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (e) {
            timeStr = dados.last_seen;
        }
    }
    document.getElementById('mapa-status-visto').innerText = timeStr;

// =========================================================
// SISTEMA DE PILHA INTELIGENTE DE CARDS POR MOTORISTA (STACK ENGINE)
// =========================================================
const stacksExpandidos = new Set();
let stackReevalTimeout = null;

function reavaliarStacks() {
    clearTimeout(stackReevalTimeout);
    stackReevalTimeout = setTimeout(() => {
        agruparCardsPorMotorista();
    }, 60);
}

function toggleStackMotorista(motId) {
    if (!motId) return;
    const idStr = String(motId);
    const expandir = !stacksExpandidos.has(idStr);
    
    if (expandir) {
        stacksExpandidos.add(idStr);
    } else {
        stacksExpandidos.delete(idStr);
    }
    
    // Atualiza a visualização local
    agruparCardsPorMotorista();

    // Sincroniza em tempo real com todas as outras telas da Torre via WebSocket
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            type: 'toggle_stack',
            motorista_id: idStr,
            expanded: expandir
        }));
    }
}

function agruparCardsPorMotorista() {
    const grid = document.getElementById('grid-monitoramento');
    if (!grid) return;

    // Pega todos os cards de manifesto presentes no DOM
    const allCards = Array.from(grid.querySelectorAll('.manifesto-card-item'));
    
    // Filtra apenas os cards da filial ativa no momento (ou todos se nenhuma estiver filtrada)
    const cardsFilial = allCards.filter(card => {
        const cFilial = card.getAttribute('data-filial-id');
        return !window.filialAtivaTorreId || String(cFilial) === String(window.filialAtivaTorreId);
    });

    // Agrupa por motorista_id
    const grupos = {};
    cardsFilial.forEach(card => {
        const motId = card.getAttribute('data-motorista-id');
        if (!motId) return;
        if (!grupos[motId]) grupos[motId] = [];
        grupos[motId].push(card);
    });

    // Processa cada grupo de motorista
    Object.entries(grupos).forEach(([motId, cardsDoMotorista]) => {
        // Se o motorista tem apenas 1 card, restaura visual normal
        if (cardsDoMotorista.length <= 1) {
            limparEfeitosStack(cardsDoMotorista[0]);
            cardsDoMotorista[0].style.display = '';
            return;
        }

        const isExpandido = stacksExpandidos.has(String(motId));

        // Ordenação inteligente: EM_TRANSPORTE primeiro, depois por data mais antiga (quem chegou antes)
        cardsDoMotorista.sort((a, b) => {
            const stA = a.getAttribute('data-status') || '';
            const stB = b.getAttribute('data-status') || '';
            if (stA === 'EM_TRANSPORTE' && stB !== 'EM_TRANSPORTE') return -1;
            if (stB === 'EM_TRANSPORTE' && stA !== 'EM_TRANSPORTE') return 1;

            const dtA = a.getAttribute('data-criacao') || '';
            const dtB = b.getAttribute('data-criacao') || '';
            return dtA.localeCompare(dtB);
        });

        if (isExpandido) {
            // EXPANDIDO: Mostra todos os cards lado a lado na grid
            cardsDoMotorista.forEach((card, index) => {
                card.style.display = '';
                limparEfeitosStack(card);
                card.classList.add('stack-expand-anim');
                aplicarBadgeStackExpandido(card, cardsDoMotorista.length, index + 1, motId);
            });
        } else {
            // EMPILHADO (COLAPSADO): Card prioritário na frente, demais escondidos
            const cardPrincipal = cardsDoMotorista[0];
            const cardsAtras = cardsDoMotorista.slice(1);

            cardPrincipal.style.display = '';
            limparEfeitosStack(cardPrincipal);
            aplicarEfeitosStackPrincipal(cardPrincipal, cardsDoMotorista.length, motId, cardsAtras);

            cardsAtras.forEach(card => {
                limparEfeitosStack(card);
                card.style.display = 'none';
            });
        }
    });

    // Para cards sem motorista_id, garante visibilidade
    cardsFilial.forEach(card => {
        const motId = card.getAttribute('data-motorista-id');
        if (!motId) {
            limparEfeitosStack(card);
            card.style.display = '';
        }
    });
}

function aplicarEfeitosStackPrincipal(card, total, motId, cardsAtras) {
    const innerCard = card.querySelector('.card');
    if (!innerCard) return;

    // Efeito de camadas visuais de cartas empilhadas
    if (total === 2) {
        innerCard.classList.add('card-stacked-layer-2');
    } else if (total >= 3) {
        innerCard.classList.add('card-stacked-layer-3plus');
    }

    // Badge com contagem e ícone de pilha
    let badge = card.querySelector('.badge-stack-toggle');
    if (!badge) {
        badge = document.createElement('div');
        badge.className = 'badge-stack-toggle shadow-sm';
        innerCard.appendChild(badge);
    }
    badge.classList.remove('is-expanded');
    badge.innerHTML = `<i class="bi bi-stack"></i> <span>${total}</span>`;
    badge.title = `${total} manifestos deste motorista. Clique para expandir os ${total} cards`;
    badge.onclick = (e) => {
        e.stopPropagation();
        badge.classList.add('badge-stack-toggle-pulse');
        toggleStackMotorista(motId);
    };

    // Faixa inferior (peek) mostrando números dos manifestos na fila
    const numerosManifestosAtras = cardsAtras.map(c => {
        const idMft = c.id.replace('card-mft-', '');
        return `#${idMft}`;
    }).join(', ');

    let peek = card.querySelector('.stack-peek-bar');
    if (!peek) {
        peek = document.createElement('div');
        peek.className = 'stack-peek-bar';
        innerCard.appendChild(peek);
    }
    peek.innerHTML = `<span><i class="bi bi-layers me-1 text-primary"></i> +${cardsAtras.length} na fila: <strong>${numerosManifestosAtras}</strong></span><i class="bi bi-chevron-down text-muted"></i>`;
    peek.title = `Clique para expandir todos os ${total} manifestos deste motorista`;
    peek.onclick = (e) => {
        e.stopPropagation();
        toggleStackMotorista(motId);
    };
}

function aplicarBadgeStackExpandido(card, total, posicao, motId) {
    const innerCard = card.querySelector('.card');
    if (!innerCard) return;

    let badge = card.querySelector('.badge-stack-toggle');
    if (!badge) {
        badge = document.createElement('div');
        badge.className = 'badge-stack-toggle is-expanded shadow-sm';
        innerCard.appendChild(badge);
    } else {
        badge.classList.add('is-expanded');
    }
    badge.innerHTML = `<i class="bi bi-x-circle me-1"></i> <span>Pilha ${posicao}/${total}</span>`;
    badge.title = `Clique para recolher todos os ${total} manifestos na pilha`;
    badge.onclick = (e) => {
        e.stopPropagation();
        badge.classList.add('badge-stack-toggle-pulse');
        toggleStackMotorista(motId);
    };
}

function limparEfeitosStack(card) {
    if (!card) return;
    const innerCard = card.querySelector('.card');
    if (innerCard) {
        innerCard.classList.remove('card-stacked-layer-2', 'card-stacked-layer-3plus');
    }
    const badge = card.querySelector('.badge-stack-toggle');
    if (badge) badge.remove();
    const peek = card.querySelector('.stack-peek-bar');
    if (peek) peek.remove();
    card.classList.remove('stack-expand-anim');
}

// Inicializa ou reavalia pilhas automaticamente
document.addEventListener("DOMContentLoaded", function () {
    if (typeof reavaliarStacks === 'function') {
        reavaliarStacks();
    }
});

conectarWebSocket();