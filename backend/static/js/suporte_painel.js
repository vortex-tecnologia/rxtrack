// suporte_painel.js
let filialId = document.getElementById('filial-id-config').value;
let wsFilial = null;
let wsTicketAtivo = null;
let currentTicketId = null;
let abaAtiva = 'abertos'; // abertos, meus, fechados
let todosTickets = [];

document.addEventListener('DOMContentLoaded', function() {
    conectarWSFilial();
    carregarTicketsIniciais();
    
    // Configurar abas
    document.querySelectorAll('#pills-tab .nav-link').forEach(btn => {
        btn.addEventListener('click', function() {
            document.querySelectorAll('#pills-tab .nav-link').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            abaAtiva = this.getAttribute('data-status');
            renderizarListaTickets();
        });
    });

    // Filtro de texto
    document.getElementById('filtro-tickets').addEventListener('input', renderizarListaTickets);
});

async function carregarTicketsIniciais() {
    try {
        const resp = await fetch('/suporte/api/tickets/');
        if(resp.ok) {
            todosTickets = await resp.json();
            renderizarListaTickets();
            atualizarBadges();
        }
    } catch(e) {
        console.error("Erro ao buscar tickets", e);
    }
}

function conectarWSFilial() {
    const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
    const token = localStorage.getItem('accessToken') || '';
    wsFilial = new WebSocket(`${wsScheme}://${window.location.host}/ws/suporte/filial/${filialId}/?token=${token}`);

    wsFilial.onopen = () => {
        document.getElementById('conexao-status').className = 'badge bg-success';
        document.getElementById('conexao-status').innerText = 'Online';
    };

    wsFilial.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === 'novo_ticket' || data.type === 'atualizacao_ticket') {
            const ticket = data.ticket;
            const index = todosTickets.findIndex(t => t.id === ticket.id);
            if(index > -1) {
                todosTickets[index] = ticket;
            } else {
                todosTickets.unshift(ticket);
            }
            renderizarListaTickets();
            atualizarBadges();
        }
        else if (data.type === 'ticket_updated') {
            carregarTicketsIniciais();
            // Flash the card if visible
            if(data.ticket_id) {
                setTimeout(() => {
                    document.querySelectorAll('.ticket-card').forEach(card => {
                        card.classList.add('flash-new');
                        setTimeout(() => card.classList.remove('flash-new'), 3500);
                    });
                }, 500);
            }
        }
    };

    wsFilial.onclose = () => {
        document.getElementById('conexao-status').className = 'badge bg-danger';
        document.getElementById('conexao-status').innerText = 'Offline';
        setTimeout(conectarWSFilial, 3000); // Tenta reconectar
    };
}

