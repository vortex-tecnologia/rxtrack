// suporte_app.js
let suporteSocket = null;
let currentTicketId = null;
let originalInputHTML = null;
let pollingAppMessages = null;

// Ao abrir o modal, carregar a lista de chamados
const modalSuporte = document.getElementById('modalSuporte');
if (modalSuporte) {
    modalSuporte.addEventListener('show.bs.modal', function() {
        if (!originalInputHTML) {
            const area = document.getElementById('suporte-chat-input-area');
            if (area) originalInputHTML = area.innerHTML;
        }
        carregarListaTickets();
    });
}

// Volta para a lista de tickets (saindo do chat ou tela de novo ticket)
function voltarListaTickets() {
    const viewNovo = document.getElementById('view-novo-ticket');
    const viewChat = document.getElementById('view-chat-ativo');
    const viewLista = document.getElementById('view-lista-tickets');
    const btnVoltar = document.getElementById('btn-voltar-tickets');
    const modalTitulo = document.getElementById('suporte-modal-titulo');

    if (viewNovo) viewNovo.style.display = 'none';
    if (viewChat) viewChat.style.display = 'none';
    if (viewLista) viewLista.style.display = 'block';
    if (btnVoltar) btnVoltar.style.display = 'none';
    if (modalTitulo) modalTitulo.innerText = 'Meus Chamados';
    
    if (suporteSocket) {
        suporteSocket.close();
        suporteSocket = null;
    }
    if (pollingAppMessages) {
        clearInterval(pollingAppMessages);
        pollingAppMessages = null;
    }
    
    carregarListaTickets();
}

