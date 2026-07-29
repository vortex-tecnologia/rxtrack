// Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
// manifesto.js - VERSÃO FINAL REVISADA E OTIMIZADA
// =====================================================
// CONFIGURAÇÕES E ESTADO GLOBAL
// =====================================================
// 1. Definição da API_BASE caso ela não venha do Django/Template
if (typeof API_BASE === 'undefined') {
    window.API_BASE = window.location.origin + '/api/';
}

// 2. Definição segura do DB_NAME (Evita o erro de "already declared")
if (typeof DB_NAME === 'undefined') {
    window.DB_NAME = 'FrotaDB';
}
if (typeof DB_VERSION === 'undefined') {
    window.DB_VERSION = 1;
}

// Use as variáveis sem o 'const' agora, pois elas já estão no escopo global (window)
const ENDPOINTS = {
    busca: `${API_BASE}manifesto/busca/`,
    status: `${API_BASE}manifesto/status/`,
};

const LOGIN_URL = '/login/';
let loadingModal = null;
let pollingInterval = null;
let manifestoAtual = null;
let jaMudouDeTela = false;
let socketTracking = null;
let filialIdMotorista = 'todas';
let heartbeatInterval = null;

// =====================================================
// MODO SELEÇÃO MÚLTIPLA (WHATSAPP STYLE)
// =====================================================
let modoSelecaoAtivo = false;
let notasSelecionadas = new Set();
let longPressTimer;

function iniciarLongPress(e, numeroNF) {
    if (modoSelecaoAtivo) return; // Se já tá ativo, ignora
    
    // Suporte para touch e mouse
    const element = e.currentTarget;
    longPressTimer = setTimeout(() => {
        ativarModoSelecao(numeroNF, element);
        // Vibração leve se o celular suportar
        if (navigator.vibrate) navigator.vibrate(50);
    }, 600); // 600ms = long press
}

function cancelarLongPress() {
    clearTimeout(longPressTimer);
}

function ativarModoSelecao(numeroNFInicial, cardElement) {
    modoSelecaoAtivo = true;
    notasSelecionadas.clear();
    
    // Adiciona a classe global para mostrar os checkboxes
    document.getElementById('area-lista-dinamica').classList.add('modo-selecao-ativo');
    
    // Seleciona a nota que originou o long-press
    toggleSelecaoCard(numeroNFInicial, cardElement);
}

function cancelarModoSelecao() {
    modoSelecaoAtivo = false;
    notasSelecionadas.clear();
    
    const area = document.getElementById('area-lista-dinamica');
    if (area) area.classList.remove('modo-selecao-ativo');
    
    const cards = document.querySelectorAll('.card-nf.selecionavel');
    cards.forEach(c => {
        c.classList.remove('selecionado');
        const chk = c.querySelector('.checkbox-selecao');
        if(chk) chk.checked = false;
    });
    
    const fab = document.getElementById('fab-baixa-massa');
    if (fab) fab.classList.remove('show');
}

function toggleSelecaoCard(numeroNF, cardElement) {
    if (!modoSelecaoAtivo) return;

    // Apenas permite seleção de entregas pendentes
    if (!cardElement.classList.contains('tipo-entrega')) return;

    const checkbox = cardElement.querySelector('.checkbox-selecao');
    
    if (notasSelecionadas.has(numeroNF)) {
        notasSelecionadas.delete(numeroNF);
        cardElement.classList.remove('selecionado');
        if(checkbox) checkbox.checked = false;
    } else {
        notasSelecionadas.add(numeroNF);
        cardElement.classList.add('selecionado');
        if(checkbox) checkbox.checked = true;
    }

    // Atualiza botão flutuante
    const fab = document.getElementById('fab-baixa-massa');
    const badge = document.getElementById('badge-selecionadas');
    
    if (notasSelecionadas.size > 0) {
        if(badge) badge.innerText = notasSelecionadas.size;
        if(fab) fab.classList.add('show');
    } else {
        cancelarModoSelecao(); // Se desmarcar tudo, sai do modo seleção automaticamente
    }
}

// =====================================================
// INTERCEPTORES DE CLIQUE
// =====================================================
function handleCardClick(e, numeroNF, chaveAcesso, tipo) {
    if (modoSelecaoAtivo) {
        // Modo WhatsApp: Apenas seleciona/deseleciona
        toggleSelecaoCard(numeroNF, e.currentTarget);
    } else {
        // Comportamento normal: abre modal de baixa individual
        if (tipo === 'ENTREGA') {
            abrirModalBaixa(numeroNF, chaveAcesso, tipo);
        } else if (tipo === 'COLETA') {
            abrirModalColeta(numeroNF, numeroNF, tipo);
        } else if (tipo === 'TRANSFERENCIA') {
            confirmarTransferenciaIndividual(numeroNF, chaveAcesso);
        } else {
            abrirModalPerguntaOperacional(numeroNF, chaveAcesso, tipo);
        }
    }
}

function abrirDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = (e) => {
            const db = e.target.result;
            // Loja para guardar as notas baixadas pendentes
            if (!db.objectStoreNames.contains('baixas_pendentes')) {
                db.createObjectStore('baixas_pendentes', { keyPath: 'id', autoIncrement: true });
            }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}
const TEMA_OPERACAO = {
    'TRANSFERENCIA': { icon: 'bi-box-arrow-right', color: 'primary', label: 'Registrar Chegada', code: '98' },
    'DESPACHO': { icon: 'bi-airplane', color: 'info', label: 'Confirmar Despacho', code: '50' },
    'RETIRADA': { icon: 'bi-box-arrow-in-left', color: 'warning', label: 'Confirmar Retirada', code: '51' },
    'ENTREGA': { icon: 'bi-truck', color: 'primary', label: 'Dar Baixa', code: '1' }
};
// =====================================================
// SINCRONIZAÇÃO AUTOMÁTICA (VIGIA)
// =====================================================
let _sincronizando = false;
async function sincronizarBaixasPendentes() {
    // Guard de concorrência: evita múltiplas chamadas simultâneas
    if (_sincronizando) return;
    _sincronizando = true;

    try {
        const db = await abrirDB();
        const transaction = db.transaction('baixas_pendentes', 'readonly');
        const store = transaction.objectStore('baixas_pendentes');

        // Usa cursor em vez de getAll() para não carregar todos os blobs na RAM de uma vez
        const chaves = await new Promise(res => {
            const keys = [];
            const req = store.openKeyCursor();
            req.onsuccess = (e) => {
                const cursor = e.target.result;
                if (cursor) {
                    keys.push(cursor.key);
                    cursor.continue();
                } else {
                    res(keys);
                }
            };
            req.onerror = () => res([]);
        });

        if (chaves.length === 0) {
            atualizarIconeNuvem();
            return;
        }

        console.log(`🔄 Tentando sincronizar ${chaves.length} notas...`);

        // Processa UM registro por vez via get(key) para economia de memória
        for (const key of chaves) {
            const item = await new Promise(res => {
                const tx = db.transaction('baixas_pendentes', 'readonly');
                const req = tx.objectStore('baixas_pendentes').get(key);
                req.onsuccess = () => res(req.result);
                req.onerror = () => res(null);
            });

            if (!item) continue;

            const formData = new FormData();

            for (const k in item.campos) {
                let valor = item.campos[k];
                if ((k === 'latitude' || k === 'longitude') && (valor === null || valor === undefined)) {
                    valor = "0.000000";
                }
                formData.append(k, valor || '');
            }

            formData.append('chave_acesso', item.chaveNF || '');
            formData.append('numero_nota', item.numeroNF || '');
            formData.append('manifesto_id', item.mID || '');

            if (item.campos && item.campos.tipo_operacao === 'COLETA') {
                formData.append('tipo_operacao', 'COLETA');
                formData.append('nota_id_tms', item.campos.nota_id_tms || item.chaveNF);
            }

            if (item.foto) {
                formData.append('foto', item.foto, `mft_${item.mID}_${item.chaveNF}.jpg`);
            }

            try {
                const response = await authFetch(`${API_BASE}manifesto/registrar-baixa/`, {
                    method: 'POST',
                    body: formData
                });

                if (response.ok) {
                    const delTrans = db.transaction('baixas_pendentes', 'readwrite');
                    await delTrans.objectStore('baixas_pendentes').delete(item.id);
                    console.log(`✅ Nota ${item.numeroNF || item.chaveNF} sincronizada com sucesso!`);
                    await atualizarIconeNuvem();
                }
                else if (response.status === 400 || response.status === 404) {
                    const dataErr = await response.json().catch(() => ({}));
                    console.error(`❌ Erro ${response.status} na nota ${item.numeroNF || item.chaveNF}: ${dataErr.erro || 'Documento rejeitado ou não localizado'}. Removendo da fila offline.`);
                    const delTrans = db.transaction('baixas_pendentes', 'readwrite');
                    await delTrans.objectStore('baixas_pendentes').delete(item.id);
                    await atualizarIconeNuvem();
                }
                else {
                    console.warn(`⚠️ Servidor respondeu ${response.status} para nota ${item.numeroNF || item.chaveNF}. Mantendo na fila.`);
                }

            } catch (err) {
                console.warn("📡 Falha de rede durante a sincronização. Parando ciclo.");
                break;
            }
        }

        await atualizarIconeNuvem();
    } finally {
        _sincronizando = false;
    }
}

// Chame a atualização da nuvem assim que salvar no catch do salvarRegistro
// catch (err) { ... store.add(objOffline); atualizarIconeNuvem(); ... }

// (Listener 'online' unificado no final do arquivo)
// =====================================================
// INICIALIZAÇÃO (INIT)
// =====================================================
document.addEventListener('DOMContentLoaded', async () => {
    initModals();

    const authenticated = await initAuth();
    if (authenticated) {
        await carregarDadosCabecalho(); // Espera carregar filial para o WS
        forcarUpdatePWA();
        atualizarDadosHeader();
        verificarEstadoInicial();

        const inputCamera = document.getElementById('camera-nativa');
        if (inputCamera) {
            inputCamera.addEventListener('change', handleCameraNativa);
        }

        // =====================================================
        // FLUXO DE FINALIZAÇÃO DE MANIFESTO (AUTOMÁTICO)
        // =====================================================
        // A rotina de finalização agora é automática e chamada por fora quando a última nota é baixada.
    } else {
        window.location.href = LOGIN_URL;
    }
});
// =====================================================
// Forçar a atualização do Service Worker e limpar cache
// =====================================================
function forcarUpdatePWA() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.getRegistrations().then(registrations => {
            for (let registration of registrations) {
                // 1. Pede para o Service Worker buscar atualizações no servidor
                registration.update();

                // 2. Se houver um novo esperando, ele força a ativação
                if (registration.waiting) {
                    registration.waiting.postMessage({ type: 'SKIP_WAITING' });
                }
            }
        });
    }
}

// Escuta a mudança de controle (quando o SW novo assume) e dá o REFRESH
navigator.serviceWorker.addEventListener('controllerchange', () => {
    console.log("Novo Service Worker assumiu. Recarregando...");
    window.location.reload(true); // O 'true' força o reload do servidor
});
// =====================================================
// FLUXO DE BUSCA E MONITORAMENTO (POLLING VIVO)
// =====================================================

async function handleManifestoSearch(event) {
    event.preventDefault();
    const numero = document.getElementById('manifesto-number').value.trim();
    if (!numero) return;

    manifestoAtual = numero;

    const loadingText = document.getElementById('loadingMessage');
    if (loadingText) loadingText.innerText = "Validando acesso e motorista...";

    loadingModal?.show();

    try {
        const response = await authFetch(ENDPOINTS.busca, {
            method: 'POST',
            body: JSON.stringify({ numero_manifesto: numero }),
        });

        if (response.ok) {
            localStorage.setItem('manifesto_ativo', numero);
            startPolling();
        } else {
            loadingModal?.hide();
            renderSearchScreen('Manifesto não encontrado ou erro no servidor.', 'error');
        }
    } catch (err) {
        loadingModal?.hide();
        renderSearchScreen('Erro de conexão com o servidor.', 'error');
    }
}