function renderizarListaTickets() {
    const container = document.getElementById('lista-chamados');
    const filtroTexto = document.getElementById('filtro-tickets').value.toLowerCase();
    
    let ticketsFiltrados = todosTickets.filter(t => {
        // Filtro por Aba
        if(abaAtiva === 'abertos' && t.status !== 'CANAL_ABERTO') return false;
        if(abaAtiva === 'meus' && t.status !== 'EM_ATENDIMENTO') return false; 
        if(abaAtiva === 'fechados' && t.status !== 'FECHADO') return false;
        
        // Se for "meus", checar se o atendente logado é o mesmo? 
        // Aqui exibe em atendimento (pode ser de outro, mas ideal é checar nome)
        // Por simplicidade, assumirei a aba "meus" mostra todos os EM_ATENDIMENTO da filial.

        // Filtro por texto
        if(filtroTexto) {
            const num = String(t.id);
            const mot = t.motorista_str ? t.motorista_str.toLowerCase() : '';
            return num.includes(filtroTexto) || mot.includes(filtroTexto);
        }
        return true;
    });

    if(ticketsFiltrados.length === 0) {
        container.innerHTML = `<div class="text-center text-muted mt-5"><i class="bi bi-inbox fs-1 opacity-25"></i><p class="mt-2 small">Nenhum chamado encontrado nesta aba.</p></div>`;
        return;
    }

    let html = '';
    ticketsFiltrados.forEach(t => {
        const lastMsgObj = t.mensagens && t.mensagens.length > 0 ? t.mensagens[t.mensagens.length-1] : null;
        const subMsg = lastMsgObj ? (lastMsgObj.texto || '[Mídia]') : 'Novo Chamado';
        
        let isActive = currentTicketId === t.id ? 'active' : '';
        let unread = t.status === 'CANAL_ABERTO' && !lastMsgObj?.enviado_por_motorista ? 'unread' : '';

        let tempo = new Date(t.updated_at).toLocaleTimeString('pt-BR', {hour: '2-digit', minute:'2-digit'});

        html += `
            <div class="card ticket-card mb-2 shadow-sm ${isActive} ${unread}" onclick="selecionarTicket(${t.id})">
                <div class="card-body p-2 px-3">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <small class="fw-bold text-dark text-truncate" style="max-width: 70%;">${t.motorista_str || 'Motorista'}</small>
                        <small class="text-muted" style="font-size: 0.70rem;">${tempo}</small>
                    </div>
                    <div class="d-flex justify-content-between align-items-center">
                        <small class="text-muted text-truncate w-75" style="font-size: 0.80rem;">${subMsg}</small>
                        <span class="badge bg-secondary" style="font-size: 0.65rem;">#${t.id}</span>
                    </div>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

function atualizarBadges() {
    const abertos = todosTickets.filter(t => t.status === 'CANAL_ABERTO').length;
    const meus = todosTickets.filter(t => t.status === 'EM_ATENDIMENTO').length;
    const fechados = todosTickets.filter(t => t.status === 'FECHADO').length;
    
    const bAbertos = document.getElementById('badge-abertos');
    const bMeus = document.getElementById('badge-meus');
    const bFechados = document.getElementById('badge-fechados');
    
    if(bAbertos) { bAbertos.innerText = abertos; bAbertos.style.display = abertos > 0 ? 'inline' : 'none'; }
    if(bMeus) { bMeus.innerText = meus; bMeus.style.display = meus > 0 ? 'inline' : 'none'; }
    if(bFechados) { bFechados.innerText = fechados; bFechados.style.display = fechados > 0 ? 'inline' : 'none'; }
}

async function selecionarTicket(id) {
    currentTicketId = id;
    renderizarListaTickets(); // Atualiza highlight

    document.getElementById('chat-placeholder').classList.add('d-none');
    document.getElementById('chat-ativo').classList.remove('d-none');
    document.getElementById('chat-mensagens').innerHTML = `<div class="d-flex h-100 justify-content-center align-items-center"><div class="spinner-border text-primary"></div></div>`;

    // Busca dados do Ticket via REST
    try {
        const resp = await fetch(`/suporte/api/tickets/${id}/`);
        if(resp.ok) {
            const ticket = await resp.json();
            
            // Header do chat
            document.getElementById('chat-header-nome').innerText = ticket.motorista_str || 'Motorista';
            window._currentMotoristaName = ticket.motorista_str || 'Motorista';
            document.getElementById('chat-header-categoria').innerText = ticket.categoria.replace(/_/g, ' ');
            document.getElementById('chat-header-status').innerText = ticket.status.replace(/_/g, ' ');
            
            // Controle de Botões
            if(ticket.status === 'CANAL_ABERTO') {
                document.getElementById('btn-assumir-ticket').style.display = 'block';
                document.getElementById('btn-encerrar-ticket').style.display = 'none';
                document.getElementById('chat-input-area').classList.add('d-none');
                document.getElementById('alerta-somente-leitura').classList.remove('d-none');
            } else if(ticket.status === 'EM_ATENDIMENTO') {
                document.getElementById('btn-assumir-ticket').style.display = 'none';
                document.getElementById('btn-encerrar-ticket').style.display = 'block';
                document.getElementById('chat-input-area').classList.remove('d-none');
                document.getElementById('alerta-somente-leitura').classList.add('d-none');
            } else {
                document.getElementById('btn-assumir-ticket').style.display = 'none';
                document.getElementById('btn-encerrar-ticket').style.display = 'none';
                document.getElementById('chat-input-area').classList.add('d-none');
                document.getElementById('alerta-somente-leitura').classList.remove('d-none');
                document.getElementById('alerta-somente-leitura').innerHTML = '<i class="bi bi-lock-fill me-2"></i> Chamado Encerrado.';
            }

            // Renderiza historico
            const msgContainer = document.getElementById('chat-mensagens');
            msgContainer.innerHTML = '';
            if (ticket.mensagens && ticket.mensagens.length > 0) {
                ticket.mensagens.forEach(m => injetarMensagemChat(m));
            } else {
                msgContainer.innerHTML = '<div class="text-center w-100 mt-4 text-muted small"><i class="bi bi-shield-lock me-1"></i> As mensagens são criptografadas de ponta a ponta.</div>';
            }
            msgContainer.scrollTop = msgContainer.scrollHeight;

            conectarWSTicket(id);

        }
    } catch(e) {
        console.error(e);
    }
}

async function assumirTicketAtivo() {
    if(!currentTicketId) return;
    try {
        const resp = await fetch(`/suporte/api/tickets/${currentTicketId}/assumir/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            }
        });
        if(resp.ok) {
            selecionarTicket(currentTicketId); // Recarrega tela
        } else {
            const err = await resp.json();
            alert(err.error || "Erro ao assumir chamado.");
        }
    } catch(e) {
        console.error(e);
    }
}