async function carregarListaTickets() {
    const token = localStorage.getItem('accessToken');
    if (!token) return;

    try {
        const response = await fetch('/suporte/api/tickets/', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (response.ok) {
            const data = await response.json();
            renderListaTickets(data);
        }
    } catch (error) {
        console.error('Erro carregando tickets', error);
    }
}

function renderListaTickets(tickets) {
    const container = document.getElementById('container-tickets-ativos');
    if (!container) return;

    if (!tickets || tickets.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted p-4 border rounded bg-white shadow-sm mt-3">
                <i class="bi bi-chat-square-text fs-1 opacity-50"></i>
                <p class="mt-2 text-sm fw-bold">Nenhum chamado aberto.</p>
                <p class="small">Se precisar de ajuda com notas fiscais ou tiver um problema operacional, abra um chamado.</p>
            </div>`;
        return;
    }

    let html = '';
    tickets.forEach(t => {
        let badgeClass = t.status === 'FECHADO' ? 'bg-secondary' : 'bg-success';
        let situacao = t.status.replace(/_/g, ' ');
        let preMsg = 'Sem mensagens';
        if (t.mensagens && t.mensagens.length > 0) {
            let lastMsg = t.mensagens[t.mensagens.length-1];
            preMsg = lastMsg.texto || (lastMsg.tipo !== 'TEXTO' ? '[Mídia]' : '') || 'Sem mensagens';
        }
        
        let datadstr = new Date(t.updated_at).toLocaleDateString('pt-BR');
        let timedstr = new Date(t.updated_at).toLocaleTimeString('pt-BR', {hour: '2-digit', minute:'2-digit'});

        html += `
            <div class="card border-0 shadow-sm mb-3" onclick="abrirChatTicket(${t.id})" style="cursor: pointer;">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="badge ${badgeClass}">${situacao}</span>
                        <small class="text-muted"><i class="bi bi-clock"></i> ${datadstr} ${timedstr}</small>
                    </div>
                    <h6 class="fw-bold mb-1">Chamado #${t.id} - ${t.categoria.replace(/_/g, ' ')}</h6>
                    <p class="text-muted small mb-0 text-truncate">${preMsg}</p>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
    if (typeof atualizarBadgeSuporte === 'function') {
        atualizarBadgeSuporte(tickets);
    }
}

function abrirNovoTicket() {
    const viewLista = document.getElementById('view-lista-tickets');
    const viewNovo = document.getElementById('view-novo-ticket');
    const btnVoltar = document.getElementById('btn-voltar-tickets');
    const modalTitulo = document.getElementById('suporte-modal-titulo');

    if (viewLista) viewLista.style.display = 'none';
    if (viewNovo) viewNovo.style.display = 'block';
    if (btnVoltar) btnVoltar.style.display = 'block';
    if (modalTitulo) modalTitulo.innerText = 'Novo Chamado';
    
    // Popular Dropdown NFs
    const nfSelect = document.getElementById('suporte-novo-nf');
    if (nfSelect) {
        nfSelect.innerHTML = '<option value="">(Nenhuma NF Específica)</option>';
        if (typeof window.notasGerais !== 'undefined' && window.notasGerais.length > 0) {
            window.notasGerais.forEach(n => {
                const numText = n.numero_nota || n.numero_coleta || n.chave_acesso;
                if (numText) {
                    nfSelect.innerHTML += `<option value="${n.id || ''}">${numText}</option>`;
                }
            });
        }
    }
}

async function criarNovoTicket() {
    const categoriaEl = document.getElementById('suporte-novo-categoria');
    const msgEl = document.getElementById('suporte-novo-msg');
    const nfSelect = document.getElementById('suporte-novo-nf');

    if (!categoriaEl || !msgEl) return;

    const categoria = categoriaEl.value;
    const msg = msgEl.value;
    const notaId = nfSelect ? nfSelect.value : '';
    const notaTexto = (nfSelect && nfSelect.selectedOptions[0]) ? nfSelect.selectedOptions[0].text : '';
    const manifestoNumero = localStorage.getItem('manifesto_ativo') || '';

    if (!categoria || !msg.trim()) {
        alert("Preencha a categoria e a mensagem, por favor.");
        return;
    }

    const token = localStorage.getItem('accessToken');
    const loadBtn = document.querySelector('button[onclick="criarNovoTicket()"]');
    let originalText = '';
    if (loadBtn) {
        originalText = loadBtn.innerHTML;
        loadBtn.disabled = true;
        loadBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Processando...';
    }

    try {
        const payload = {
            categoria: categoria,
            detalhe: msg,
            manifesto_numero: manifestoNumero,
            nota_numero: (notaTexto && notaTexto !== '(Nenhuma NF Específica)') ? notaTexto : '',
        };
        if (notaId) {
            payload.nota_fiscal = notaId;
        }

        const response = await fetch('/suporte/api/tickets/', {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json' 
            },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            const ticket = await response.json();
            abrirChatTicket(ticket.id);
        } else {
            console.error(await response.text());
            alert('Erro ao criar ticket.');
        }
    } catch (e) {
        console.error(e);
        alert('Falha na comunicação.');
    } finally {
        if (loadBtn) {
            loadBtn.disabled = false;
            loadBtn.innerHTML = originalText;
        }
    }
}

async function abrirChatTicket(id) {
    currentTicketId = id;
    
    if (pollingAppMessages) {
        clearInterval(pollingAppMessages);
        pollingAppMessages = null;
    }
    
    // RESTAURAR AREA DE INPUT (Caso tenha vindo de um chamado fechado anteriormente)
    const inputArea = document.getElementById('suporte-chat-input-area');
    if (inputArea && originalInputHTML) {
        inputArea.innerHTML = originalInputHTML;
    }

    const viewLista = document.getElementById('view-lista-tickets');
    const viewNovo = document.getElementById('view-novo-ticket');
    const viewChat = document.getElementById('view-chat-ativo');
    const btnVoltar = document.getElementById('btn-voltar-tickets');
    const modalTitulo = document.getElementById('suporte-modal-titulo');

    if (viewLista) viewLista.style.display = 'none';
    if (viewNovo) viewNovo.style.display = 'none';
    if (viewChat) viewChat.style.display = 'flex';
    if (btnVoltar) btnVoltar.style.display = 'block';
    if (modalTitulo) modalTitulo.innerText = `Chamado #${id}`;
    
    // reset input safely
    const inputField = document.getElementById('suporte-chat-input');
    if (inputField) inputField.value = '';
    
    const container = document.getElementById('suporte-chat-mensagens');
    if (container) {
        container.innerHTML = `<div class="text-center p-3"><div class="spinner-border text-primary"></div></div>`;
    }

    const token = localStorage.getItem('accessToken');
    try {
        const respTicket = await fetch(`/suporte/api/tickets/${id}/?t=${new Date().getTime()}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (respTicket.ok) {
            const ticket = await respTicket.json();
            
            if (container) container.innerHTML = '';
            if (ticket.mensagens && ticket.mensagens.length > 0) {
                ticket.mensagens.forEach(msg => {
                    renderizarMensagemNaTela(msg);
                });
            } else if (container) {
                container.innerHTML = '<p class="text-center text-muted mt-3 small opacity-50">Início da conversa</p>';
            }
            scrollToBottomChat();
            
            // Bloqueia input se ticket FECHADO
            if (ticket.status === 'FECHADO') {
                const area = document.getElementById('suporte-chat-input-area');
                if(area) area.innerHTML = '<div class="text-center text-muted py-3 w-100 fw-bold"><i class="bi bi-lock-fill me-2"></i>Este chamado foi encerrado.</div>';
            } else {
                iniciarPollingChatApp(id);
            }
        } else if (container) {
            container.innerHTML = '<p class="text-center text-danger mt-3 small opacity-50">Erro ao carregar mensagens</p>';
        }
    } catch(e) {
        console.error("Erro abrindo chat:", e);
    }
}

function iniciarPollingChatApp(ticketId) {
    if (pollingAppMessages) {
        clearInterval(pollingAppMessages);
        pollingAppMessages = null;
    }
    // Faz a primeira atualizacao de imediato
    atualizarMensagensAppSilencioso(ticketId);
    pollingAppMessages = setInterval(() => {
        if (currentTicketId === ticketId) {
            atualizarMensagensAppSilencioso(ticketId);
        }
    }, 4000);
}

function iniciarWebSocketChat(ticketId) {
    // Desativado para evitar erros de conexao WebSocket no console. Usando polling ativo.
}

async function atualizarMensagensAppSilencioso(id) {
    const token = localStorage.getItem('accessToken');
    try {
        const respTicket = await fetch(`/suporte/api/tickets/${id}/?t=${new Date().getTime()}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (respTicket.ok) {
            const ticket = await respTicket.json();
            const container = document.getElementById('suporte-chat-mensagens');
            if (container) {
                const totalNaTela = container.querySelectorAll('.shadow-sm.p-3').length;
                const totalNovas = (ticket.mensagens || []).length;
                
                if (totalNovas !== totalNaTela) {
                    container.innerHTML = '';
                    if (ticket.mensagens && ticket.mensagens.length > 0) {
                        ticket.mensagens.forEach(msg => {
                            renderizarMensagemNaTela(msg);
                        });
                    } else {
                        container.innerHTML = '<p class="text-center text-muted mt-3 small opacity-50">Início da conversa</p>';
                    }
                    scrollToBottomChat();
                }
            }
        }
    } catch(e) {
        console.error("Erro no polling silencioso de mensagens no app:", e);
    }
}

function renderizarMensagemNaTela(msg) {
    const container = document.getElementById('suporte-chat-mensagens');
    if (!container) return;
    
    if (msg.tipo === 'SISTEMA') {
        const textoSistema = (msg.texto || msg.mensagem || '').replace(/\n/g, '<br>');
        const html = `
            <div class="d-flex w-100 justify-content-center mb-3">
                <div class="bg-light rounded-3 px-4 py-2 text-center shadow-sm" style="max-width:90%;">
                    <small class="text-muted fst-italic">${textoSistema}</small>
                </div>
            </div>
        `;
        container.innerHTML += html;

        if ((msg.texto || msg.mensagem || '').toLowerCase().includes('encerrado')) {
            const inputArea = document.getElementById('suporte-chat-input-area');
            if(inputArea) inputArea.innerHTML = '<div class="text-center text-muted py-3 w-100 fw-bold"><i class="bi bi-lock-fill me-2"></i>Este chamado foi encerrado.</div>';
        }
        return;
    }
    
    const isMe = msg.enviado_por_motorista === true;
    let balaoClass = isMe ? 'bg-success text-white' : 'bg-white text-dark';
    let wrapperClass = isMe ? 'justify-content-end' : 'justify-content-start';
    let autorNome = isMe ? 'Você' : msg.remetente || msg.remetente_nome || 'Atendente';
    
    if(container.innerHTML.includes('Início da conversa')) {
        container.innerHTML = '';
    }
    let midiaHtml = '';
    let arquivoUrl = msg.arquivo_url || msg.arquivo || '';
    
    if (msg.tipo === 'IMAGEM' && arquivoUrl) {
        midiaHtml = `<img src="${arquivoUrl}" class="img-fluid rounded mb-2 shadow-sm" style="max-height: 200px; cursor: pointer;" onclick="abrirVideoTutorial(this.src, 'Mídia')">`;
    } else if (msg.tipo === 'AUDIO' && arquivoUrl) {
        midiaHtml = `
            <div class="d-flex align-items-center gap-2 mb-2 p-2 rounded-3" style="background: rgba(0,0,0,0.08); min-width: 220px;">
                <i class="bi bi-mic-fill" style="font-size: 1.2rem;"></i>
                <audio controls preload="none" style="height: 36px; flex: 1; max-width: 100%;">
                    <source src="${arquivoUrl}" type="audio/webm">
                    <source src="${arquivoUrl}" type="audio/mpeg">
                    Seu navegador não suporta áudio.
                </audio>
            </div>`;
    } else if (msg.tipo === 'VIDEO' && arquivoUrl) {
        midiaHtml = `
            <video controls preload="none" class="rounded mb-2 shadow-sm" style="max-height: 250px; max-width: 100%;">
                <source src="${arquivoUrl}" type="video/mp4">
                <source src="${arquivoUrl}" type="video/webm">
            </video>`;
    }

    let textoExibir = msg.texto || msg.mensagem || '';
    if (midiaHtml && (textoExibir === '(Audio)' || textoExibir === '(Midia enviada)')) {
        textoExibir = '';
    }
    const textoFormatado = textoExibir.replace(/\n/g, '<br>');

    const html = `
        <div class="d-flex w-100 ${wrapperClass} mb-3 align-items-end">
            <div class="shadow-sm p-3 rounded-4 ${balaoClass}" style="max-width: 85%; border-bottom-${isMe?'right':'left'}-radius: 0;">
                <p class="small fw-bold mb-1 opacity-75">${autorNome}</p>
                ${midiaHtml}
                ${textoFormatado ? `<p class="mb-1" style="word-wrap: break-word; font-size: 0.95rem;">${textoFormatado}</p>` : ''}
                <div class="text-end mt-1" style="font-size: 0.70rem; opacity: 0.7;">
                    ${new Date(msg.created_at).toLocaleTimeString('pt-BR', {hour: '2-digit', minute:'2-digit'})}
                </div>
            </div>
        </div>
    `;
    container.innerHTML += html;
}

function scrollToBottomChat() {
    const container = document.getElementById('suporte-chat-mensagens');
    if (container) container.scrollTop = container.scrollHeight;
}

function enviarMensagemChat() {
    const input = document.getElementById('suporte-chat-input');
    if (!input) return;
    const msg = input.value.trim();
    if (!msg) return;

    const token = localStorage.getItem('accessToken');
    fetch('/suporte/api/mensagens/', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
            ticket: currentTicketId,
            texto: msg,
            tipo: 'TEXTO'
        })
    }).then(() => {
        input.value = '';
        atualizarMensagensAppSilencioso(currentTicketId); // atualiza o chat imediatamente apos enviar
    });
}