// Tenta sincronizar toda vez que o app detecta que a internet voltou
// (Listener 'online' unificado no final do arquivo)

//
function startPolling() {
    stopPolling();
    jaMudouDeTela = false;

    pollingInterval = setInterval(async () => {
        try {
            const response = await authFetch(`${API_BASE}manifesto/status/?numero_manifesto=${manifestoAtual}`);

            // PROTEÇÃO 401: Ignora ciclo se o token estiver renovando
            if (!response || response.status === 401) {
                console.warn("Autenticação em renovação...");
                return;
            }

            const data = await response.json();

            // 1. ESTADO DE CARREGAMENTO: Notas aparecendo uma a uma
            if (data.status === 'ENRIQUECENDO' || data.status === 'AGUARDANDO' || data.status === 'PROCESSANDO') {
                if (!jaMudouDeTela) {
                    jaMudouDeTela = true;
                    loadingModal?.hide();
                    renderEstruturaLista(manifestoAtual);
                } else {
                    atualizarListaViva(manifestoAtual);
                }
            }

            // 2. ESTADO FINAL: Carga concluída (5 a 50 notas)
            if (data.status === 'PROCESSADO') {
                stopPolling();
                await atualizarListaViva(manifestoAtual);

                const contador = document.getElementById('contador-notas');
                if (contador) {
                    contador.className = "badge bg-success animate__animated animate__bounceIn";
                    contador.innerText = "✅ Sincronização Concluída";
                }

                // Finaliza e recarrega para estabilizar banco local
                setTimeout(() => { window.location.reload(); }, 1500);
            }
            else if (data.status === 'ERRO') {
                stopPolling();
                loadingModal?.hide();
                renderSearchScreen(data.mensagem_erro || 'Erro no processamento', 'error');
            }
        } catch (err) {
            console.error("Erro no ciclo de polling:", err);
        }
    }, 3000);
}

// =====================================================
// RENDERIZAÇÃO DINÂMICA (INCREMENTAL)
// =====================================================

async function renderEstruturaLista(numeroManifesto) {
    const content = document.getElementById('app-content');
    if (!content) return;

    // 1. Tenta pegar as notas que já estavam no cache para mostrar IMEDIATAMENTE
    const notasCache = localStorage.getItem(`cache_notas_${numeroManifesto}`);

    content.innerHTML = `
        <div class="container pb-5 animate__animated animate__fadeIn">
            <div class="text-center mb-4">
                <h5 class="fw-bold text-secondary mb-1">Manifesto #${numeroManifesto}</h5>
                <div id="progresso-container" class="mt-2">
                    <span id="contador-notas" class="badge bg-primary px-3 py-2">Sincronizando...</span>
                </div>
            </div>

            <div id="area-lista-dinamica">
                ${notasCache ? '' : `
                    <div class="skeleton-card"></div>
                    <div class="skeleton-card"></div>
                `}
            </div>
        </div>
    `;

    // Se tem cache, já renderiza ele enquanto o servidor não responde
    if (notasCache) {
        document.getElementById('area-lista-dinamica').innerHTML = JSON.parse(notasCache).html;
    }

    // 2. Dispara as consultas ao servidor em PARALELO (Muito mais rápido)
    // Em vez de esperar o status para depois buscar notas, faz os dois de uma vez
    Promise.all([
        authFetch(`${API_BASE}manifesto/status/?numero_manifesto=${numeroManifesto}`),
        atualizarListaViva(numeroManifesto)
    ]).then(async ([resStatus]) => {
        const statusData = await resStatus.json();
        // Se o status disser que encerrou, aí sim a gente limpa a tela
        if (statusData.status === 'FINALIZADO') {
            localStorage.removeItem(`cache_notas_${numeroManifesto}`);
            window.location.reload();
        }
    });
}

// =====================================================
// FLUXO DE BUSCA E MONITORAMENTO (POLLING VIVO)
// =====================================================
async function atualizarListaViva(numeroManifesto) {
    try {
        const response = await authFetch(`${API_BASE}manifesto/notas/?numero_manifesto=${numeroManifesto}`);
        if (!response || response.status !== 200) return;

        const notas = await response.json();
        window.notasGerais = notas;
        const areaDinamica = document.getElementById('area-lista-dinamica');
        const contador = document.getElementById('contador-notas');

        // 1. BUSCA NOTAS NO LIMBO (INDEXEDDB)
        const db = await abrirDB();
        const transPendentes = db.transaction('baixas_pendentes', 'readonly');
        const storePendentes = transPendentes.objectStore('baixas_pendentes');
        const notasNoLimbo = await new Promise(res => {
            const req = storePendentes.getAll();
            req.onsuccess = () => res(req.result.map(n => n.chaveNF));
        });

        // --- 2. LOGICA DA SINCRONIZAÇÃO (FEEDBACK VISUAL) ---
        if (contador) {
            contador.innerHTML = `<span class="badge bg-primary px-4 py-2 animate__animated animate__fadeIn">Sincronizando...</span>`;
        }

        // --- 3. ANÁLISE DE MUDANÇA (SILENT REFRESH) ---
        const cacheDadosRaw = localStorage.getItem(`cache_dados_puros_${numeroManifesto}`);
        const novosDadosJSON = JSON.stringify(notas);

        // VARIÁVEIS DE APOIO PARA OS GRUPOS E CONTADORES
        const TEMA_OPERACAO = {
            'TRANSFERENCIA': { icon: 'bi-box-arrow-right', color: 'primary', label: 'Registrar Chegada', code: '98' },
            'DESPACHO': { icon: 'bi-airplane', color: 'info', label: 'Confirmar Despacho', code: '50' },
            'RETIRADA': { icon: 'bi-box-arrow-in-left', color: 'warning', label: 'Confirmar Retirada', code: '51' },
            'ENTREGA': { icon: 'bi-truck', color: 'success', label: 'Dar Baixa', code: '1' },
            'COLETA': { icon: 'bi-box-seam', color: 'dark', label: 'Registrar Coleta', code: '1' }
        };

        const grupos = { 'TRANSFERENCIA': [], 'DESPACHO': [], 'RETIRADA': [], 'ENTREGA': [], 'COLETA': [] };
        let totalFinalizadas = 0;
        let htmlConcluidos = '';

        // PROCESSA OS DADOS PARA SABER OS CONTADORES (MESMO QUE NÃO MUDE A TELA)
        notas.forEach(nf => {
            const tipo = nf.tipo_operacao || 'ENTREGA';
            if (nf.ja_baixada) {
                totalFinalizadas++;
                const config = TEMA_OPERACAO[tipo] || TEMA_OPERACAO['ENTREGA'];
                htmlConcluidos += gerarCardHTML(nf, config, true, false);
            } else {
                if (grupos[tipo]) grupos[tipo].push(nf);
                else grupos['ENTREGA'].push(nf);
            }
        });

        // SE NÃO MUDOU NADA, APENAS ATUALIZA OS CONTADORES E SAI
        // IMPORTANTE: Só pula se a lista já estiver renderizada na tela!
        const listaJaRenderizada = document.getElementById('input-busca-nfe') !== null;
        if (cacheDadosRaw === novosDadosJSON && listaJaRenderizada) {
            console.log("ℹ️ Sem alterações. Atualizando apenas contadores.");
            setTimeout(() => {
                atualizarVisualContadores(contador, notas, totalFinalizadas);
            }, 800);
            return;
        }

        // --- 4. SE HOUVE MUDANÇA, REDESENHA A TELA ---
        if (areaDinamica && notas.length > 0) {
            // INJEÇÃO DA BUSCA (MANTIDO ORIGINAL)
            if (!document.getElementById('input-busca-nfe')) {
                areaDinamica.innerHTML = `
                    <div class="search-box mb-4">
                        <div class="input-group shadow-sm position-relative" style="border-radius: 15px; overflow: hidden;">
                            <span class="input-group-text bg-white border-0"><i class="bi bi-search text-muted"></i></span>
                            <input type="text" id="input-busca-nfe" class="form-control border-0 p-3" placeholder="Filtrar por Número ou Chave..." oninput="filtrarNotasOffline(); toggleClearButton();">
                        </div>
                    </div>
                    <div id="container-baixa-coletiva"></div>
                    <div id="container-finalizacao-manifesto"></div>
                    <div id="lista-notas-container"></div>
                    <div id="lista-notas-concluidas" class="mt-4 pt-3 border-top d-none">
                        <div class="d-flex align-items-center mb-3 text-success opacity-75">
                            <i class="bi bi-check-all fs-4 me-2"></i><h6 class="mb-0 fw-bold text-uppercase">Itens Concluídos</h6>
                        </div>
                        <div id="container-concluidos-cards" class="opacity-50"></div>
                    </div>
                `;
            }

            const containerNotas = document.getElementById('lista-notas-container');
            const containerConcluidos = document.getElementById('container-concluidos-cards');
            const secaoConcluidos = document.getElementById('lista-notas-concluidas');
            const containerColetiva = document.getElementById('container-baixa-coletiva');

            // MONTA O HTML DAS PENDENTES
            let htmlPendentes = '';
            Object.keys(grupos).forEach(tipo => {
                if (grupos[tipo].length > 0) {
                    const config = TEMA_OPERACAO[tipo];
                    htmlPendentes += `<div class="group-divider mb-2 mt-3 small fw-bold text-muted text-uppercase" style="background: #e9ecef; padding: 5px 10px; border-radius: 5px;">
                                        <i class="bi ${config.icon} me-1"></i> ${tipo} (${grupos[tipo].length})
                                      </div>`;
                    grupos[tipo].forEach(nf => {
                        const estaSincronizando = notasNoLimbo.includes(nf.chave_acesso);
                        htmlPendentes += gerarCardHTML(nf, config, false, estaSincronizando);
                    });
                }
            });

            containerNotas.innerHTML = htmlPendentes;

            if (totalFinalizadas > 0) {
                containerConcluidos.innerHTML = htmlConcluidos;
                secaoConcluidos.classList.remove('d-none');
            } else {
                secaoConcluidos.classList.add('d-none');
            }

            // BAIXA COLETIVA
            const transfPendentes = grupos['TRANSFERENCIA'].filter(n => !n.ja_baixada);
            if (transfPendentes.length > 0 && containerColetiva) {
                containerColetiva.innerHTML = `<div class="card bg-primary text-white mb-4 shadow-sm border-0"><div class="card-body d-flex justify-content-between align-items-center"><div><small class="fw-bold opacity-75">OPERAÇÃO FILIAL</small><h6 class="mb-0">Chegada de ${transfPendentes.length} Notas</h6></div><button class="btn btn-light btn-sm fw-bold text-primary px-3" onclick="registrarChegadaColetiva('${numeroManifesto}')">CONFIRMAR CHEGADA</button></div></div>`;
            } else if (containerColetiva) { containerColetiva.innerHTML = ''; }

            // CONTAINER DE FINALIZAÇÃO (BOTÃO MANUAL)
            const containerFinalizacao = document.getElementById('container-finalizacao-manifesto');
            if (containerFinalizacao) {
                if (notas.length > 0 && totalFinalizadas === notas.length) {
                    containerFinalizacao.innerHTML = `
                        <div class="card bg-success text-white mb-4 shadow border-0 animate__animated animate__pulse animate__infinite">
                            <div class="card-body text-center py-4">
                                <i class="bi bi-flag-fill mb-2" style="font-size: 2rem;"></i>
                                <h5 class="fw-bold mb-1">ENTREGAS CONCLUÍDAS!</h5>
                                <p class="small mb-3 opacity-91">Todas as notas deste manifesto foram bipadas.</p>
                                <button class="btn btn-light btn-lg fw-bold text-success w-100 rounded-pill shadow-sm" onclick="abrirModalFinalizacao()">
                                    <i class="bi bi-check-all me-1"></i> FINALIZAR MANIFESTO
                                </button>
                            </div>
                        </div>
                    `;
                } else {
                    containerFinalizacao.innerHTML = '';
                }
            }

            // FINALIZAÇÃO: ATUALIZA CONTADORES E CACHE
            atualizarVisualContadores(contador, notas, totalFinalizadas);
            filtrarNotasOffline();

            // Cache de dados puros (leve) — o cache de HTML foi removido para economizar memória
            localStorage.setItem(`cache_dados_puros_${numeroManifesto}`, novosDadosJSON);
        }
    } catch (err) { console.error("Erro na atualização viva:", err); }
}