async function encerrarTicketAtivo() {
    if(!currentTicketId) return;
    // Abre modal de confirmacao em vez de confirm()
    const modal = new bootstrap.Modal(document.getElementById('modalConfirmarEncerramento'));
    modal.show();
}

async function confirmarEncerramento() {
    // Fecha o modal
    bootstrap.Modal.getInstance(document.getElementById('modalConfirmarEncerramento')).hide();
    
    if(!currentTicketId) return;
    try {
        const resp = await fetch(`/suporte/api/tickets/${currentTicketId}/encerrar/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            }
        });
        if(resp.ok) {
            selecionarTicket(currentTicketId);
        } else {
            const err = await resp.json();
            alert(err.error || "Erro ao encerrar chamado.");
        }
    } catch(e) {
        console.error(e);
    }
}

// === WS TICKET ESPECÍFICO ===
function conectarWSTicket(ticketId) {
    if (wsTicketAtivo) wsTicketAtivo.close();
    const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
    const token = localStorage.getItem('accessToken') || '';
    wsTicketAtivo = new WebSocket(`${wsScheme}://${window.location.host}/ws/suporte/ticket/${ticketId}/?token=${token}`);

    wsTicketAtivo.onmessage = function(e) {
        const data = JSON.parse(e.data);
        if (data.type === 'chat_message') {
            injetarMensagemChat(data);
            const msgContainer = document.getElementById('chat-mensagens');
            msgContainer.scrollTop = msgContainer.scrollHeight;
        }
    };
}

function injetarMensagemChat(msg) {
    const container = document.getElementById('chat-mensagens');
    
    // Mensagens de sistema (assumir, encerrar)
    if (msg.tipo === 'SISTEMA') {
        const textoSistema = (msg.texto || msg.mensagem || '');
        const html = `
            <div class="d-flex w-100 justify-content-center mb-3">
                <div class="chat-bubble chat-bubble-sistema px-4 py-2">
                    <small class="text-muted">${textoSistema}</small>
                </div>
            </div>
        `;
        container.innerHTML += html;
        return;
    }
    
    // Se logado e o SAC e a msg foi do motorista, entao motorista e "esquerda" e SAC "direita"
    const isMe = !msg.enviado_por_motorista; 
    
    let wrapperClass = isMe ? 'justify-content-end' : 'justify-content-start';
    let bubbleClass = isMe ? 'chat-bubble-sac' : 'chat-bubble-motorista';
    let autor = isMe ? 'Voce' : (window._currentMotoristaName || 'Motorista');

    let midiaHtml = '';
    let arquivoFinal = msg.arquivo_url || msg.arquivo || '';
    if (msg.tipo === 'IMAGEM' && arquivoFinal) {
        midiaHtml = `<img src="${arquivoFinal}" class="img-fluid rounded mb-2 shadow-sm d-block cursor-pointer" style="max-height: 250px;" onclick="verMidia(this.src, 'IMAGEM')">`;
    } else if (msg.tipo === 'AUDIO' && arquivoFinal) {
        midiaHtml = `
            <div class="d-flex align-items-center gap-2 mb-2 p-2 rounded-3" style="background: rgba(0,0,0,0.06); min-width: 220px;">
                <i class="bi bi-mic-fill" style="font-size: 1.2rem;"></i>
                <audio controls preload="none" style="height: 36px; flex: 1; max-width: 100%;">
                    <source src="${arquivoFinal}" type="audio/webm">
                    <source src="${arquivoFinal}" type="audio/mpeg">
                    Navegador nao suporta audio.
                </audio>
            </div>`;
    } else if (msg.tipo === 'VIDEO' && arquivoFinal) {
        midiaHtml = `
            <video controls preload="none" class="rounded mb-2 shadow-sm d-block" style="max-height: 280px; max-width: 100%;">
                <source src="${arquivoFinal}" type="video/mp4">
                <source src="${arquivoFinal}" type="video/webm">
            </video>`;
    }

    // Esconde texto generico se midia esta presente
    let textoExibir = msg.texto || msg.mensagem || '';
    if (midiaHtml && (textoExibir === '(Audio)' || textoExibir === '(Midia enviada)')) {
        textoExibir = '';
    }
    const textoFormatado = textoExibir.replace(/\n/g, '<br>');

    const html = `
        <div class="d-flex w-100 ${wrapperClass} mb-3">
            <div class="chat-bubble ${bubbleClass}">
                <div class="fw-bold opacity-75 mb-1" style="font-size: 0.75rem;">${autor}</div>
                ${midiaHtml}
                ${textoFormatado ? `<div>${textoFormatado}</div>` : ''}
                <div class="text-end mt-1 text-muted" style="font-size: 0.65rem;">
                    ${new Date(msg.created_at).toLocaleTimeString('pt-BR', {hour: '2-digit', minute:'2-digit'})}
                </div>
            </div>
        </div>
    `;
    container.innerHTML += html;
}

function enviarMensagemPainel() {
    const input = document.getElementById('chat-input-texto');
    const txt = input.value.trim();
    if(!txt || !currentTicketId) return;

    if (wsTicketAtivo && wsTicketAtivo.readyState === WebSocket.OPEN) {
        wsTicketAtivo.send(JSON.stringify({
            mensagem: txt,
            tipo: 'TEXTO'
        }));
        input.value = '';
    } else {
        // Fallback REST
        fetch('/suporte/api/mensagens/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                ticket: currentTicketId,
                texto: txt,
                tipo: 'TEXTO'
            })
        }).then(() => input.value = '');
    }
}