// Delegated listener to avoid issues if element is replaced
document.addEventListener('keypress', function (e) {
    if (e.key === 'Enter' && e.target.id === 'suporte-chat-input') {
        enviarMensagemChat();
    }
});

async function previewUploadArquivo() {
    const fileInput = document.getElementById('suporte-chat-arq');
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) return;
    
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('ticket', currentTicketId);
    
    if (file.type.startsWith('image/')) formData.append('tipo', 'IMAGEM');
    else if (file.type.startsWith('video/')) formData.append('tipo', 'VIDEO');
    else if (file.type.startsWith('audio/')) formData.append('tipo', 'AUDIO');
    
    formData.append('arquivo', file);
    formData.append('texto', '(Mídia enviada)');

    const token = localStorage.getItem('accessToken');

    try {
        const resp = await fetch('/suporte/api/mensagens/', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });

        if(resp.ok) {
            abrirChatTicket(currentTicketId);
        } else {
            alert('Falha ao enviar mídia.');
        }
    } catch(e) {
        console.error(e);
    }
    fileInput.value = '';
}

let mediaRecorder = null;
let audioChunks = [];
let isGravando = false;

async function toggleGravarAudio() {
    if (isGravando) {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }
        return;
    }
    
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
        audioChunks = [];
        
        mediaRecorder.ondataavailable = function(e) {
            if (e.data.size > 0) audioChunks.push(e.data);
        };
        
        mediaRecorder.onstop = function() {
            stream.getTracks().forEach(track => track.stop());
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            enviarAudioGravado(audioBlob);
            
            isGravando = false;
            const btn = document.getElementById('btn-gravar-audio');
            if(btn) {
                btn.classList.remove('btn-danger');
                btn.classList.add('btn-light');
                btn.innerHTML = '<i class="bi bi-mic-fill fs-5"></i>';
                btn.style.animation = '';
            }
        };
        
        mediaRecorder.start();
        isGravando = true;
        const btn = document.getElementById('btn-gravar-audio');
        if(btn) {
            btn.classList.remove('btn-light');
            btn.classList.add('btn-danger');
            btn.innerHTML = '<i class="bi bi-stop-fill fs-5"></i>';
            btn.style.animation = 'pulse 1s infinite';
        }
        
    } catch(e) {
        console.error('Erro ao acessar microfone:', e);
        alert('Não foi possível acessar o microfone. Verifique as permissões.');
    }
}