// FUNÇÃO SIMPLES SÓ PARA OS BADGES DE CIMA
function atualizarVisualContadores(contador, notas, totalFinalizadas) {
    if (!contador) return;
    let html = `<div class="d-flex gap-2 justify-content-center">
                    <span class="badge bg-secondary p-2">${notas.length} Notas no Manifesto</span>`;
    if (totalFinalizadas > 0) {
        html += `<span class="badge bg-success p-2 animate__animated animate__bounceIn">
                    <i class="bi bi-check2-circle"></i> ${totalFinalizadas} Finalizadas</span>`;
    }
    html += `</div>`;
    contador.innerHTML = html;

    // Se tudo foi entregue, APENAS ATUALIZA O CONTADOR (A finalização agora é manual via botão)
    if (notas.length > 0 && totalFinalizadas === notas.length) {
        console.log("🏁 Todas as notas concluídas. Aguardando finalização manual.");
        // Removido o fluxo automático: finalizarManifestoAutomatico();
    }
}
// =====================================================
// FUNÇÃO AUXILIAR PARA GERAR O CARD (EVITA DUPLICAR CÓDIGO)
// =====================================================
function gerarCardHTML(nf, config, baixada, sincronizando = false) {
    // Se estiver sincronizando, usamos o amarelo (warning), se baixada verde (success), senão a cor da config
    const cor = sincronizando ? 'warning' : (baixada ? 'success' : config.color);
    const icone = sincronizando ? 'bi-cloud-arrow-up' : (baixada ? 'bi-check-circle-fill' : config.icon);

    const chave = nf.chave_acesso || '';
    const tipo = nf.tipo_operacao || 'ENTREGA';
    const numero = (tipo === 'COLETA') ? (nf.numero_coleta || nf.numero_nota || '') : (nf.numero_nota || '');

    // Classe especial para o card que está subindo
    const classeSincronizando = sincronizando ? 'opacity-75 shadow-none border-dashed' : '';

    const isEntrega = tipo === 'ENTREGA';
    
    return `
        <div class="card card-nf mb-3 shadow-sm border-start border-${cor} border-4 animate__animated ${baixada || sincronizando ? '' : 'animate__fadeInUp selecionavel'} ${classeSincronizando} ${isEntrega && !baixada ? 'tipo-entrega' : ''}" 
        id="card-nf-${numero}"
        data-chave="${chave}"
        data-numero="${numero}"
        ${(!baixada && !sincronizando) ? `
        onmousedown="iniciarLongPress(event, '${numero}')" 
        onmouseup="cancelarLongPress()" 
        onmouseleave="cancelarLongPress()" 
        ontouchstart="iniciarLongPress(event, '${numero}')" 
        ontouchend="cancelarLongPress()" 
        ontouchcancel="cancelarLongPress()"
        onclick="handleCardClick(event, '${numero}', '${chave}', '${tipo}')"
        oncontextmenu="event.preventDefault();"
        ` : ''}>
            <div class="card-body p-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="d-flex align-items-center">
                        ${!baixada && !sincronizando && isEntrega ? `
                        <input class="form-check-input checkbox-selecao fs-4 me-3 mt-0" type="checkbox" onclick="event.preventDefault();">
                        ` : ''}
                        <h6 class="fw-bold mb-1">${tipo === 'COLETA' ? '📦COLETA' : '📝NF'} ${numero}</h6>
                    </div>
                    <span>
                        <i class="bi ${icone} text-${cor} ${sincronizando ? 'animate__animated animate__flash animate__infinite' : ''}" 
                           style="font-size: 1.2rem;"></i>
                    </span>
                </div>
                <p class="small text-muted mb-1">👤 ${nf.destinatario}</p>
                <p class="small text-muted mb-2" style="font-size: 0.75rem;"><i class="bi bi-geo-alt"></i> ${nf.endereco_entrega}</p>
                
                ${sincronizando ? `
                    <div class="alert alert-warning py-1 px-2 mb-0 d-flex align-items-center justify-content-center" style="font-size: 0.8rem;">
                        <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                        <span class="fw-bold text-uppercase">Sincronizando...</span>
                    </div>
                ` : !baixada ? `
                    <button class="btn btn-sm btn-${config.color} w-100 fw-bold btn-baixa-individual">
                        ${config.label}
                    </button>
                ` : `
                    <button class="btn btn-sm btn-outline-success w-100 btn-baixa-individual" 
                        onclick='event.stopPropagation(); abrirModalDetalhes(${JSON.stringify(nf.dados_baixa)})'>
                        Ver Detalhes
                    </button>
                `}
            </div>
        </div>`;
}
// =====================================================
// FUNÇÕES DE INTERFACE (MODALS E SEARCH)
// =====================================================

function renderSearchScreen(message = null, type = 'info') {
    stopPolling();
    const content = document.getElementById('app-content');
    const alertHTML = message ? `<div class="alert alert-${type === 'error' ? 'danger' : 'info'} animate__animated animate__shakeX w-100 mb-3">${message}</div>` : '';

    content.innerHTML = `
        <div class="search-container-card animate__animated animate__fadeIn flex-grow-1 w-100">
            <div class="card shadow border-0 p-4" style="border-radius: 20px;">
                <div class="text-center mb-4">
                    <i class="bi bi-truck text-primary" style="font-size: 2.5rem;"></i>
                    <h5 class="fw-bold mt-2">Buscar Manifesto</h5>
                    <p class="text-muted small">Digite o número para carregar as notas</p>
                </div>

                ${alertHTML}

                <form id="search-form">
                    <div class="form-floating mb-3">
                        <input type="number" id="manifesto-number" class="form-control" placeholder="00000" required>
                        <label for="manifesto-number">Número do Manifesto</label>
                    </div>
                    <button class="btn btn-primary btn-lg w-100 shadow-sm fw-bold" style="border-radius: 12px;">
                        CARREGAR ROTA
                    </button>
                </form>
            </div>
        </div>
    `;
    document.getElementById('search-form').addEventListener('submit', handleManifestoSearch);
}

// =====================================================
// VERIFICAÇÃO DE ESTADO INICIAL (MANIFESTO ATIVO) - COMPLETA
// =====================================================
async function verificarEstadoInicial() {
    const content = document.getElementById('app-content');
    const mID_salvo = localStorage.getItem('manifesto_ativo');

    // 1. CARREGAMENTO INSTANTÂNEO (UX Otimista)
    if (mID_salvo) {
        console.log("⚡ Iniciando com dados locais...");
        manifestoAtual = mID_salvo;
        renderListaEntregasFinal(mID_salvo);

        const cache = localStorage.getItem(`cache_notas_${mID_salvo}`);
        if (cache) {
            const areaDinamica = document.getElementById('area-lista-dinamica');
            if (areaDinamica) {
                areaDinamica.innerHTML = JSON.parse(cache).html;
            }
        }
    } else {
        // 2. SE NÃO TEM CACHE, LIMPA O INPUT E MOSTRA O SKELETON (NOVO)
        // Substituímos o spinner antigo pelo Skeleton para uma sensação melhor
        if (content) {
            mostrarSkeletonLoading();
        }
    }

    // 3. VERIFICAÇÃO EM SEGUNDO PLANO
    try {
        const response = await authFetch(`${API_BASE}manifesto/verificar-ativo/`);

        if (!response || !response.ok) {
            if (!mID_salvo) renderSearchScreen(); // Se falhou e não tem nada, mostra busca
            return;
        }

        const data = await response.json();

        if (data.tem_manifesto) {
            manifestoAtual = data.numero_manifesto;
            localStorage.setItem('manifesto_ativo', data.numero_manifesto);

            // Se a tela de loading estava ativa, a renderListaEntregasFinal vai montar a estrutura
            if (!mID_salvo) renderListaEntregasFinal(data.numero_manifesto);

            const el = document.getElementById('manifesto-id-display');
            if (el) el.innerText = data.numero_manifesto;

            atualizarListaViva(data.numero_manifesto);
            iniciarCoracaoTracking(); // Inicia o tracking se tem manifesto
        } else {
            console.log("ℹ️ Nenhum manifesto ativo.");
            localStorage.removeItem('manifesto_ativo');
            if (mID_salvo) localStorage.removeItem(`cache_notas_${mID_salvo}`);
            renderSearchScreen(); // Agora sim, aqui ele mostra o input de busca
        }
    } catch (err) {
        console.warn("📡 Falha na verificação de status.");
        if (!mID_salvo) renderSearchScreen();
    }
}
async function renderListaEntregasFinal(numeroManifesto) {
    // Mesma lógica do renderEstruturaLista, mas usada para carregamento inicial (Estado Ativo)
    renderEstruturaLista(numeroManifesto);
}



// =====================================================
// ATUALIZA CONTATO DE ENTREGAS SEM RELOAD
// =====================================================
function atualizarContadorVisual() {
    const contadorContainer = document.getElementById('contador-notas');
    if (!contadorContainer) return;

    // Procura o badge de "Finalizadas"
    let badgeSucesso = contadorContainer.querySelector('.bg-success');

    if (badgeSucesso) {
        // Se já existe, pega o número atual, soma 1 e atualiza o texto
        let texto = badgeSucesso.innerText;
        let numeroAtual = parseInt(texto.replace(/\D/g, '')) || 0;
        let novoNumero = numeroAtual + 1;

        badgeSucesso.innerHTML = `<i class="bi bi-check2-circle"></i> ${novoNumero} Finalizadas`;
        badgeSucesso.classList.add('animate__bounceIn'); // Dá um pulinho

        // Remove a animação depois para poder repetir na próxima
        setTimeout(() => badgeSucesso.classList.remove('animate__bounceIn'), 1000);
    } else {
        // Se for a primeira nota do dia, cria o badge do zero
        const novoBadge = `<span class="badge bg-success p-2 animate__bounceIn"><i class="bi bi-check2-circle"></i> 1 Finalizadas</span>`;
        contadorContainer.innerHTML += novoBadge;
    }
}

// =====================================================
// FUNÇÃO PARA VER SE O MANIFESTO ESTÁ COMPLETO E FINALIZAR AUTOMATICAMENTE
// =====================================================
function verificarFimDoManifesto() {
    const container = document.getElementById('lista-notas-container');
    const notasRestantes = container.querySelectorAll('.card');

    // Se não houver mais cards visíveis na seção de pendentes, abre o modal de confirmação
    if (notasRestantes.length === 0) {
        abrirModalFinalizacao();
    }
}

// =====================================================
// FINALIZAÇÃO AUTOMÁTICA EM SEGUNDO PLANO
// =====================================================
// =====================================================
// FINALIZAÇÃO MANUAL (SOLICITADA PELO USUÁRIO)
// =====================================================
function abrirModalFinalizacao() {
    const modalElement = document.getElementById('modalFinalizacaoManual');
    // Resetar o conteúdo caso tenha sido alterado por erro anterior
    document.getElementById('conteudo-modal-finalizacao').innerHTML = `
        <div class="modal-header border-0 flex-column align-items-center pt-4">
            <div class="bg-primary bg-opacity-10 p-3 rounded-circle mb-3">
                <i class="bi bi-flag-fill text-primary fs-1"></i>
            </div>
            <h4 class="modal-title fw-bold text-dark">Entregas Concluídas</h4>
        </div>
        <div class="modal-body text-center px-4 pb-4">
            <p class="text-muted">Parabéns! Você concluiu todas as entregas deste manifesto. Deseja finalizar a rota agora?</p>
            <div class="d-grid gap-2 mt-4">
                <button type="button" class="btn btn-primary btn-lg rounded-pill fw-bold py-3 shadow-sm" onclick="executarFinalizacaoManual()">
                    <i class="bi bi-check-circle-fill me-2"></i> FINALIZAR MANIFESTO
                </button>
                <button type="button" class="btn btn-link text-muted text-decoration-none fw-bold" data-bs-dismiss="modal">
                    Voltar à Lista
                </button>
            </div>
        </div>
    `;
    const modal = new bootstrap.Modal(modalElement);
    modal.show();
}

