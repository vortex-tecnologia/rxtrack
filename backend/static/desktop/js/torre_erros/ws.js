document.addEventListener("DOMContentLoaded", function() {
    let currentPage = 1;
    let isLoading = false;
    let hasNext = true;

    const tableBody = document.getElementById('erros-tbody');
    const loadingSpinner = document.getElementById('loading-spinner');
    const emptyState = document.getElementById('empty-state');
    const loadMoreBtn = document.getElementById('btn-load-more');
    const paginationContainer = document.getElementById('pagination-container');
    
    // Contadores
    const countCriticos = document.getElementById('count-criticos');
    const countAtencao = document.getElementById('count-atencao');
    const countInfo = document.getElementById('count-info');
    const countResolvidos = document.getElementById('count-resolvidos');

    // Filtros
    const filterSeveridade = document.getElementById('filter-severidade');
    const filterCategoria = document.getElementById('filter-categoria');
    const btnRefresh = document.getElementById('btn-refresh');

    // Inicializar
    carregarErros(true);

    // Eventos dos filtros
    filterSeveridade.addEventListener('change', () => carregarErros(true));
    filterCategoria.addEventListener('change', () => carregarErros(true));
    btnRefresh.addEventListener('click', () => carregarErros(true));
    loadMoreBtn.addEventListener('click', () => {
        if (!isLoading && hasNext) {
            currentPage++;
            carregarErros(false);
        }
    });

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

    function formatDate(isoString) {
        if (!isoString) return '-';
        const date = new Date(isoString);
        return date.toLocaleString('pt-BR');
    }

    function getBadgeClass(severidade) {
        switch(severidade) {
            case 'CRITICO': return 'bg-danger';
            case 'ATENCAO': return 'bg-warning text-dark';
            case 'INFO': return 'bg-info text-dark';
            default: return 'bg-secondary';
        }
    }
    
    function getRowClass(severidade) {
        switch(severidade) {
            case 'CRITICO': return 'row-critico';
            case 'ATENCAO': return 'row-atencao';
            case 'INFO': return 'row-info';
            default: return '';
        }
    }

    function createRowHTML(erro) {
        const refs = [];
        if (erro.manifesto_numero) refs.push(`MFT: ${erro.manifesto_numero}`);
        if (erro.nota_fiscal_numero) refs.push(`NF: ${erro.nota_fiscal_numero}`);
        
        let actions = '';
        if (erro.status === 'ABERTO') {
            actions = `<span class="badge bg-warning text-dark"><i class="bi bi-hourglass-split"></i> Aguardando Ação</span>`;
        } else {
            actions = `<span class="badge bg-success">Resolvido</span>`;
        }

        const qtd = erro.qtd_tentativas || 1;
        const badgeTentativas = qtd > 1 
            ? `<span class="badge bg-danger bg-opacity-75 text-white ms-1 rounded-pill" title="${qtd} tentativas acumuladas para este mesmo erro"><i class="bi bi-arrow-repeat me-1"></i>${qtd}x</span>` 
            : '';

        const dataExibicao = formatDate(erro.atualizado_em || erro.criado_em);

        return `
            <tr id="erro-${erro.id}" class="${getRowClass(erro.severidade)}" style="cursor: pointer;" onclick="abrirModalErro(${erro.id})">
                <td>
                    <span class="badge ${getBadgeClass(erro.severidade)}">${erro.severidade}</span>
                    ${badgeTentativas}
                </td>
                <td><small class="fw-bold text-secondary">${erro.categoria_display}</small></td>
                <td><small>${dataExibicao}</small></td>
                <td>
                    <div class="small fw-bold">${refs.join(' | ')}</div>
                    ${erro.motorista_nome ? `<small class="text-muted"><i class="bi bi-person"></i> ${erro.motorista_nome}</small>` : ''}
                </td>
                <td>
                    <strong class="d-block text-truncate" style="max-width: 250px;" title="${erro.titulo}">${erro.titulo}</strong>
                    <small class="text-muted d-inline-block text-truncate" style="max-width: 300px;" title="${erro.descricao}">${erro.descricao}</small>
                </td>
                <td>${actions}</td>
            </tr>
        `;
    }

    function carregarErros(reset = false) {
        if (reset) {
            currentPage = 1;
            tableBody.innerHTML = '';
            emptyState.classList.add('d-none');
            paginationContainer.classList.add('d-none');
        }
        
        isLoading = true;
        loadingSpinner.classList.remove('d-none');

        const params = new URLSearchParams({
            page: currentPage,
            status: 'ABERTO',
            severidade: filterSeveridade.value,
            categoria: filterCategoria.value
        });

        fetch(`/api/torre-erros/listar/?${params.toString()}`)
            .then(res => res.json())
            .then(data => {
                if (data.status === 'sucesso') {
                    hasNext = data.has_next;
                    
                    if (reset && data.erros.length === 0) {
                        emptyState.classList.remove('d-none');
                    } else {
                        data.erros.forEach(erro => {
                            tableBody.insertAdjacentHTML('beforeend', createRowHTML(erro));
                        });
                        
                        if (hasNext) {
                            paginationContainer.classList.remove('d-none');
                        } else {
                            paginationContainer.classList.add('d-none');
                        }
                    }
                } else {
                    console.error('Erro ao carregar erros:', data.message);
                }
            })
            .catch(err => console.error('Request failed', err))
            .finally(() => {
                isLoading = false;
                loadingSpinner.classList.add('d-none');
            });
    }

    function attachResolverEvents() {
        document.querySelectorAll('.btn-resolver').forEach(btn => {
            // Remove evento anterior para não duplicar
            btn.replaceWith(btn.cloneNode(true));
        });
        
        document.querySelectorAll('.btn-resolver').forEach(btn => {
            btn.addEventListener('click', function() {
                const erroId = this.getAttribute('data-id');
                const btnRef = this;
                btnRef.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
                btnRef.disabled = true;

                fetch(`/api/torre-erros/resolver/${erroId}/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCookie('csrftoken')
                    }
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'sucesso') {
                        // A interface será atualizada pelo WebSocket, mas caso queira já adiantar:
                        const row = document.getElementById(`erro-${erroId}`);
                        if (row) {
                            row.style.opacity = '0.5';
                            btnRef.parentElement.innerHTML = '<span class="badge bg-success">Resolvido</span>';
                        }
                    } else {
                        alert(`Erro: ${data.message}`);
                        btnRef.innerHTML = '<i class="bi bi-check2"></i> Resolver';
                        btnRef.disabled = false;
                    }
                })
                .catch(err => {
                    console.error(err);
                    btnRef.innerHTML = '<i class="bi bi-check2"></i> Resolver';
                    btnRef.disabled = false;
                });
            });
        });
    }

    // ==========================================
    // WEBSOCKET (Atualização em Tempo Real)
    // ==========================================
    const wsFilialId = JSON.parse(document.getElementById('filial-ws-id').textContent) || 'todas';
    const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
    
    // Tentativa de reconexão
    let socket;
    function connectWS() {
        socket = new WebSocket(`${wsScheme}://${window.location.host}/ws/torre-erros/${wsFilialId}/`);

        socket.onopen = function(e) {
            console.log('TorreErros WebSocket conectado');
            const statusBadge = document.getElementById('ws-status');
            statusBadge.classList.remove('bg-danger');
            statusBadge.classList.add('bg-success');
            statusBadge.innerHTML = '<i class="bi bi-circle-fill me-1" style="font-size: 0.5rem;"></i> Conectado';
        };

        socket.onmessage = function(e) {
            const parsedData = JSON.parse(e.data);
            const tipoEvento = parsedData.type;
            const dados = parsedData.dados;

            if (tipoEvento === 'novo_erro') {
                // Atualiza contadores
                if (dados.severidade === 'CRITICO') {
                    countCriticos.innerText = parseInt(countCriticos.innerText) + 1;
                } else if (dados.severidade === 'ATENCAO') {
                    countAtencao.innerText = parseInt(countAtencao.innerText) + 1;
                } else if (dados.severidade === 'INFO') {
                    countInfo.innerText = parseInt(countInfo.innerText) + 1;
                }

                // Insere no topo da tabela se não tiver filtro restritivo aplicado
                if (
                    (!filterSeveridade.value || filterSeveridade.value === dados.severidade) &&
                    (!filterCategoria.value || filterCategoria.value === dados.categoria)
                ) {
                    emptyState.classList.add('d-none');
                    tableBody.insertAdjacentHTML('afterbegin', createRowHTML(dados));
                }

                // Se for crítico, exibe toast/alerta
                if (dados.severidade === 'CRITICO') {
                    mostrarToastNotificacao('Erro Crítico Registrado', dados.titulo, 'danger');
                }

            } else if (tipoEvento === 'atualizacao_erro') {
                // Erro repetido acumulou nova tentativa
                const rowExistente = document.getElementById(`erro-${dados.id}`);
                if (rowExistente) {
                    rowExistente.outerHTML = createRowHTML(dados);
                    const newRow = document.getElementById(`erro-${dados.id}`);
                    if (newRow) {
                        tableBody.prepend(newRow);
                        newRow.style.backgroundColor = 'rgba(255, 193, 7, 0.2)';
                        setTimeout(() => { newRow.style.backgroundColor = ''; }, 1500);
                    }
                } else {
                    if (
                        (!filterSeveridade.value || filterSeveridade.value === dados.severidade) &&
                        (!filterCategoria.value || filterCategoria.value === dados.categoria)
                    ) {
                        emptyState.classList.add('d-none');
                        tableBody.insertAdjacentHTML('afterbegin', createRowHTML(dados));
                    }
                }
            } else if (tipoEvento === 'erro_resolvido') {
                const row = document.getElementById(`erro-${dados.id}`);
                
                // Mostrar toast notificando se foi auto-resolvido
                if (dados.resolvido_por_nome && dados.resolvido_por_nome.includes('Auto')) {
                    mostrarToastNotificacao('✅ Erro Auto-Resolvido', `O erro #${dados.id} foi resolvido automaticamente por uma retentativa.`, 'success');
                }

                if (row) {
                    // Descobre a severidade para decrementar
                    const badgeText = row.querySelector('td .badge').innerText;
                    
                    if (badgeText === 'CRITICO') countCriticos.innerText = Math.max(0, parseInt(countCriticos.innerText) - 1);
                    if (badgeText === 'ATENCAO') countAtencao.innerText = Math.max(0, parseInt(countAtencao.innerText) - 1);
                    if (badgeText === 'INFO') countInfo.innerText = Math.max(0, parseInt(countInfo.innerText) - 1);

                    countResolvidos.innerText = parseInt(countResolvidos.innerText) + 1;
                    
                    // Remove linha com animação suave
                    row.style.transition = 'all 0.5s ease';
                    row.style.opacity = '0';
                    row.style.transform = 'translateX(20px)';
                    setTimeout(() => {
                        row.remove();
                        if (tableBody.children.length === 0) {
                            emptyState.classList.remove('d-none');
                        }
                    }, 500);
                }
            }
        };

        socket.onclose = function(e) {
            console.error('TorreErros WebSocket desconectado inesperadamente');
            const statusBadge = document.getElementById('ws-status');
            statusBadge.classList.remove('bg-success');
            statusBadge.classList.add('bg-danger');
            statusBadge.innerHTML = '<i class="bi bi-x-circle-fill me-1" style="font-size: 0.5rem;"></i> Desconectado';
            
            // Tenta reconectar a cada 5s
            setTimeout(connectWS, 5000);
        };
    }

    connectWS();

    // Helper de Toast (usando Bootstrap)
    function mostrarToastNotificacao(titulo, mensagem, type = 'info') {
        const toastContainer = document.querySelector('.toast-container');
        if (!toastContainer) return;
        
        const toastHTML = `
            <div class="toast align-items-center text-bg-${type} border-0 mb-2" role="alert" aria-live="assertive" aria-atomic="true" data-bs-autohide="true" data-bs-delay="10000">
                <div class="d-flex">
                    <div class="toast-body">
                        <strong class="d-block">${titulo}</strong>
                        ${mensagem}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `;
        
        toastContainer.insertAdjacentHTML('beforeend', toastHTML);
        const toastEl = toastContainer.lastElementChild;
        const toast = new bootstrap.Toast(toastEl);
        toast.show();
        
        toastEl.addEventListener('hidden.bs.toast', () => {
            toastEl.remove();
        });
    }

    // ==========================================
    // MODAIS DE DETALHE E RESOLVIDOS
    // ==========================================
    
    window.abrirModalErro = function(erroId) {
        // Se o modal de resolvidos estiver aberto, escondemos ele para evitar sobreposição
        const modalResolvidosEl = document.getElementById('modalResolvidos');
        if (modalResolvidosEl && modalResolvidosEl.classList.contains('show')) {
            const modalInstance = bootstrap.Modal.getInstance(modalResolvidosEl);
            if (modalInstance) modalInstance.hide();
        }

        fetch(`/api/torre-erros/detalhe/${erroId}/`)
            .then(res => res.json())
            .then(data => {
                if(data.status === 'sucesso') {
                    const e = data.erro;
                    document.getElementById('modalErroSeveridade').className = `badge ${getBadgeClass(e.severidade)}`;
                    document.getElementById('modalErroSeveridade').innerText = e.severidade;
                    document.getElementById('modalErroCategoria').innerText = e.categoria;
                    document.getElementById('modalErroManifesto').innerText = e.manifesto_numero || '-';
                    document.getElementById('modalErroNF').innerText = e.nota_fiscal_numero || '-';
                    document.getElementById('modalErroMotorista').innerText = e.motorista_nome || '-';
                    document.getElementById('modalErroData').innerText = e.criado_em;
                    document.getElementById('modalErroRegra').innerText = e.regra_aplicada;
                    document.getElementById('modalErroDescricao').innerText = e.descricao;
                    document.getElementById('modalErroRaw').innerText = e.erro_raw;

                    // Renderiza histórico de tentativas
                    const containerQtd = document.getElementById('modalErroQtdTentativas');
                    const timelineDiv = document.getElementById('modalErroHistoricoTimeline');
                    if (containerQtd && timelineDiv) {
                        containerQtd.innerText = `${e.qtd_tentativas || 1}x`;
                        
                        let histHtml = '';
                        if (e.historico_tentativas && e.historico_tentativas.length > 0) {
                            e.historico_tentativas.forEach(h => {
                                const isUltima = (h.numero === e.historico_tentativas.length);
                                histHtml += `
                                    <div class="d-flex justify-content-between align-items-center py-1 ${isUltima ? 'fw-bold text-danger' : 'text-muted'}" style="border-bottom: 1px dashed #e0e0e0;">
                                        <span><i class="bi bi-clock me-2"></i>Tentativa #${h.numero}</span>
                                        <span>${h.data_hora} ${isUltima ? '<span class="badge bg-danger text-white ms-1">Mais Recente</span>' : ''}</span>
                                    </div>
                                `;
                            });
                        } else {
                            histHtml = `<div class="text-muted"><i class="bi bi-clock me-2"></i>1ª Tentativa: ${e.criado_em}</div>`;
                        }
                        timelineDiv.innerHTML = histHtml;
                    }
                    
                    const acoesDiv = document.getElementById('modalErroAcoes');
                    const infoResolvido = document.getElementById('modalErroResolvidoInfo');
                    const observacaoInput = document.getElementById('modalErroObservacaoInput');
                    
                    if(e.status === 'ABERTO') {
                        acoesDiv.classList.remove('d-none');
                        infoResolvido.classList.add('d-none');
                        observacaoInput.value = '';
                        
                        const btnResolver = document.getElementById('btnModalResolverErro');
                        btnResolver.onclick = function() {
                            resolverErroModal(e.id);
                        };
                    } else {
                        acoesDiv.classList.add('d-none');
                        infoResolvido.classList.remove('d-none');
                        document.getElementById('modalErroResolvidoPor').innerText = e.resolvido_por || 'Sistema (Auto)';
                        document.getElementById('modalErroDataResolucao').innerText = e.data_resolucao;
                        document.getElementById('modalErroObservacao').innerText = e.observacao_resolucao ? `Obs: ${e.observacao_resolucao}` : '';
                    }

                    const modal = new bootstrap.Modal(document.getElementById('modalErroDetalhe'));
                    modal.show();
                } else {
                    alert('Erro ao carregar detalhes: ' + data.message);
                }
            })
            .catch(err => console.error(err));
    }
    
    function resolverErroModal(erroId) {
        const obs = document.getElementById('modalErroObservacaoInput').value;
        const btnResolver = document.getElementById('btnModalResolverErro');
        btnResolver.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
        btnResolver.disabled = true;

        fetch(`/api/torre-erros/resolver/${erroId}/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ observacao: obs })
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'sucesso') {
                bootstrap.Modal.getInstance(document.getElementById('modalErroDetalhe')).hide();
                // WebSocket já vai esconder a linha
            } else {
                alert(`Erro: ${data.message}`);
            }
        })
        .catch(err => console.error(err))
        .finally(() => {
            btnResolver.innerHTML = '<i class="bi bi-check-lg me-1"></i> Marcar como Resolvido';
            btnResolver.disabled = false;
        });
    }

    let resolvidosPage = 1;
    window.abrirModalResolvidos = function() {
        // Inicializa com data de hoje
        const hoje = new Date().toISOString().split('T')[0];
        document.getElementById('filtroResolvidosInicio').value = hoje;
        document.getElementById('filtroResolvidosFim').value = hoje;
        carregarErrosResolvidos(false);
        
        const modal = new bootstrap.Modal(document.getElementById('modalResolvidos'));
        modal.show();
    }
    
    window.carregarErrosResolvidos = function(loadMore = false) {
        if(!loadMore) {
            resolvidosPage = 1;
            document.getElementById('resolvidos-tbody').innerHTML = '';
        } else {
            resolvidosPage++;
        }
        
        document.getElementById('loading-resolvidos').classList.remove('d-none');
        document.getElementById('btn-load-more-resolvidos').classList.add('d-none');
        
        const dataInicio = document.getElementById('filtroResolvidosInicio').value;
        const dataFim = document.getElementById('filtroResolvidosFim').value;
        
        fetch(`/api/torre-erros/resolvidos/?page=${resolvidosPage}&data_inicio=${dataInicio}&data_fim=${dataFim}`)
            .then(res => res.json())
            .then(data => {
                if(data.status === 'sucesso') {
                    const tbody = document.getElementById('resolvidos-tbody');
                    data.erros.forEach(e => {
                        const refs = [];
                        if (e.manifesto_numero) refs.push(`MFT: ${e.manifesto_numero}`);
                        if (e.nota_fiscal_numero) refs.push(`NF: ${e.nota_fiscal_numero}`);
                        
                        const tr = document.createElement('tr');
                        tr.style.cursor = 'pointer';
                        tr.onclick = () => abrirModalErro(e.id);
                        
                        let resolverHtml = `<strong>${e.resolvido_por_nome}</strong>`;
                        if(e.status === 'AUTO_RESOLVIDO') {
                            resolverHtml = `<span class="badge bg-primary bg-opacity-10 text-primary border border-primary"><i class="bi bi-robot me-1"></i>Auto</span>`;
                        }
                        
                        tr.innerHTML = `
                            <td><span class="badge ${getBadgeClass(e.severidade)}">${e.severidade}</span></td>
                            <td><small class="fw-bold text-secondary">${e.categoria_display}</small></td>
                            <td><small>${e.data_resolucao}</small></td>
                            <td>${resolverHtml}</td>
                            <td>
                                <div class="small fw-bold">${refs.join(' | ')}</div>
                                <div class="text-truncate text-muted small" style="max-width: 250px;">${e.titulo}</div>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                    
                    if(data.has_next) {
                        document.getElementById('btn-load-more-resolvidos').classList.remove('d-none');
                    }
                }
            })
            .catch(err => console.error(err))
            .finally(() => {
                document.getElementById('loading-resolvidos').classList.add('d-none');
            });
    }

});