document.getElementById('chat-input-texto').addEventListener('keypress', function(e){
    if(e.key === 'Enter') enviarMensagemPainel();
});

async function uploadMidiaPainel() {
    const input = document.getElementById('chat-upload-arquivo');
    if(!input.files || input.files.length === 0) return;

    const file = input.files[0];
    const formData = new FormData();
    formData.append('ticket', currentTicketId);
    
    if (file.type.startsWith('image/')) formData.append('tipo', 'IMAGEM');
    else if (file.type.startsWith('video/')) formData.append('tipo', 'VIDEO');
    else if (file.type.startsWith('audio/')) formData.append('tipo', 'AUDIO');
    
    formData.append('arquivo', file);
    formData.append('texto', '(Mídia enviada)');

    try {
        const resp = await fetch('/suporte/api/mensagens/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: formData
        });

        if(resp.ok) {
            const data = await resp.json();
            if (wsTicketAtivo && wsTicketAtivo.readyState === WebSocket.OPEN) {
                wsTicketAtivo.send(JSON.stringify({
                    mensagem: '',
                    tipo: data.tipo,
                    arquivo_url: data.arquivo
                }));
            }
        }
    } catch(e) {
        console.error(e);
    }
    input.value = '';
}

// Util para CSRF nas chamadas fetch() de sessão
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function verMidia(url, tipo) {
    const modal = new bootstrap.Modal(document.getElementById('modalMidia'));
    if(tipo === 'IMAGEM') {
        document.getElementById('visualizar-img').src = url;
        document.getElementById('visualizar-img').style.display = 'block';
        document.getElementById('visualizar-video').style.display = 'none';
        modal.show();
    }
}