async function executarFinalizacaoManual() {
    const manifestoId = localStorage.getItem('manifesto_ativo') ||
        manifestoAtual ||
        document.getElementById('manifesto-id-display')?.innerText;

    if (!manifestoId) {
        alert("Erro: ID do manifesto não encontrado.");
        return;
    }

    const container = document.getElementById('conteudo-modal-finalizacao');

    // ESTADO 1: PROCESSANDO
    container.innerHTML = `
        <div class="modal-body text-center p-5">
            <div class="spinner-border text-primary mb-4" role="status" style="width: 4rem; height: 4rem;">
                <span class="visually-hidden">Processando...</span>
            </div>
            <h4 class="fw-bold">Finalizando manifesto...</h4>
            <p class="text-muted">Aguarde, estamos comunicando com o servidor.</p>
        </div>
    `;

    try {
        const response = await authFetch(`${API_BASE}manifesto/finalizar/`, {
            method: 'POST',
            body: JSON.stringify({
                km_final: "0",
                manifesto_id: manifestoId
            })
        });

        const data = await response.json();

        if (response.ok) {
            // ESTADO 2: SUCESSO
            container.innerHTML = `
                <div class="modal-body text-center p-5 animate__animated animate__zoomIn">
                    <div class="bg-success bg-opacity-10 p-4 rounded-circle d-inline-block mb-4">
                        <i class="bi bi-check-circle-fill text-success" style="font-size: 5rem;"></i>
                    </div>
                    <h2 class="fw-bold text-success">Manifesto Finalizado!</h2>
                    <p class="text-muted fs-5">Sua rota foi encerrada com sucesso.</p>
                    <div class="alert alert-success mt-4">
                        <i class="bi bi-info-circle me-2"></i> O aplicativo irá recarregar em instantes.
                    </div>
                </div>
            `;

            localStorage.removeItem('manifesto_ativo');
            localStorage.removeItem(`cache_notas_${manifestoId}`);
            localStorage.removeItem(`cache_dados_puros_${manifestoId}`);

            setTimeout(() => {
                window.location.reload();
            }, 500);

        } else {
            // ESTADO 3: ERRO DO BACKEND
            const msgErro = data.mensagem || "Houve uma falha na confirmação do fim da rota.";
            container.innerHTML = `
                <div class="modal-header border-0 flex-column align-items-center pt-4">
                    <div class="bg-danger bg-opacity-10 p-3 rounded-circle mb-3">
                        <i class="bi bi-exclamation-triangle-fill text-danger fs-1"></i>
                    </div>
                    <h4 class="modal-title fw-bold text-dark">Erro na Finalização</h4>
                </div>
                <div class="modal-body text-center px-4 pb-4">
                    <p class="text-danger fw-bold mb-4">${msgErro}</p>
                    <div class="d-grid gap-2">
                        <button type="button" class="btn btn-secondary btn-lg rounded-pill fw-bold py-3" onclick="abrirModalFinalizacao()">
                            Tentar Novamente
                        </button>
                        <button type="button" class="btn btn-link text-muted text-decoration-none fw-bold" data-bs-dismiss="modal">
                            Fechar
                        </button>
                    </div>
                </div>
            `;
        }
    } catch (err) {
        // ESTADO 4: ERRO DE CONEXÃO
        container.innerHTML = `
            <div class="modal-header border-0 flex-column align-items-center pt-4">
                <div class="bg-warning bg-opacity-10 p-3 rounded-circle mb-3">
                    <i class="bi bi-wifi-off text-warning fs-1"></i>
                </div>
                <h4 class="modal-title fw-bold text-dark">Falha de Conexão</h4>
            </div>
            <div class="modal-body text-center px-4 pb-4">
                <p class="text-muted mb-4">Não foi possível conectar ao servidor. Verifique sua internet.</p>
                <div class="d-grid gap-2">
                    <button type="button" class="btn btn-primary btn-lg rounded-pill fw-bold py-3" onclick="executarFinalizacaoManual()">
                        RECOMENTAR / TENTAR
                    </button>
                    <button type="button" class="btn btn-link text-muted text-decoration-none fw-bold" data-bs-dismiss="modal">
                        Voltar
                    </button>
                </div>
            </div>
        `;
    }
}

// =====================================================
// BAIXAS, CÂMERA E GEOLOCALIZAÇÃO
// =====================================================

// Certifique-se de que o statusModal foi inicializado no topo do seu arquivo JS
const statusModal = new bootstrap.Modal(document.getElementById('statusModal'));

async function salvarRegistro() {
    // 1. Coleta de elementos do DOM
    const selectOcorrencia = document.getElementById('select-ocorrencia');
    const inputRecebedor = document.getElementById('input-recebedor');
    const inputChave = document.getElementById('hidden-chave-nf');
    const canvas = document.getElementById('canvas-preview');
    const inputNumero = document.getElementById('hidden-numero-nf');
    const numeroNF = inputNumero ? inputNumero.value : '';

    const isRetida = document.getElementById('check-nota-retida').checked;
    const inputObs = document.getElementById('input-observacao').value;

    const cod = selectOcorrencia.value;
    const chaveNF = inputChave.value;
    const temFoto = (canvas.dataset.temFoto === "true");
    const mID = manifestoAtual || localStorage.getItem('manifesto_ativo');

    // --- NOVA LÓGICA DE VALIDAÇÃO ---
    if (isRetida) {
        if (!inputObs || inputObs.trim().length < 3) {
            alert("Selecione o motivo da retenção.");
            return;
        }
    } else {
        if ((cod === "1" || cod === "2") && !temFoto) {
            alert("A foto é obrigatória para este código de ocorrência!");
            return;
        }
    }

    // 3. Interface: Fecha modal de preenchimento e abre modal de progresso
    const modalBaixaEl = document.getElementById('modalBaixa');
    const modalBaixaInstance = bootstrap.Modal.getInstance(modalBaixaEl);
    if (modalBaixaInstance) modalBaixaInstance.hide();

    atualizarStatusUI('loading', 'Enviando Registro...', 'Aguarde, estamos salvando os dados.');
    statusModal.show();

    // 4. Preparação dos Dados (FormData)
    const formData = new FormData();
    const inputTipo = document.getElementById('hidden-tipo-operacao');
    const tipoOp = inputTipo ? inputTipo.value : '';

    formData.append('ocorrencia_codigo', cod);
    formData.append('chave_acesso', chaveNF);
    formData.append('numero_nota', numeroNF);
    formData.append('manifesto_id', mID);
    formData.append('recebedor', inputRecebedor.value || '');
    formData.append('nota_retida', isRetida);
    formData.append('observacao_retida', inputObs);
    if (tipoOp) {
        formData.append('tipo_operacao', tipoOp);
    }


    // 5. Captura de Coordenadas GPS
    try {
        const coords = await getCoords();
        if (coords && coords.lat && coords.lon) {
            formData.append('latitude', coords.lat);
            formData.append('longitude', coords.lon);
        } else {
            // Se o GPS falhar, enviamos 0 para não dar erro de "null" no Django
            formData.append('latitude', "0.000000");
            formData.append('longitude', "0.000000");
        }
    } catch (gpsErr) {
        console.warn("GPS falhou, enviando zerado para evitar erro 400");
        formData.append('latitude', "0.000000");
        formData.append('longitude', "0.000000");
    }

    // 6. Conversão do Canvas para Imagem (Blob)
    let fotoBlob = null;
    if (!isRetida && temFoto) {
        fotoBlob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.70));
        formData.append('foto', fotoBlob, `mft_${mID}_${chaveNF}.jpg`);
        // Libera memória do canvas imediatamente após extrair o blob
        canvas.width = 1;
        canvas.height = 1;
        canvas.getContext('2d').clearRect(0, 0, 1, 1);
    }

    // 7. Envio para o Backend com CONTINGÊNCIA OFFLINE
    try {
        const response = await authFetch(`${API_BASE}manifesto/registrar-baixa/`, {
            method: 'POST',
            body: formData
        });

        // =====================================================
        // AJUSTE PARA ERRO 500: Se o servidor falhar (ex: banco fora),
        // nós "jogamos" o erro para o CATCH para salvar offline.
        // =====================================================
        if (!response.ok && response.status >= 500) {
            throw new Error("Erro Crítico no Servidor");
        }

        const data = await response.json();

        if (response.ok) {
            atualizarStatusUI('success', '✅ Registro Cadastrado!', 'A baixa foi realizada com sucesso.');
            processarSumiçoNota(numeroNF);
            atualizarListaViva(manifestoAtual); // Atualiza a lista para refletir a baixa (opcional, pois o polling já cuida disso)

        } else {
            // Se o servidor retornar erro controlado (ex: 400 - Validação)
            if (data.status_integracao === 'erro_tms') {
                atualizarStatusUI('warning', '⚠️ Salvo com Alerta', `O canhoto foi salvo no App, mas houve um erro na ESL: ${data.erro}`);
            } else {
                atualizarStatusUI('error', '❌ Falha no Registro', data.erro || 'Erro interno no servidor.');
            }
            configurarBotaoWhats(data.erro, chaveNF);
        }
    } catch (err) {
        // --- MÁGICA DO MODO OFFLINE (Disparado por falta de net OU Erro 500) ---
        console.warn("Falha detectada. Salvando no banco de dados interno...");

        try {
            const db = await abrirDB();
            const transaction = db.transaction('baixas_pendentes', 'readwrite');
            const store = transaction.objectStore('baixas_pendentes');

            const objOffline = {
                id: Date.now().toString(),
                numeroNF: numeroNF,
                chaveNF: chaveNF,
                mID: mID,
                campos: {
                    ocorrencia_codigo: cod,
                    recebedor: inputRecebedor.value || '',
                    nota_retida: isRetida,
                    observacao_retida: inputObs,
                    latitude: formData.get('latitude'),
                    longitude: formData.get('longitude')
                },
                foto: fotoBlob
            };

            store.add(objOffline);

            // Atualiza a nuvem para Amarelo na hora
            await atualizarIconeNuvem();

            atualizarStatusUI('warning', '📡 Modo Offline Ativado', 'O sinal oscilou. Sua baixa foi guardada no celular e será enviada assim que o sinal voltar.');

            processarSumiçoNota(numeroNF);
            atualizarListaViva(manifestoAtual);
        } catch (dbErr) {
            console.error("Erro crítico ao salvar no DB interno:", dbErr);
            atualizarStatusUI('error', '❌ Erro de Sistema', 'Não foi possível salvar offline.');
        }
    }
}
// Função auxiliar para não repetir código de remover nota
function processarSumiçoNota(numeroNF) {
    const cardParaRemover = document.getElementById(`card-nf-${numeroNF}`);
    if (cardParaRemover) {
        cardParaRemover.classList.add('animate__fadeOutRight');
        setTimeout(() => {
            cardParaRemover.remove();
            atualizarContadorVisual();
            verificarFimDoManifesto();
        }, 500);
    }
    setTimeout(() => {
        statusModal.hide();
    }, 2000);
}
/**
 * Função Auxiliar para atualizar a interface do Modal de Status
 */
function atualizarStatusUI(tipo, titulo, mensagem) {
    const iconDiv = document.getElementById('status-icon');
    const titleEl = document.getElementById('status-title');
    const msgEl = document.getElementById('status-message');
    const footerDiv = document.getElementById('status-footer');

    titleEl.innerText = titulo;
    msgEl.innerText = mensagem;

    if (tipo === 'loading') {
        iconDiv.innerHTML = '<div class="spinner-border text-primary" style="width: 3rem; height: 3rem;"></div>';
        footerDiv.style.display = 'none';
    } else {
        footerDiv.style.display = 'block';
        if (tipo === 'success') iconDiv.innerHTML = '<span style="font-size: 5rem;">✅</span>';
        if (tipo === 'error') iconDiv.innerHTML = '<span style="font-size: 5rem;">❌</span>';
        if (tipo === 'warning') iconDiv.innerHTML = '<span style="font-size: 5rem;">⚠️</span>';
    }
}

