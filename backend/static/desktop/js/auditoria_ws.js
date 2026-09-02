/**
 * auditoria_ws.js - RXTrack
 * Conexão em Tempo Real (WebSocket) para o Cockpit de Auditoria de Processos.
 * Atualiza status de hardware (bateria, rede, sinal) e baixas instantaneamente.
 */

(function() {
    let ws = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 15;
    const baseDelay = 2000;

    function conectarWebSocket() {
        const config = window.AUDITORIA_CONFIG || {};
        const filialId = config.filialId || 'todas';
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/painel-logistico/${filialId}/`;

        console.log(`📡 [Auditoria WS] Conectando a ${wsUrl}...`);
        
        try {
            ws = new WebSocket(wsUrl);

            ws.onopen = function() {
                console.log(`✅ [Auditoria WS] Conectado ao grupo filial: ${filialId}`);
                reconnectAttempts = 0;
                atualizarBadgeConexao(true);
            };

            ws.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    processarMensagemWS(data);
                } catch (e) {
                    console.error("❌ [Auditoria WS] Erro ao parsear mensagem:", e);
                }
            };

            ws.onclose = function(e) {
                console.warn(`⚠️ [Auditoria WS] Desconectado (Código: ${e.code}). Tentando reconectar...`);
                atualizarBadgeConexao(false);
                tentarReconectar();
            };

            ws.onerror = function(err) {
                console.error("❌ [Auditoria WS] Erro na conexão:", err);
                ws.close();
            };
        } catch (err) {
            console.error("❌ [Auditoria WS] Falha ao iniciar WebSocket:", err);
            tentarReconectar();
        }
    }

    function tentarReconectar() {
        if (reconnectAttempts < maxReconnectAttempts) {
            reconnectAttempts++;
            const delay = Math.min(30000, baseDelay * Math.pow(1.5, reconnectAttempts));
            console.log(`🔄 [Auditoria WS] Tentativa ${reconnectAttempts}/${maxReconnectAttempts} em ${Math.round(delay/1000)}s...`);
            setTimeout(conectarWebSocket, delay);
        } else {
            console.error("❌ [Auditoria WS] Limite de tentativas de reconexão atingido.");
        }
    }

    function atualizarBadgeConexao(conectado) {
        const badge = document.getElementById('wsConnectionBadge');
        if (badge) {
            if (conectado) {
                badge.className = 'badge bg-success bg-opacity-10 text-success border border-success d-inline-flex align-items-center gap-1';
                badge.innerHTML = '<span class="pulse-dot bg-success"></span> AO VIVO (WS)';
            } else {
                badge.className = 'badge bg-warning bg-opacity-10 text-warning border border-warning d-inline-flex align-items-center gap-1';
                badge.innerHTML = '<span class="pulse-dot bg-warning"></span> RECONECTANDO...';
            }
        }
    }

    function processarMensagemWS(data) {
        const tipo = data.type || data.action;

        // 1. Atualização de Telemetria e Hardware do Motorista (Heartbeat)
        if (tipo === 'atualizar_status_motorista' || data.bateria !== undefined) {
            atualizarHardwareMotorista(data);
        }

        // 2. Baixa realizada ou atualização do manifesto
        if (tipo === 'atualizar_painel' || tipo === 'baixa_registrada' || data.manifesto_id) {
            atualizarProgressoManifesto(data);
        }
    }

    function atualizarHardwareMotorista(data) {
        const motoristaId = data.motorista_id;
        const cpf = data.cpf;
        const bateria = data.bateria;
        const rede = data.rede;
        const isCharging = data.is_charging;

        // Busca os elementos na tela pelo motorista ID ou CPF
        const cards = document.querySelectorAll(`[data-motorista-id="${motoristaId}"], [data-motorista-cpf="${cpf}"]`);
        cards.forEach(card => {
            // Atualiza Bateria
            if (bateria !== undefined && bateria !== null) {
                const batEl = card.querySelector('.motorista-bateria-val');
                const batBar = card.querySelector('.motorista-bateria-bar');
                const batIcon = card.querySelector('.motorista-bateria-icon');
                
                if (batEl) batEl.innerText = `${bateria}%`;
                if (batBar) {
                    batBar.style.width = `${bateria}%`;
                    batBar.className = `progress-bar ${bateria <= 15 ? 'bg-danger' : (bateria <= 35 ? 'bg-warning' : 'bg-success')}`;
                }
                if (batIcon) {
                    batIcon.className = isCharging ? 'bi bi-lightning-charge-fill text-warning' : 'bi bi-battery-charging';
                }
            }

            // Atualiza Rede
            if (rede) {
                const redeBadge = card.querySelector('.motorista-rede-badge');
                if (redeBadge) {
                    redeBadge.innerText = rede;
                    redeBadge.className = `badge ${rede === '5G' || rede === 'WIFI' ? 'bg-primary' : (rede === '4G' ? 'bg-info text-dark' : 'bg-secondary')} bg-opacity-25 border`;
                }
            }

            // Atualiza Sinal
            const sinalBadge = card.querySelector('.motorista-sinal-badge');
            const sinalTexto = card.querySelector('.motorista-sinal-texto');
            if (sinalBadge) {
                sinalBadge.className = 'badge bg-success bg-opacity-10 text-success border-success border rounded-pill px-2 py-1';
                sinalBadge.innerHTML = '<i class="bi bi-circle-fill me-1" style="font-size: 0.5rem;"></i> Agora';
            }
            if (sinalTexto) {
                sinalTexto.innerText = 'Sinal agora';
            }

            // Efeito visual sutil de pulso
            card.classList.add('card-updated-pulse');
            setTimeout(() => card.classList.remove('card-updated-pulse'), 1500);
        });
    }

    function atualizarProgressoManifesto(data) {
        const manifestoId = data.manifesto_id || data.id;
        const total = data.total_notas;
        const baixadas = data.notas_baixadas || data.baixadas;
        const pendentes = data.notas_pendentes || (total !== undefined && baixadas !== undefined ? total - baixadas : null);

        const card = document.querySelector(`[data-manifesto-id="${manifestoId}"]`);
        if (card && total !== undefined && baixadas !== undefined) {
            const progresso = Math.round((baixadas / total) * 100);
            
            const progBar = card.querySelector('.manifesto-progresso-bar');
            const progText = card.querySelector('.manifesto-progresso-text');
            const pendentesEl = card.querySelector('.manifesto-pendentes-text');

            if (progBar) progBar.style.width = `${progresso}%`;
            if (progText) progText.innerText = `${progresso}%`;
            if (pendentesEl && pendentes !== null) {
                pendentesEl.innerText = `${pendentes} nota(s) pendente(s)`;
            }

            // Efeito visual de atualização
            card.classList.add('card-updated-pulse');
            setTimeout(() => card.classList.remove('card-updated-pulse'), 1500);
        }
    }

    // Inicia ao carregar a página
    document.addEventListener('DOMContentLoaded', function() {
        conectarWebSocket();
    });
})();

/**
 * Drawer 360º de Detalhes Técnicos do Motorista & Manifesto
 */
async function abrirDrawer360(manifestoId) {
    const drawerEl = document.getElementById('drawerAuditoria360');
    if (!drawerEl) return;

    const bsOffcanvas = bootstrap.Offcanvas.getOrCreateInstance(drawerEl);
    bsOffcanvas.show();

    // Mostra loading e esconde conteúdo
    document.getElementById('drawerLoading').style.display = 'block';
    document.getElementById('drawerContent').style.display = 'none';

    try {
        const res = await fetch(`/auditoria/api/detalhes-360/${manifestoId}/`);
        if (!res.ok) throw new Error("Erro ao carregar dados.");
        const data = await res.json();
        renderizarDrawer360(data);
    } catch (err) {
        console.error("Erro ao carregar drawer 360:", err);
        Swal.fire({
            icon: 'error',
            title: 'Erro de Comunicação',
            text: 'Não foi possível carregar a telemetria do motorista.',
            confirmButtonColor: '#0d6efd'
        });
        bsOffcanvas.hide();
    }
}

function renderizarDrawer360(data) {
    document.getElementById('drawerLoading').style.display = 'none';
    document.getElementById('drawerContent').style.display = 'block';

    // Cabeçalho
    document.getElementById('drawerMotoristaNome').innerText = data.motorista_nome || 'Não Identificado';
    document.getElementById('drawerManifestoNum').innerText = `#${data.obj ? data.obj.numero_manifesto : (data.timeline && data.timeline[0] ? data.timeline[0].numero_nota : '')}`;
    document.getElementById('drawerFilialNome').innerText = data.filial_nome || 'Matriz';
    document.getElementById('drawerPlaca').innerText = data.placa || '--';
    document.getElementById('drawerCategoria').innerText = data.motorista_categoria || 'OUTROS';
    
    // Telemetria
    document.getElementById('drawerBateriaVal').innerText = data.bateria !== null && data.bateria !== undefined ? `${data.bateria}%` : '--%';
    document.getElementById('drawerRedeVal').innerText = data.rede || '4G';
    document.getElementById('drawerSinalVal').innerText = data.status_texto || 'Sem sinal';
    document.getElementById('drawerRitmoVal').innerText = `${data.ritmo_entregas_hora || 0} n/h`;
    document.getElementById('drawerEtaVal').innerText = data.eta_str || '--:--';
    document.getElementById('drawerScoreVal').innerText = `${data.score || 100}/100`;

    // WhatsApp Action
    const zapBtn = document.getElementById('drawerWhatsappBtn');
    if (zapBtn) {
        if (data.motorista_telefone) {
            const telLimpo = data.motorista_telefone.replace(/\D/g, '');
            const msg = encodeURIComponent(`Olá ${data.motorista_nome}, aqui é do monitoramento operacional da ${data.filial_nome}. Notamos sua viagem no manifesto #${data.obj ? data.obj.numero_manifesto : ''}. Está tudo bem com sua rota?`);
            zapBtn.href = `https://wa.me/55${telLimpo}?text=${msg}`;
            zapBtn.classList.remove('disabled');
        } else {
            zapBtn.removeAttribute('href');
            zapBtn.classList.add('disabled');
        }
    }

    // Timeline de Notas
    const timelineContainer = document.getElementById('drawerTimelineNotas');
    timelineContainer.innerHTML = '';

    if (!data.timeline || data.timeline.length === 0) {
        timelineContainer.innerHTML = '<p class="text-muted text-center py-4">Nenhuma nota vinculada a este manifesto.</p>';
        return;
    }

    data.timeline.forEach((item, idx) => {
        const isBaixada = item.ja_baixada;
        const isSucesso = item.status === 'BAIXADA';
        const isOcorrencia = item.status === 'OCORRENCIA';
        
        let statusBadge = '<span class="badge bg-secondary">Pendente</span>';
        if (isSucesso) {
            statusBadge = '<span class="badge bg-success">Entregue</span>';
        } else if (isOcorrencia) {
            statusBadge = `<span class="badge bg-danger">${item.ocorrencia_nome || 'Ocorrência'}</span>`;
        }

        let sacBadge = '';
        if (item.motivo_baixa === 'MOTORISTA_DESLEIXO') {
            sacBadge = '<span class="badge bg-danger ms-1" style="font-size:0.65rem;">PENALIDADE SAC</span>';
        } else if (item.motivo_baixa === 'APP_ERROR') {
            sacBadge = '<span class="badge bg-info text-dark ms-1" style="font-size:0.65rem;">ERRO APP</span>';
        }

        let fotoHtml = '';
        if (item.foto_url) {
            fotoHtml = `
                <a href="${item.foto_url}" target="_blank" class="btn btn-xs btn-outline-primary mt-2 d-inline-flex align-items-center gap-1" style="font-size: 0.75rem;">
                    <i class="bi bi-image"></i> Ver Canhoto
                </a>
            `;
        }

        let acaoSacHtml = '';
        if (!isBaixada) {
            acaoSacHtml = `
                <button class="btn btn-xs btn-outline-danger mt-2 ms-1" style="font-size: 0.75rem;" onclick="abrirModalBaixaSAC('${item.id}', '${item.numero_nota}', '${escapeHtml(item.destinatario || '')}')">
                    <i class="bi bi-shield-exclamation"></i> Baixar via SAC
                </button>
            `;
        }

        const timelineItem = document.createElement('div');
        timelineItem.className = 'timeline-item mb-3 pb-3 border-bottom position-relative ps-4';
        timelineItem.innerHTML = `
            <div class="timeline-dot bg-${isSucesso ? 'success' : (isOcorrencia ? 'danger' : 'secondary')}"></div>
            <div class="d-flex justify-content-between align-items-start mb-1">
                <div>
                    <span class="fw-bold fs-6">NF #${item.numero_nota}</span>
                    <span class="badge bg-light text-dark border ms-1">${item.tipo_operacao}</span>
                    ${statusBadge}
                    ${sacBadge}
                </div>
                <small class="text-muted">${item.data_baixa || 'Aguardando'}</small>
            </div>
            <div class="small text-muted mb-1">
                <i class="bi bi-person me-1"></i>${escapeHtml(item.destinatario || 'Não informado')}
            </div>
            <div class="small text-muted mb-2">
                <i class="bi bi-geo-alt me-1"></i>${escapeHtml(item.endereco || 'Endereço não informado')}
            </div>
            ${item.recebedor ? `<div class="small text-dark fw-semibold"><i class="bi bi-check2-circle text-success me-1"></i>Recebido por: ${escapeHtml(item.recebedor)}</div>` : ''}
            ${item.observacao ? `<div class="small text-muted fst-italic">"${escapeHtml(item.observacao)}"</div>` : ''}
            <div class="d-flex align-items-center flex-wrap">
                ${fotoHtml}
                ${acaoSacHtml}
            </div>
        `;
        timelineContainer.appendChild(timelineItem);
    });
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