async function enviarAudioGravado(audioBlob) {
    if (!currentTicketId) return;
    const formData = new FormData();
    formData.append('ticket', currentTicketId);
    formData.append('tipo', 'AUDIO');
    formData.append('arquivo', audioBlob, 'audio_gravado.webm');
    formData.append('texto', '(Audio)');
    
    const token = localStorage.getItem('accessToken');
    try {
        const resp = await fetch('/suporte/api/mensagens/', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });
        if(resp.ok) {
            abrirChatTicket(currentTicketId);
        } else {
            alert('Falha ao enviar áudio.');
        }
    } catch(e) {
        console.error('Erro enviando áudio:', e);
    }
}

const pulseStyle = document.createElement('style');
pulseStyle.textContent = `
    @keyframes pulse {
        0%, 100% { transform: scale(1); opacity: 1; }
        50% { transform: scale(1.1); opacity: 0.8; }
    }
`;
document.head.appendChild(pulseStyle);

// === BADGE DE NOTIFICAÇÕES (CHAMADOS NÃO LIDOS) ===
function atualizarBadgeSuporte(tickets) {
    const badge = document.getElementById('badge-suporte-unread');
    if (!badge) return;

    let totalUnread = 0;
    (tickets || []).forEach(t => {
        if (t.status !== 'FECHADO' && t.mensagens) {
            t.mensagens.forEach(msg => {
                if (!msg.enviado_por_motorista && !msg.lida) {
                    totalUnread++;
                }
            });
        }
    });

    if (totalUnread > 0) {
        badge.innerText = totalUnread;
        badge.style.display = 'inline-block';
    } else {
        badge.innerText = '0';
        badge.style.display = 'none';
    }
}

async function atualizarContagemNotificacoesApp() {
    const token = localStorage.getItem('accessToken');
    if (!token) return;

    try {
        const response = await fetch('/suporte/api/tickets/', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (response.ok) {
            const data = await response.json();
            atualizarBadgeSuporte(data);
        }
    } catch (error) {
        console.error('Erro ao atualizar contagem de notificações do suporte', error);
    }
}

// Inicializa a escuta de notificações
document.addEventListener('DOMContentLoaded', function() {
    atualizarContagemNotificacoesApp();
    // Atualiza a cada 30 segundos
    setInterval(atualizarContagemNotificacoesApp, 30000);
});