/**
 * Configura o botão de suporte do WhatsApp caso ocorra um erro
 */
function configurarBotaoWhats(erroMsg, chave) {
    const btn = document.getElementById('btn-reportar');
    if (!btn) return;

    btn.style.display = 'block';
    btn.onclick = () => {
        const msg = `Olá! Tive um problema ao registrar a baixa.\nErro: ${erroMsg}\nChave: ${chave}`;
        const url = `https://wa.me/5521980064787?text=${encodeURIComponent(msg)}`;
        window.open(url, '_blank');
    };
}


//// FUNÇÕES AUXILIARES DE CÂMERA NATIVA E MODAIS ////

async function handleCameraNativa(event) {
    const file = event.target.files[0];
    if (!file) return;

    const canvas = document.getElementById('canvas-preview');
    const ctx = canvas.getContext('2d');

    try {
        // createImageBitmap redimensiona NATIVAMENTE pelo browser
        // sem carregar a foto inteira (12MP ~48MB) na RAM do JavaScript.
        // Resultado: ~90% menos consumo de memória vs new Image()
        const larguraDesejada = 800;
        const bitmap = await createImageBitmap(file, {
            resizeWidth: larguraDesejada,
            resizeQuality: 'medium'
        });

        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        ctx.drawImage(bitmap, 0, 0);

        // Libera o bitmap da memória imediatamente
        bitmap.close();

        canvas.style.display = 'none';
        canvas.dataset.temFoto = "true";

        // Atualiza a interface de forma LEVE (apenas ícone e texto)
        const icone = document.getElementById('icone-camera');
        const texto = document.getElementById('texto-status-foto');

        if (icone) {
            icone.className = "bi bi-check-circle-fill text-success";
            icone.style.fontSize = "3rem";
        }
        if (texto) {
            texto.innerText = "Foto capturada com sucesso!";
            texto.className = "text-success fw-bold mt-2";
        }

        document.getElementById('label-camera').style.display = 'none';
        document.getElementById('btn-nova-foto').style.display = 'block';
    } catch (err) {
        console.error('Erro ao processar foto:', err);
        // Fallback para navegadores muito antigos sem createImageBitmap
        const imgUrl = URL.createObjectURL(file);
        const img = new Image();
        img.onload = function () {
            const escala = Math.min(1, 800 / img.width);
            canvas.width = img.width * escala;
            canvas.height = img.height * escala;
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            URL.revokeObjectURL(imgUrl);
            canvas.style.display = 'none';
            canvas.dataset.temFoto = "true";
            const icone = document.getElementById('icone-camera');
            const texto = document.getElementById('texto-status-foto');
            if (icone) { icone.className = "bi bi-check-circle-fill text-success"; icone.style.fontSize = "3rem"; }
            if (texto) { texto.innerText = "Foto capturada com sucesso!"; texto.className = "text-success fw-bold mt-2"; }
            document.getElementById('label-camera').style.display = 'none';
            document.getElementById('btn-nova-foto').style.display = 'block';
        };
        img.src = imgUrl;
    }
}

// =========================================================================
// LÓGICA DE BAIXA EM MASSA (MODAL E SALVAMENTO)
// =========================================================================

function selecionarTipoMassa(tipo) {
    const rRetida = document.getElementById('radio-retida');
    const rOcorrencia = document.getElementById('radio-ocorrencia');
    const sOcorrencia = document.getElementById('select-ocorrencia-massa');
    const divObs = document.getElementById('campo-observacao-massa');

    if (tipo === 'retida') {
        rRetida.checked = true;
        sOcorrencia.disabled = true;
        divObs.style.display = 'block';
    } else {
        rOcorrencia.checked = true;
        sOcorrencia.disabled = false;
        divObs.style.display = 'none';
    }
}

function abrirModalBaixaMassa() {
    if (notasSelecionadas.size === 0) return;

    // Atualiza contadores
    document.getElementById('qtd-massa-selecionadas').innerText = notasSelecionadas.size;

    // Preenche lista de resumo
    const listaHtml = Array.from(notasSelecionadas).map(numero => {
        const card = document.getElementById(`card-nf-${numero}`);
        const dest = card.querySelector('p.text-muted').innerText.replace('👤 ', '');
        return `<div class="d-flex justify-content-between border-bottom py-1 small">
            <span class="fw-bold">NF ${numero}</span>
            <span class="text-truncate ms-2" style="max-width: 150px;">${dest}</span>
        </div>`;
    }).join('');
    
    document.getElementById('lista-resumo-massa').innerHTML = listaHtml;

    // Reset formulário
    document.getElementById('input-observacao-massa').value = 'Canhotos retidos para conferência';
    selecionarTipoMassa('retida'); // Default

    // Esconde o FAB enquanto o modal está aberto
    const fab = document.getElementById('fab-baixa-massa');
    if (fab) fab.style.display = 'none';

    const modalBaixaMassa = new bootstrap.Modal(document.getElementById('modalBaixaMassa'));
    modalBaixaMassa.show();

    // Quando o modal fechar, restaura o FAB
    document.getElementById('modalBaixaMassa').addEventListener('hidden.bs.modal', function restaurarFab() {
        if (notasSelecionadas.size > 0) {
            fab.style.display = '';
        }
        this.removeEventListener('hidden.bs.modal', restaurarFab);
    });
}

async function salvarBaixaMassa() {
    const tipoSelecionado = document.querySelector('input[name="tipo_baixa_massa"]:checked').value;
    const inputObsMassa = document.getElementById('input-observacao-massa').value;
    const selectOc = document.getElementById('select-ocorrencia-massa').value;

    let cod;
    let isRetida = false;
    let obsStr = '';

    if (tipoSelecionado === 'retida') {
        cod = "1"; // Ocorrência padrão de Entrega para reter canhoto
        isRetida = true;
        obsStr = inputObsMassa.trim() || 'Canhotos retidos para conferência';
    } else {
        if (!selectOc) {
            alert("Selecione qual a ocorrência de Insucesso na lista.");
            return;
        }
        cod = selectOc;
        isRetida = false;
        obsStr = ''; // Insucessos não exigem obs no campo obs retida
    }

    const mID = manifestoAtual || localStorage.getItem('manifesto_ativo');

    // 1. Fecha o Modal de Baixa em Massa
    const modalBaixaMassaEl = document.getElementById('modalBaixaMassa');
    const modalBaixaMassaInstance = bootstrap.Modal.getInstance(modalBaixaMassaEl);
    if (modalBaixaMassaInstance) modalBaixaMassaInstance.hide();

    // 2. Abre a tela de carregamento (Reaproveita o statusModal da baixa unitária)
    atualizarStatusUI('loading', 'Processando Lote...', `Aguarde, estamos processando as ${notasSelecionadas.size} notas...`);
    statusModal.show();

    // 3. Captura GPS (apenas 1 vez para todo o lote para poupar tempo)
    let gpsCoords = { lat: "0.000000", lon: "0.000000" };
    try {
        const coords = await getCoords();
        if (coords && coords.lat && coords.lon) {
            gpsCoords = coords;
        }
    } catch (gpsErr) {
        console.warn("GPS falhou, enviando zerado no lote");
    }

    let falhasLote = 0;

    // 4. Itera e envia cada baixa sequencialmente para não matar a memória do celular
    // A promessa de cada nota é resolvida antes de ir pra próxima (importante para SQLite/Rede Mobile lenta)
    const arrayNotas = Array.from(notasSelecionadas);
    
    for (const numeroNF of arrayNotas) {
        const card = document.getElementById(`card-nf-${numeroNF}`);
        const chaveNF = card ? card.dataset.chave : '';

        const formData = new FormData();
        formData.append('ocorrencia_codigo', cod);
        formData.append('chave_acesso', chaveNF);
        formData.append('numero_nota', numeroNF);
        formData.append('manifesto_id', mID);
        formData.append('recebedor', 'BAIXA EM LOTE');
        formData.append('nota_retida', isRetida);
        formData.append('observacao_retida', obsStr);
        formData.append('latitude', gpsCoords.lat);
        formData.append('longitude', gpsCoords.lon);

        try {
            const response = await authFetch(`${API_BASE}manifesto/registrar-baixa/`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok && response.status >= 500) {
                throw new Error("Erro 500 Lote");
            }

            const data = await response.json();
            if (response.ok) {
                // Sucesso na API
                processarSumiçoNotaSilencioso(numeroNF);
            } else {
                falhasLote++;
                console.error("Erro nota", numeroNF, data.erro);
            }
        } catch (err) {
            // Falha de rede ou 500: Salva local (Offline Mode)
            console.warn("Salvando offline NF", numeroNF);
            try {
                const db = await abrirDB();
                const transaction = db.transaction('baixas_pendentes', 'readwrite');
                const store = transaction.objectStore('baixas_pendentes');

                const objOffline = {
                    id: Date.now().toString() + '_' + numeroNF,
                    numeroNF: numeroNF,
                    chaveNF: chaveNF,
                    mID: mID,
                    campos: {
                        ocorrencia_codigo: cod,
                        recebedor: 'BAIXA EM LOTE',
                        nota_retida: isRetida,
                        observacao_retida: obsStr,
                        latitude: gpsCoords.lat,
                        longitude: gpsCoords.lon
                    },
                    foto: null // Baixa em massa NUNCA tem foto
                };

                store.add(objOffline);
                processarSumiçoNotaSilencioso(numeroNF);
            } catch (dbErr) {
                console.error("Erro crítico salvar offline lote:", dbErr);
                falhasLote++;
            }
        }
    }

    // 5. Finalização
    cancelarModoSelecao();
    atualizarListaViva(mID);
    await atualizarIconeNuvem(); // Atualiza a nuvem caso alguma tenha ficado offline

    if (falhasLote === 0) {
        atualizarStatusUI('success', 'Lote Concluído', `Todas as notas foram baixadas com sucesso.`);
    } else {
        atualizarStatusUI('warning', 'Lote com Alertas', `O lote terminou, mas ${falhasLote} notas não conseguiram ser salvas.`);
    }

    setTimeout(() => {
        statusModal.hide();
        verificarFimDoManifesto(); // Checa se acabaram as notas
    }, 3000);
}

function processarSumiçoNotaSilencioso(numeroNF) {
    const cardParaRemover = document.getElementById(`card-nf-${numeroNF}`);
    if (cardParaRemover) {
        cardParaRemover.classList.add('animate__fadeOutRight');
        setTimeout(() => {
            cardParaRemover.remove();
            atualizarContadorVisual();
        }, 500);
    }
}

// =========================================================================
// Abre o modal de baixa com os dados da nota e configurações específicas
// =========================================================================
function abrirModalBaixa(numeroNota, chaveAcesso, tipo) {
    const tituloEl = document.getElementById('modal-titulo-nf');
    const inputChave = document.getElementById('hidden-chave-nf');
    const inputNumero = document.getElementById('hidden-numero-nf');
    const selectOc = document.getElementById('select-ocorrencia');
    const cameraSection = document.querySelector('.camera-container');
    const cameraLabel = document.getElementById('label-camera');
    const btnNovaFoto = document.getElementById('btn-nova-foto');
    const canvas = document.getElementById('canvas-preview');

    // Elementos da Modificação de Nota Retida
    const checkRetida = document.getElementById('check-nota-retida');
    const campoObs = document.getElementById('campo-observacao');
    const inputObs = document.getElementById('input-observacao');

    // =====================================================
    // 1. LIMPEZA TOTAL (RESET) - PARA NÃO REAPROVEITAR DADOS
    // =====================================================
    if (inputObs) inputObs.value = '';
    document.getElementById('input-recebedor').value = '';

    // Reset da Câmera e Canvas — libera memória GPU reduzindo para 1x1
    canvas.width = 1;
    canvas.height = 1;
    canvas.getContext('2d').clearRect(0, 0, 1, 1);
    canvas.dataset.temFoto = "false";
    canvas.style.display = 'none';

    // Reset Visual do Placeholder (Volta a ser cinza e sem check)
    const icone = document.getElementById('icone-camera');
    const texto = document.getElementById('texto-status-foto');
    if (icone) {
        icone.className = "bi bi-camera text-secondary";
        icone.style.fontSize = "1.8rem";
    }
    if (texto) {
        texto.innerText = "Nenhuma foto capturada";
        texto.className = "text-muted small fw-bold mb-0";
    }

    // Reset dos Botões
    cameraLabel.style.display = 'block';
    btnNovaFoto.style.display = 'none';

    // =====================================================
    // 2. CONFIGURAÇÃO DO MODAL COM OS NOVOS DADOS
    // =====================================================
    tituloEl.innerText = `📝 ${tipo} - NF ${numeroNota}`;
    inputChave.value = (chaveAcesso && chaveAcesso !== 'null') ? chaveAcesso : '';
    if (inputNumero) inputNumero.value = numeroNota || '';

    let inputTipo = document.getElementById('hidden-tipo-operacao');
    if (!inputTipo) {
        inputTipo = document.createElement('input');
        inputTipo.type = 'hidden';
        inputTipo.id = 'hidden-tipo-operacao';
        document.body.appendChild(inputTipo);
    }
    const tipoUpper = (tipo || '').toUpperCase();
    inputTipo.value = tipoUpper;

    // --- FILTRO INTELIGENTE DE OCORRÊNCIAS (DESPACHO vs ENTREGA) ---
    const isDespachoType = tipoUpper.includes('DESPACHO');
    if (selectOc) {
        Array.from(selectOc.options).forEach(opt => {
            const val = opt.value;
            if (isDespachoType) {
                // Em Despacho, NUNCA permite ocorrências 001 ou 002 (Entrega Final)
                if (val === '1' || val === '01' || val === '001' || val === '2' || val === '02' || val === '002') {
                    opt.style.display = 'none';
                    opt.disabled = true;
                } else {
                    opt.style.display = '';
                    opt.disabled = false;
                }
            } else {
                opt.style.display = '';
                opt.disabled = false;
            }
        });

        // Para Despacho, pré-seleciona a ocorrência 050 (Carga Despachada)
        if (isDespachoType) {
            const opt50 = Array.from(selectOc.options).find(o => (o.value === '50' || o.value === '050') && !o.disabled);
            if (opt50) {
                selectOc.value = opt50.value;
            } else {
                const firstValid = Array.from(selectOc.options).find(o => !o.disabled);
                if (firstValid) selectOc.value = firstValid.value;
            }
        } else {
            const firstValid = Array.from(selectOc.options).find(o => !o.disabled);
            if (firstValid) selectOc.value = firstValid.value;
        }
    }

    document.getElementById('placeholder-camera').style.display = 'block';



    // Reset dos campos de Nota Retida
    if (checkRetida) {
        checkRetida.checked = false;
        campoObs.style.display = 'none';

        checkRetida.onchange = function () {
            if (this.checked) {
                cameraSection.style.display = 'none';
                cameraLabel.style.display = 'none';
                btnNovaFoto.style.display = 'none';
                campoObs.style.display = 'block';
            } else {
                if (tipo === 'ENTREGA') {
                    cameraSection.style.display = 'block';
                    cameraLabel.style.display = 'block';
                }
                campoObs.style.display = 'none';
            }
        };
    }

    // REGRA DE OURO
    if (tipo !== 'ENTREGA') {
        cameraSection.style.display = 'none';
        cameraLabel.style.display = 'none';
        btnNovaFoto.style.display = 'none';
        if (TEMA_OPERACAO[tipo]) selectOc.value = TEMA_OPERACAO[tipo].code;
    } else {
        cameraSection.style.display = 'block';
        cameraLabel.style.display = 'block';
        selectOc.value = '1';
    }

    new bootstrap.Modal(document.getElementById('modalBaixa')).show();
}
async function carregarDadosCabecalho() {
    try {
        const response = await authFetch(`${API_BASE}motorista/perfil/`);

        if (response && response.ok) {
            const dados = await response.json();
            // Dados do perfil carregados com sucesso

            // 1. Atualiza a foto se existir
            const avatarContainer = document.querySelector('.avatar-circle');
            if (dados.foto_url && avatarContainer) {
                avatarContainer.innerHTML = `<img src="${dados.foto_url}" alt="Foto" style="width:100%; height:100%; object-fit:cover; border-radius:50%;">`;
            }

            // 2. Opcional: Se você tiver um campo de nome no header, pode atualizar aqui também
            const nomeExibicao = document.getElementById('nome-motorista');
            if (nomeExibicao) nomeExibicao.innerText = dados.nome;

            // Salva a filial para o WebSocket
            if (dados.filial_id) {
                filialIdMotorista = dados.filial_id;
            }

            // 3. Verifica se tem permissão para usar Galeria (Celulares Fracos)
            if (dados.permitir_upload_galeria) {
                console.log("Liberando uso da Galeria (Workaround Celular Fraco ativo)");
                // Pega os inputs de câmera nativa no HTML
                const inputCameraNativa = document.getElementById('camera-nativa');
                const inputOcorrencia = document.getElementById('foto-ocorrencia'); // se existir outro

                if (inputCameraNativa) {
                    inputCameraNativa.removeAttribute('capture');
                }
                if (inputOcorrencia) {
                    inputOcorrencia.removeAttribute('capture');
                }
            }

            // 4. Envia dados do hardware do celular para o admin saber se é celular fraco
            setTimeout(async () => {
                try {
                    let ram = navigator.deviceMemory ? `${navigator.deviceMemory}GB` : 'Desconhecido';
                    let model = 'Desconhecido';
                    
                    if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) {
                        const hints = await navigator.userAgentData.getHighEntropyValues(['model']);
                        if (hints.model) model = hints.model;
                    }
                    
                    if (ram !== 'Desconhecido' || model !== 'Desconhecido') {
                        authFetch(`${API_BASE}motorista/perfil/`, {
                            method: 'POST',
                            body: JSON.stringify({ modelo_aparelho: model, memoria_ram: ram })
                        });
                    }
                } catch(e) {}
            }, 3000); // Executa 3 segundos depois pra não atrasar o carregamento da tela

        } else {
            console.log("Não foi possível carregar os dados do perfil ou motorista anônimo.");
        }
    } catch (error) {
        console.error("Erro ao buscar dados do motorista:", error);
    }
}
async function iniciarSincronismo(numeroManifesto) {
    const modalElement = document.getElementById('modalSincronismo');
    const modalSinc = new bootstrap.Modal(modalElement);

    // Elementos internos do modal
    const elStatus = document.getElementById('modal-sinc-status');
    const elTitulo = document.getElementById('modal-sinc-titulo');
    const elMensagem = document.getElementById('modal-sinc-mensagem');
    const elProgresso = document.getElementById('modal-sinc-progresso');
    const elBtnFechar = document.getElementById('modal-sinc-btn-fechar');

    // Resetar modal para estado inicial (Carregando)
    elStatus.innerHTML = '<div class="spinner-border text-primary mb-3" style="width: 3rem; height: 3rem;"></div>';
    elTitulo.innerText = "Sincronizando Notas";
    elMensagem.innerText = "Estamos buscando novas notas no sistema da ESL. Por favor, aguarde alguns instantes.";
    elProgresso.classList.remove('d-none');
    elBtnFechar.classList.add('d-none');

    modalSinc.show();

    try {
        // Importante: use o authFetch para garantir que o Token seja enviado!
        const response = await authFetch(`${API_BASE}manifesto/sincronizar/`, {
            method: 'POST',
            body: JSON.stringify({ numero_manifesto: numeroManifesto })
        });

        if (response && response.ok) {
            // Sucesso
            setTimeout(() => {
                elStatus.innerHTML = '<i class="bi bi-check-circle-fill text-success" style="font-size: 3rem;"></i>';
                elTitulo.innerText = "Sucesso!";
                elMensagem.innerText = "Notas sincronizadas. A página será atualizada.";
                elProgresso.classList.add('d-none');

                setTimeout(() => {
                    modalSinc.hide();
                    window.location.reload();
                }, 2000);
            }, 5000); // Aguarda um pouco para a task começar
        } else {
            // Erro de Resposta (401, 404, 500...)
            throw new Error(response.status === 401 ? "Sessão expirada. Faça login novamente." : "Falha na comunicação com o servidor.");
        }
    } catch (error) {
        // Exibe o erro dentro do Modal em vez de Alert
        elStatus.innerHTML = '<i class="bi bi-exclamation-triangle-fill text-danger" style="font-size: 3rem;"></i>';
        elTitulo.innerText = "Erro na Sincronização";
        elMensagem.innerHTML = `<span class="text-danger">${error.message}</span>`;
        elProgresso.classList.add('d-none');
        elBtnFechar.classList.remove('d-none'); // Deixa o motorista fechar o modal
    }
}
// =============================================================================
// Função para atualizar o ícone de nuvem no header com base nas baixas pendentes
// =============================================================================
async function atualizarIconeNuvem() {
    try {
        const db = await abrirDB();
        const transaction = db.transaction('baixas_pendentes', 'readonly');
        const store = transaction.objectStore('baixas_pendentes');

        const request = store.count();

        request.onsuccess = function () {
            const totalPendentes = request.result;
            const container = document.getElementById('nuvem-status');
            if (!container) return;

            if (totalPendentes > 0) {
                // Nuvem AMARELA: Notas presas no celular
                // animate__pulse faz ela ficar "batendo" como um coração
                container.innerHTML = `
                    <div class="position-relative animate__animated animate__pulse animate__infinite">
                        <i class="bi bi-cloud-arrow-up-fill text-warning" style="font-size: 1.8rem;" title="Notas pendentes"></i>
                        <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger" 
                              style="font-size: 0.7rem; min-width: 20px; border: 2px solid white;">
                            ${totalPendentes}
                        </span>
                    </div>`;
            } else {
                // Nuvem VERDE: Tudo sincronizado com o servidor
                // animate__bounceIn faz ela dar um "pulo" quando termina de enviar
                container.innerHTML = `
                    <div class="animate__animated animate__bounceIn">
                        <i class="bi bi-cloud-check-fill text-success" style="font-size: 1.8rem;" title="Tudo sincronizado"></i>
                    </div>`;

                // Remove a animação após 2 segundos para ficar estática e limpa
                setTimeout(() => {
                    const el = container.querySelector('.animate__animated');
                    if (el) el.classList.remove('animate__animated', 'animate__bounceIn');
                }, 2000);
            }
        };
    } catch (err) {
        console.error("Erro ao atualizar ícone da nuvem:", err);
    }
}

// =====================================================
// UTILITÁRIOS FINAIS
// =====================================================

function stopPolling() {
    if (pollingInterval) { clearInterval(pollingInterval); pollingInterval = null; }
}

function initModals() {
    const loadingEl = document.getElementById('loadingModal');
    if (loadingEl) loadingModal = new bootstrap.Modal(loadingEl, { backdrop: 'static', keyboard: false });
}

function getCoords() {
    return new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
            (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
            () => resolve(null),
            { timeout: 5000, enableHighAccuracy: true }
        );
    });
}

// O Coração de Rastreamento (Heartbeat) foi movido para o arquivo pwa_tracking.js
// para garantir estabilidade e melhor gerenciamento de cache no PWA.

function abrirModalDetalhes(dados) {
    const container = document.getElementById('modal-detalhes-body');
    if (!container) return;
    container.innerHTML = `
        <div class="mb-2 small"><strong>📅 Data:</strong> ${dados.data}</div>
        <div class="mb-2 small"><strong>👤 Recebedor:</strong> ${dados.recebedor || 'Não informado'}</div>
        <div class="mb-3 small">
            <strong>📝 Ocorrência:</strong> 
            <span class="badge bg-primary text-white">
                ${dados.ocorrencia || 'Não informada'}
            </span>
        </div>
        ${dados.foto_url ? `<img src="${dados.foto_url}" class="img-fluid rounded border shadow-sm w-100 mb-3">` : ''}
    `;
    new bootstrap.Modal(document.getElementById('modalDetalhes')).show();
}

async function atualizarDadosHeader() {
    try {
        const res = await authFetch(`${AUTH_BASE}perfil/`);
        const data = await res.json();
        if (data && data.nome) document.getElementById('header-nome-motorista').textContent = data.nome.split(' ')[0];
    } catch (e) { console.error("Erro no header"); }
}

// 1. FILTRAGEM COM SANITIZAÇÃO (Apenas números)
function beep() {
    const audio = new Audio(
        "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YRAAAAAA/////w=="
    );
    audio.play().catch(() => { });
}
function filtrarNotasOffline() {
    const input = document.getElementById('input-busca-nfe');
    // REMOVE TUDO QUE NÃO É NÚMERO AO DIGITAR
    const termo = input.value.replace(/\D/g, '');
    input.value = termo; // Atualiza o campo visualmente apenas com números

    const cards = document.querySelectorAll('#lista-notas-container .card');
    cards.forEach(card => {
        const textoCard = card.innerText.replace(/\D/g, ''); // Limpa o texto do card para comparar
        const chave = card.getAttribute('data-chave') || "";

        if (textoCard.includes(termo) || chave.includes(termo)) {
            card.style.display = "block";
        } else {
            card.style.display = "none";
        }
    });
}

// 2. SCANNER EM TEMPO REAL (Usando ZXing)
let codeReader = null;
let lendo = false;

function abrirScanner() {
    const modalEl = document.getElementById('scannerModal');
    const modal = new bootstrap.Modal(modalEl);

    lendo = false;
    modal.show();

    modalEl.addEventListener('shown.bs.modal', async () => {
        try {
            codeReader = new ZXing.BrowserMultiFormatReader();

            await codeReader.decodeFromConstraints(
                {
                    video: {
                        facingMode: { ideal: "environment" },
                        width: { ideal: 1920 },
                        height: { ideal: 1080 }
                    }
                },
                document.getElementById('video-scanner'),
                (result, err) => {
                    if (result && !lendo) {
                        lendo = true;

                        const codigo = result.text.replace(/\D/g, '');
                        console.log("Código lido:", codigo);

                        // 1️⃣ Preenche campo de busca
                        const campoBusca = document.getElementById('input-busca-nfe');
                        campoBusca.value = codigo;
                        toggleClearButton();
                        filtrarNotasOffline();

                        // 2️⃣ Filtra a lista
                        filtrarNotasOffline();

                        // 3️⃣ Feedback
                        beep();
                        if (navigator.vibrate) navigator.vibrate(150);

                        // 4️⃣ Fecha scanner e modal
                        pararScanner();
                        modal.hide();
                    }
                }
            );

        } catch (err) {
            alert("Erro ao acessar a câmera: " + err);
            console.error(err);
        }
    }, { once: true });
}

function pararScanner() {
    if (codeReader) {
        codeReader.reset(); // libera a câmera
        codeReader = null;
    }
}


async function lerCodigoBarra(input) {
    if (!input.files || !input.files[0]) return;

    const btnCamera = input.parentElement.querySelector('button');
    const iconeOriginal = btnCamera.innerHTML;
    btnCamera.innerHTML = '<div class="spinner-border spinner-border-sm text-primary"></div>';

    let imageUrl = null;

    try {
        const codeReader = new ZXing.BrowserMultiFormatReader();
        imageUrl = URL.createObjectURL(input.files[0]);

        const result = await codeReader.decodeFromImageUrl(imageUrl);

        const codigo = result.text.replace(/\D/g, '');
        console.log("Código lido (imagem):", codigo);

        // 1️⃣ Preenche campo de busca
        const campoBusca = document.getElementById('input-busca-nfe');
        campoBusca.value = codigo;
        toggleClearButton();
        filtrarNotasOffline();

        // 2️⃣ Filtra lista
        filtrarNotasOffline();

        // 3️⃣ Feedback
        beep();
        if (navigator.vibrate) navigator.vibrate(150);

    } catch (err) {
        alert("Não foi possível ler o código de barras. Tente aproximar mais a câmera ou digitar a NF.");
        console.error("Erro leitura imagem:", err);
    } finally {
        btnCamera.innerHTML = iconeOriginal;
        if (imageUrl) URL.revokeObjectURL(imageUrl);
    }
}
function toggleClearButton() {
    const input = document.getElementById('input-busca-nfe');
    const btn = document.getElementById('btn-limpar-busca');

    if (!input || !btn) return;

    if (input.value.trim().length > 0) {
        btn.classList.remove('d-none');
    } else {
        btn.classList.add('d-none');
    }
}

function limparBusca() {
    const input = document.getElementById('input-busca-nfe');
    if (!input) return;

    input.value = "";
    input.focus();

    toggleClearButton();
    filtrarNotasOffline();
}

// Função para registrar a chegada de todas as transferências de uma vez
async function registrarChegadaColetiva(manifestoId) {
    // 1. Criamos o modal de confirmação dinâmico (Para evitar o 'confirm' do navegador)
    const modalConfirmHTML = `
    <div class="modal fade" id="modalConfirmMassa" tabindex="-1" aria-hidden="true" data-bs-backdrop="static">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow-lg" style="border-radius: 20px;">
                <div class="modal-body text-center p-4">
                    <div class="mb-3">
                        <i class="bi bi-exclamation-circle-fill text-primary" style="font-size: 3.5rem;"></i>
                    </div>
                    <h5 class="fw-bold">Chegada na Filial</h5>
                    <p class="text-muted">Deseja registrar a chegada de <b>TODAS</b> as notas de transferência deste manifesto?</p>
                    
                    <div class="d-grid gap-2 mt-4">
                        <button class="btn btn-primary btn-lg fw-bold" id="btn-confirmar-massa">
                            SIM, REGISTRAR TUDAS
                        </button>
                        <button class="btn btn-light" data-bs-dismiss="modal">CANCELAR</button>
                    </div>
                </div>
            </div>
        </div>
    </div>`;

    document.body.insertAdjacentHTML('beforeend', modalConfirmHTML);
    const mConfirm = new bootstrap.Modal(document.getElementById('modalConfirmMassa'));
    mConfirm.show();

    // 2. Ação ao clicar em confirmar no modal
    document.getElementById('btn-confirmar-massa').onclick = async () => {
        mConfirm.hide(); // Fecha o modal de pergunta

        // Abre o modal de status (Carregando)
        statusModal.show();
        atualizarStatusUI('loading', 'Processando Lote...', 'Enfileirando notas para integração com ESL.');

        try {
            const response = await authFetch(`${API_BASE}manifesto/baixa-operacional/`, {
                method: 'POST',
                body: JSON.stringify({
                    tipo_operacao: 'TRANSFERENCIA',
                    manifesto_id: manifestoId, // 👈 Corrigido para usar o parâmetro da função
                    chave_acesso: null,        // Indica ao backend que é o lote todo
                    is_completo: true
                })
            });

            if (response.ok) {
                atualizarStatusUI('success', '✅ Registro Concluído', 'A fila de chegada foi processada com sucesso.');
                // Recarrega após 2 segundos para atualizar a lista no PWA
                setTimeout(() => location.reload(), 2000);
            } else {
                const erroData = await response.json();
                atualizarStatusUI('error', '❌ Falha na Operação', erroData.erro || 'Erro ao processar lote.');
            }
        } catch (e) {
            atualizarStatusUI('error', '📡 Erro de Rede', 'Verifique sua conexão com a internet.');
        }
    };

    // Remove o HTML do modal do site ao fechar para não dar conflito depois
    document.getElementById('modalConfirmMassa').addEventListener('hidden.bs.modal', function () {
        this.remove();
    });
}

// Função para abrir o modal de pergunta operacional (Despacho ou Retirada)

function abrirModalPerguntaOperacional(numeroNota, chave, tipo) {
    const titulo = tipo === 'DESPACHO' ? "Confirmar Despacho" : "Confirmar Retirada";
    const pergunta = tipo === 'DESPACHO' ? "O embarque foi completo?" : "A retirada foi completa?";

    // Injeta o HTML do modal dinamicamente no body
    const modalHtml = `
    <div class="modal fade" id="modalOperacional" tabindex="-1" aria-hidden="true" data-bs-backdrop="static">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content shadow-lg border-0" style="border-radius: 20px;">
                <div class="modal-body text-center p-4">
                    <div class="mb-3">
                        <i class="bi bi-question-circle-fill text-warning" style="font-size: 3.5rem;"></i>
                    </div>
                    <h5 class="fw-bold">${titulo}</h5>
                    <p class="text-muted">NF: ${numeroNota}</p>
                    <p class="mb-4">${pergunta}</p>
                    
                    <div class="d-grid gap-2">
                        <button class="btn btn-success btn-lg fw-bold" onclick="executarBaixaOp('${chave}', '${tipo}', true)">
                            SIM (Completo)
                        </button>
                        <button class="btn btn-outline-danger" onclick="executarBaixaOp('${chave}', '${tipo}', false)">
                            NÃO (Parcial)
                        </button>
                        <button class="btn btn-link text-muted" data-bs-dismiss="modal">Cancelar</button>
                    </div>
                </div>
            </div>
        </div>
    </div>`;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const m = new bootstrap.Modal(document.getElementById('modalOperacional'));
    m.show();

    // Limpa o HTML do modal ao fechar para não poluir o DOM
    document.getElementById('modalOperacional').addEventListener('hidden.bs.modal', function () {
        this.remove();
    });
}

async function executarBaixaOp(chave, tipo, isCompleto) {
    const modalEl = document.getElementById('modalOperacional');
    const bootstrapModal = bootstrap.Modal.getInstance(modalEl);
    if (bootstrapModal) bootstrapModal.hide();

    atualizarStatusUI('loading', 'Processando...', 'Sincronizando com a fila do sistema.');
    statusModal.show();

    const dadosBaixa = {
        tipo_operacao: tipo,
        chave_acesso: chave,
        manifesto_id: manifestoAtual, // Usando sua variável global
        is_completo: isCompleto,
        data_registro: new Date().toISOString()
    };

    try {
        const response = await authFetch(`${API_BASE}manifesto/baixa-operacional/`, {
            method: 'POST',
            body: JSON.stringify(dadosBaixa)
        });

        if (response && response.ok) {
            atualizarStatusUI('success', '✅ Sucesso!', 'Ocorrência enviada para processamento.');

            // CORREÇÃO: Usando a variável global manifestoAtual
            setTimeout(() => {
                statusModal.hide();
                if (typeof atualizarListaViva === 'function') {
                    atualizarListaViva(manifestoAtual);
                }
            }, 1500);

        } else {
            throw new Error('Erro no servidor');
        }

    } catch (err) {
        console.warn("📡 Salvando no IndexedDB devido a falha de rede/servidor...");

        try {
            const db = await abrirDB();
            const tx = db.transaction('baixas_pendentes', 'readwrite');
            const store = tx.objectStore('baixas_pendentes');

            await store.put({
                chaveNF: chave,
                dados: dadosBaixa,
                tipo: 'operacional',
                timestamp: Date.now()
            });

            atualizarStatusUI('warning', '📡 Modo Offline', 'Sem sinal! A baixa será enviada automaticamente depois.');

            setTimeout(() => {
                statusModal.hide();
                if (typeof atualizarListaViva === 'function') {
                    atualizarListaViva(manifestoAtual);
                }
            }, 2000);

        } catch (dbErr) {
            console.error("Erro crítico ao salvar no IndexedDB:", dbErr);
            atualizarStatusUI('error', '❌ Falha Crítica', 'Erro ao salvar localmente.');
        }
    }
}
// Função para transferência unitária (Nota por Nota)
async function confirmarTransferenciaIndividual(numeroNota, chave) {
    const confirmar = await new Promise(resolve => {
        // Usando um modal de confirmação limpo em vez de alert
        const modalConfirmHTML = `
        <div class="modal fade" id="modalConfirmTransf" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content border-0 shadow" style="border-radius: 15px;">
                    <div class="modal-body text-center p-4">
                        <i class="bi bi-info-circle text-primary" style="font-size: 3rem;"></i>
                        <h5 class="fw-bold mt-3">Registrar Chegada</h5>
                        <p class="text-muted">Deseja confirmar a chegada da NF ${numeroNota} na filial?</p>
                        <div class="d-grid gap-2 mt-4">
                            <button class="btn btn-primary fw-bold" id="btn-ok-transf">CONFIRMAR</button>
                            <button class="btn btn-light" data-bs-dismiss="modal">CANCELAR</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', modalConfirmHTML);
        const m = new bootstrap.Modal(document.getElementById('modalConfirmTransf'));
        m.show();

        document.getElementById('btn-ok-transf').onclick = () => { m.hide(); resolve(true); };
        document.getElementById('modalConfirmTransf').addEventListener('hidden.bs.modal', function () { this.remove(); resolve(false); });
    });

    if (confirmar) {
        // Chama a mesma lógica de execução enviando is_completo=true (pois 098 é fixo)
        executarBaixaOp(chave, 'TRANSFERENCIA', true);
    }
}

// =====================================================
// LÓGICA DE COLETA (NOVO FLUXO)
// =====================================================

let motivosColetaCache = null;

async function carregarMotivosColeta() {
    if (motivosColetaCache) return motivosColetaCache;
    
    try {
        const response = await authFetch(`${API_BASE}manifesto/ocorrencias/?is_coleta=true`);
        if (response.ok) {
            motivosColetaCache = await response.json();
            return motivosColetaCache;
        }
    } catch (e) {
        console.warn("Erro ao buscar motivos de coleta", e);
    }
    
    // Fallback caso a API falhe ou offline
    return [
        { codigo_tms: "004", descricao: "Coleta não Realizada" },
        { codigo_tms: "020", descricao: "Falta de Tempo Hábil" },
        { codigo_tms: "021", descricao: "Estabelecimento Fechado" },
        { codigo_tms: "041", descricao: "Retorno para ARMAZENAGEM por devolução do cliente" },
        { codigo_tms: "044", descricao: "Tempo de espera no cliente excedido" }
    ];
}

function abrirModalColeta(numero, pickId, tipo) {
    console.log("📦 Abrindo modal de Coleta:", numero);
    const modalColeta = new bootstrap.Modal(document.getElementById('modalColeta'));
    const btnSim = document.getElementById('btn-coleta-sim');
    const btnNao = document.getElementById('btn-coleta-nao');
    
    // Elementos do novo UI
    const containerPergunta = document.getElementById('coleta-pergunta-container');
    const containerMotivo = document.getElementById('coleta-motivo-container');
    const footerCancelar = document.getElementById('coleta-footer-cancelar');
    const selectMotivo = document.getElementById('select-coleta-motivo');
    const obsMotivo = document.getElementById('obs-coleta-motivo');
    const btnConfirmarMotivo = document.getElementById('btn-confirmar-nao-coleta');
    const btnVoltarColeta = document.getElementById('btn-voltar-coleta');

    // Reset da UI para estado inicial (Pergunta Sim/Não)
    containerPergunta.classList.remove('d-none');
    containerMotivo.classList.add('d-none');
    footerCancelar.classList.remove('d-none');
    selectMotivo.value = "";
    obsMotivo.value = "";

    // Remove listeners antigos para evitar disparos duplos
    const novoBtnSim = btnSim.cloneNode(true);
    btnSim.parentNode.replaceChild(novoBtnSim, btnSim);

    const novoBtnNao = btnNao.cloneNode(true);
    btnNao.parentNode.replaceChild(novoBtnNao, btnNao);
    
    const novoBtnConfirmar = btnConfirmarMotivo.cloneNode(true);
    btnConfirmarMotivo.parentNode.replaceChild(novoBtnConfirmar, btnConfirmarMotivo);
    
    const novoBtnVoltar = btnVoltarColeta.cloneNode(true);
    btnVoltarColeta.parentNode.replaceChild(novoBtnVoltar, btnVoltarColeta);

    // Ações
    novoBtnSim.onclick = () => {
        modalColeta.hide();
        salvarRegistroColeta(pickId, '1', 'Coleta realizada com sucesso');
    };

    novoBtnNao.onclick = async () => {
        // Mostra a tela de motivo
        containerPergunta.classList.add('d-none');
        footerCancelar.classList.add('d-none');
        containerMotivo.classList.remove('d-none');
        
        // Carrega motivos se ainda não estiver carregado no select
        if (selectMotivo.options.length <= 1) {
            selectMotivo.innerHTML = '<option value="" disabled selected>Carregando motivos...</option>';
            const motivos = await carregarMotivosColeta();
            selectMotivo.innerHTML = '<option value="" disabled selected>Selecione um motivo...</option>';
            motivos.forEach(motivo => {
                // Não adiciona a ocorrência 1 (sucesso) na lista de problemas
                if (motivo.codigo_tms !== "001" && motivo.codigo_tms !== "1") {
                    selectMotivo.innerHTML += `<option value="${motivo.codigo_tms}">${motivo.codigo_tms} - ${motivo.descricao}</option>`;
                }
            });
        }
    };
    
    novoBtnVoltar.onclick = () => {
        containerMotivo.classList.add('d-none');
        containerPergunta.classList.remove('d-none');
        footerCancelar.classList.remove('d-none');
    };
    
    novoBtnConfirmar.onclick = () => {
        const codigo = selectMotivo.value;
        const obs = obsMotivo.value.trim();
        
        if (!codigo) {
            alert("Por favor, selecione um motivo.");
            return;
        }
        
        modalColeta.hide();
        salvarRegistroColeta(pickId, codigo, obs || selectMotivo.options[selectMotivo.selectedIndex].text);
    };

    modalColeta.show();
}

async function salvarRegistroColeta(pickId, codigoOcorrencia, observacao) {
    atualizarStatusUI('loading', 'Registrando Coleta...', 'Aguarde um momento.');
    statusModal.show();

    let lat = 0, lng = 0;
    try {
        const pos = await obterPosicaoGPS();
        lat = pos.coords.latitude;
        lng = pos.coords.longitude;
    } catch (e) {
        console.warn("GPS não capturado para coleta.");
    }

    const formData = new FormData();
    formData.append('tipo_operacao', 'COLETA');
    formData.append('nota_id_tms', pickId);
    formData.append('ocorrencia_codigo', codigoOcorrencia);
    formData.append('latitude', lat);
    formData.append('longitude', lng);
    formData.append('observacao_app', observacao);
    formData.append('data_registro', new Date().toISOString());
    formData.append('manifesto_id', manifestoAtual);

    try {
        const response = await authFetch(`${API_BASE}manifesto/registrar-baixa/`, {
            method: 'POST',
            body: formData
        });

        if (response && response.ok) {
            atualizarStatusUI('success', '✅ Coleta Registrada', 'Informações enviadas com sucesso.');
            setTimeout(() => {
                statusModal.hide();
                atualizarListaViva(manifestoAtual);
            }, 1500);
        } else {
            throw new Error('Falha no servidor');
        }
    } catch (err) {
        console.warn("Coleta salva offline (IndexedDB)");
        try {
            const db = await abrirDB();
            const tx = db.transaction('baixas_pendentes', 'readwrite');
            const store = tx.objectStore('baixas_pendentes');

            const objOffline = {
                id: Date.now().toString(),
                numeroNF: pickId,
                chaveNF: '', // Coleta não usa chave de 44 dígitos
                mID: manifestoAtual,
                campos: {
                    tipo_operacao: 'COLETA',
                    nota_id_tms: pickId,
                    ocorrencia_codigo: codigoOcorrencia,
                    latitude: lat,
                    longitude: lng,
                    observacao_app: observacao,
                    data_registro: new Date().toISOString()
                },
                foto: null
            };

            await store.put(objOffline);

            await atualizarIconeNuvem();

            atualizarStatusUI('warning', '📡 Modo Offline', 'Sinal fraco. A coleta será sincronizada depois.');
            setTimeout(() => {
                statusModal.hide();
                atualizarListaViva(manifestoAtual);
            }, 2000);
        } catch (dbErr) {
            atualizarStatusUI('error', '❌ Erro Crítico', 'Não foi possível salvar a coleta.');
        }
    }
}


// =====================================================
// LOADING NOVO CARREGAMENTO
// =====================================================
function mostrarSkeletonLoading() {
    const content = document.getElementById('app-content');
    if (!content) return;

    // A mesma estrutura do HTML acima
    const cardNF = `
        <div class="skeleton-card-nf">
            <div class="d-flex justify-content-between mb-3">
                <div class="skeleton-line shimmer-effect" style="width: 40%; height: 18px;"></div>
                <div class="skeleton-line shimmer-effect" style="width: 25px; height: 25px; border-radius: 50%;"></div>
            </div>
            <div class="skeleton-line shimmer-effect" style="width: 85%; height: 12px;"></div>
            <div class="skeleton-line shimmer-effect" style="width: 65%; height: 12px;"></div>
            <div class="skeleton-line shimmer-effect w-100" style="height: 38px; margin-top: 12px; border-radius: 8px;"></div>
        </div>
    `;

    content.innerHTML = `
        <div class="p-3 animate__animated animate__fadeIn">
            <div class="shimmer-effect mb-4" style="height: 55px; width: 100%; border-radius: 15px;"></div>
            <div class="shimmer-effect mb-3" style="height: 25px; width: 140px; border-radius: 5px;"></div>
            ${cardNF}
            ${cardNF}
        </div>
    `;
}
// =====================================================
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
        atualizarIconeNuvem();
        // Tenta sincronizar automaticamente caso o motorista tenha acabado de abrir com net
        sincronizarBaixasPendentes();
    }, 1500);
});



// 1. Escuta quando o navegador avisa que a internet VOLTOU
window.addEventListener('online', () => {
    console.log("📡 Sinal de rede detectado! Iniciando sincronização...");

    // Damos 3 segundos para a conexão estabilizar antes de tentar subir
    setTimeout(() => {
        sincronizarBaixasPendentes();
    }, 3000);
});

// 2. Escuta quando a internet CAIU (para atualizar o ícone na hora)
window.addEventListener('offline', () => {
    console.log("🚫 O dispositivo ficou offline.");
    atualizarIconeNuvem();
});

setInterval(() => {
    if (navigator.onLine) {
        console.log("⏰ Verificação periódica de notas pendentes...");
        sincronizarBaixasPendentes();
    }
}, 5 * 60 * 1000); // 5 minutos em milissegundos

// =====================================================
// 3. REFRESH SUAVE AO VOLTAR DO BACKGROUND (APK / PWA)
// Quando o motorista minimiza o app (ex: vai pro Waze) e volta,
// fazemos um refresh dos dados SEM recarregar a página inteira.
// =====================================================
let _ultimoRetornoBackground = 0;
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        const agora = Date.now();
        // Debounce: só executa se passou pelo menos 10 segundos desde o último refresh
        if (agora - _ultimoRetornoBackground < 10000) return;
        _ultimoRetornoBackground = agora;

        console.log("🔄 [Background Return] App voltou ao foco! Atualizando dados...");

        // 1. Tenta sincronizar baixas que ficaram pendentes
        if (navigator.onLine) {
            sincronizarBaixasPendentes();
        }

        // 2. Se tem manifesto ativo, atualiza a lista de notas (refresh suave)
        const mID = manifestoAtual || localStorage.getItem('manifesto_ativo');
        if (mID && navigator.onLine) {
            atualizarListaViva(mID);
        }

        // 3. Atualiza ícone de nuvem (status de conexão)
        atualizarIconeNuvem();
    }
});

