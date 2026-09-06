/**
 * roteirizacao_v1.js - RXTrack
 * Módulo de Roteirização Manual do Motorista (PWA / Android Capacitor)
 * 
 * Regras e Especificações:
 * 1. Entidade persistente da sessão do manifesto em localStorage ('rxtrack_rota_${manifestoId}')
 * 2. Três estados estritos: 'PENDENTE', 'ATUAL', 'CONCLUIDA'
 *    - Apenas UMA nota pode ser 'ATUAL' por vez
 *    - Pós-baixa: nota marcada 'CONCLUIDA' e próxima promovida a 'ATUAL'
 * 3. Track é a fonte da verdade da sequência (ordem escolhida pelo motorista não é alterada por Waze/Google)
 * 4. Google Maps: Estratégia de segmentos inteligentes para rotas com > 10 paradas (não descarta nenhuma nota)
 * 5. Waze: Envia somente a parada ATUAL com preparação contínua da próxima
 * 6. Prioridade absoluta para Latitude/Longitude do model NotaFiscal com fallback sanitizado para Endereço
 * 7. Mini-mapa interativo Leaflet 1.9.4 com marcadores numerados e polyline conectando o trajeto
 * 8. Reordenação por arrasto (drag-and-drop) com SortableJS
 */

(function (window, document) {
    'use strict';

    const STORAGE_KEY_PREFIX = 'rxtrack_rota_';
    const PREF_NAV_KEY = 'rxtrack_navegador_preferido';
    const LIMITE_SEGMENTO_GOOGLE = 10; // 1 destino + até 9 waypoints

    let _mapaInstancia = null;
    let _mapaMarkers = [];
    let _mapaPolyline = null;
    let _motoristaMarker = null;
    let _sortableInstancia = null;
    let _itensEdicao = []; // Array de trabalho no modal
    let _posicaoMotorista = null; // { lat, lng }

    // =====================================================
    // 1. UTILITÁRIOS E HIGIENIZAÇÃO
    // =====================================================

    function sanitizarTexto(txt) {
        if (!txt) return '';
        return String(txt)
            .replace(/[\r\n\t]+/g, ' ')
            .replace(/\s{2,}/g, ' ')
            .trim();
    }

    function sanitizarEnderecoParaUrl(end, cep) {
        let base = sanitizarTexto(end);
        if (!base || base.toUpperCase().includes('ENDEREÇO NÃO INFORMADO')) {
            return cep ? `CEP ${cep}, Brasil` : '';
        }
        if (!base.toLowerCase().includes('brasil')) {
            base += ', Brasil';
        }
        return base;
    }

    function coordValida(lat, lng) {
        if (lat === null || lat === undefined || lng === null || lng === undefined) return false;
        const nLat = parseFloat(lat);
        const nLng = parseFloat(lng);
        if (isNaN(nLat) || isNaN(nLng)) return false;
        return (nLat >= -90 && nLat <= 90 && nLng >= -180 && nLng <= 180 && !(nLat === 0 && nLng === 0));
    }

    // Distância Haversine em Km
    function haversineKm(lat1, lon1, lat2, lon2) {
        const R = 6371;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                  Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                  Math.sin(dLon / 2) * Math.sin(dLon / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }

    // =====================================================
    // 2. MÁQUINA DE ESTADOS DA ROTA (PENDENTE, ATUAL, CONCLUIDA)
    // =====================================================

    /**
     * Recalcula rigorosamente os estados das paradas:
     * - 'CONCLUIDA': Se a nota já foi baixada/entregue
     * - 'ATUAL': EXATAMENTE A PRIMEIRA nota selecionada que não está concluída
     * - 'PENDENTE': Todas as notas selecionadas seguintes à atual
     * - 'DESMARCADA': Notas desmarcadas pelo motorista
     */
    function recalcularEstadosRota(paradas) {
        if (!Array.isArray(paradas)) return;

        let achouAtual = false;
        paradas.forEach((p, idx) => {
            p.ordem = idx + 1;
            if (p.selecionada === false) {
                p.estado = 'DESMARCADA';
            } else if (p.concluida === true) {
                p.estado = 'CONCLUIDA';
            } else if (!achouAtual) {
                p.estado = 'ATUAL';
                achouAtual = true;
            } else {
                p.estado = 'PENDENTE';
            }
        });
    }

    // =====================================================
    // 3. PERSISTÊNCIA LOCAL (LOCALSTORAGE)
    // =====================================================

    function obterManifestoIdAtual() {
        return window.manifestoAtual || localStorage.getItem('manifesto_ativo') || null;
    }

    function obterRotaSalva(manifestoId) {
        if (!manifestoId) return null;
        try {
            const raw = localStorage.getItem(STORAGE_KEY_PREFIX + manifestoId);
            if (!raw) return null;
            const rota = JSON.parse(raw);
            if (rota && Array.isArray(rota.paradas)) {
                recalcularEstadosRota(rota.paradas);
            }
            return rota;
        } catch (e) {
            console.warn('[Roteirizacao] Erro ao carregar rota salva:', e);
            return null;
        }
    }

    function salvarRota(manifestoId, rotaData) {
        if (!manifestoId || !rotaData) return;
        try {
            if (Array.isArray(rotaData.paradas)) {
                recalcularEstadosRota(rotaData.paradas);
            }
            rotaData.atualizadoEm = new Date().toISOString();
            localStorage.setItem(STORAGE_KEY_PREFIX + manifestoId, JSON.stringify(rotaData));
        } catch (e) {
            console.error('[Roteirizacao] Erro ao salvar rota:', e);
        }
    }

    function removerRotaSalva(manifestoId) {
        if (!manifestoId) return;
        localStorage.removeItem(STORAGE_KEY_PREFIX + manifestoId);
    }

    // =====================================================
    // 4. EXTRAÇÃO DAS NOTAS DO MANIFESTO (SINCRONIZAÇÃO)
    // =====================================================

    function extrairNotasDoManifesto() {
        const notasOriginais = window.notasGerais || [];
        const manifestoId = obterManifestoIdAtual();
        const rotaSalva = obterRotaSalva(manifestoId);

        const mapaSalvas = new Map();
        if (rotaSalva && Array.isArray(rotaSalva.paradas)) {
            rotaSalva.paradas.forEach((p, idx) => {
                const key = String(p.numero || p.id);
                mapaSalvas.set(key, {
                    ordem: idx,
                    selecionada: p.selecionada !== false,
                    concluida: Boolean(p.concluida)
                });
            });
        }

        const lista = [];
        notasOriginais.forEach((nf, index) => {
            const tipo = nf.tipo_operacao || 'ENTREGA';
            const numero = String((tipo === 'COLETA') ? (nf.numero_coleta || nf.numero_nota || '') : (nf.numero_nota || ''));
            const idNota = String(nf.id || numero);
            const isBaixada = Boolean(nf.ja_baixada || (nf.status && ['BAIXADA', 'OCORRENCIA'].includes(nf.status)));

            const salvoInfo = mapaSalvas.get(numero) || mapaSalvas.get(idNota);

            lista.push({
                id: nf.id,
                numero: numero,
                chave: nf.chave_acesso || '',
                destinatario: sanitizarTexto(nf.destinatario) || 'CLIENTE NÃO INFORMADO',
                endereco: sanitizarTexto(nf.endereco_entrega) || 'ENDEREÇO NÃO INFORMADO',
                cep: nf.cep || '',
                latitude: coordValida(nf.latitude, nf.longitude) ? parseFloat(nf.latitude) : null,
                longitude: coordValida(nf.latitude, nf.longitude) ? parseFloat(nf.longitude) : null,
                tipo: tipo,
                statusOriginal: nf.status,
                concluida: isBaixada || (salvoInfo ? salvoInfo.concluida : false),
                selecionada: salvoInfo ? salvoInfo.selecionada : !isBaixada,
                ordemPrevia: salvoInfo ? salvoInfo.ordem : (9999 + index)
            });
        });

        // Ordena estritamente pela ordem salva prévia; novos itens entram ao final
        lista.sort((a, b) => a.ordemPrevia - b.ordemPrevia);

        // Aplica máquina de estados
        recalcularEstadosRota(lista);

        return lista;
    }

    // =====================================================
    // 5. MAPA LEAFLET & MARCADORES NUMERADOS
    // =====================================================

    async function atualizarLocalizacaoMotorista() {
        try {
            if (typeof window.getCoords === 'function') {
                const coords = await window.getCoords();
                if (coords && coordValida(coords.lat, coords.lon)) {
                    _posicaoMotorista = { lat: coords.lat, lng: coords.lon };
                    return _posicaoMotorista;
                }
            }
        } catch (e) {}

        if (window.ultimaPosicaoNativa && coordValida(window.ultimaPosicaoNativa.lat, window.ultimaPosicaoNativa.lng)) {
            _posicaoMotorista = { lat: window.ultimaPosicaoNativa.lat, lng: window.ultimaPosicaoNativa.lng };
        }
        return _posicaoMotorista;
    }

    function inicializarMapa(containerId) {
        if (!window.L) {
            console.error('[Roteirizacao] Leaflet não carregado.');
            return null;
        }

        const containerEl = document.getElementById(containerId);
        if (!containerEl) return null;

        if (_mapaInstancia) {
            try {
                _mapaInstancia.remove();
            } catch (e) {}
            _mapaInstancia = null;
        }

        const latIni = _posicaoMotorista ? _posicaoMotorista.lat : -22.9068;
        const lngIni = _posicaoMotorista ? _posicaoMotorista.lng : -43.1729;

        _mapaInstancia = L.map(containerId, {
            zoomControl: false,
            attributionControl: false
        }).setView([latIni, lngIni], 13);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19
        }).addTo(_mapaInstancia);

        L.control.zoom({ position: 'bottomright' }).addTo(_mapaInstancia);

        return _mapaInstancia;
    }

    function desenharMapaRoteirizacao() {
        if (!_mapaInstancia) return;

        // Limpa camadas anteriores
        _mapaMarkers.forEach(m => _mapaInstancia.removeLayer(m));
        _mapaMarkers = [];

        if (_mapaPolyline) {
            _mapaInstancia.removeLayer(_mapaPolyline);
            _mapaPolyline = null;
        }
        if (_motoristaMarker) {
            _mapaInstancia.removeLayer(_motoristaMarker);
            _motoristaMarker = null;
        }

        const pontosTrajeto = [];
        const boundsPontos = [];

        // 1. Marcador do Motorista
        if (_posicaoMotorista && coordValida(_posicaoMotorista.lat, _posicaoMotorista.lng)) {
            const motIcon = L.divIcon({
                className: 'custom-leaflet-marker-driver',
                html: `<div class="marker-driver-pulse"><i class="bi bi-truck-front-fill"></i></div>`,
                iconSize: [32, 32],
                iconAnchor: [16, 16]
            });
            _motoristaMarker = L.marker([_posicaoMotorista.lat, _posicaoMotorista.lng], { icon: motIcon })
                .bindPopup('<b>Você está aqui</b>')
                .addTo(_mapaInstancia);

            pontosTrajeto.push([_posicaoMotorista.lat, _posicaoMotorista.lng]);
            boundsPontos.push([_posicaoMotorista.lat, _posicaoMotorista.lng]);
        }

        // 2. Marcadores das Notas Selecionadas
        let seq = 1;
        _itensEdicao.forEach((item) => {
            if (!item.selecionada) return;

            const temCoord = coordValida(item.latitude, item.longitude);
            if (temCoord) {
                const latLng = [item.latitude, item.longitude];
                pontosTrajeto.push(latLng);
                boundsPontos.push(latLng);

                let statusClasse = 'marker-status-pendente';
                let iconeBadge = seq;

                if (item.estado === 'CONCLUIDA') {
                    statusClasse = 'marker-status-concluida';
                    iconeBadge = '<i class="bi bi-check-lg"></i>';
                } else if (item.estado === 'ATUAL') {
                    statusClasse = 'marker-status-atual';
                    iconeBadge = `<span class="fw-bold">${seq}</span>`;
                }

                const badgeIcon = L.divIcon({
                    className: 'custom-leaflet-marker-stop',
                    html: `<div class="marker-stop-badge ${statusClasse}">${iconeBadge}</div>`,
                    iconSize: [30, 30],
                    iconAnchor: [15, 15]
                });

                const marker = L.marker(latLng, { icon: badgeIcon })
                    .bindPopup(`
                        <div class="small">
                            <b>Parada ${seq}:</b> NF #${item.numero}<br>
                            <b>Destinatário:</b> ${item.destinatario}<br>
                            <b>Status:</b> <span class="badge ${item.estado === 'CONCLUIDA' ? 'bg-success' : (item.estado === 'ATUAL' ? 'bg-warning text-dark' : 'bg-primary')}">${item.estado}</span><br>
                            <small class="text-muted">${item.endereco}</small>
                        </div>
                    `)
                    .addTo(_mapaInstancia);

                _mapaMarkers.push(marker);
            }
            seq++;
        });

        // 3. Linha visual conectando os pontos na sequência
        if (pontosTrajeto.length > 1) {
            _mapaPolyline = L.polyline(pontosTrajeto, {
                color: '#2563eb',
                weight: 4,
                opacity: 0.85,
                dashArray: '6, 8',
                lineJoin: 'round'
            }).addTo(_mapaInstancia);
        }

        // 4. Enquadra os pontos
        if (boundsPontos.length > 0) {
            const bounds = L.latLngBounds(boundsPontos);
            _mapaInstancia.fitBounds(bounds, { padding: [35, 35], maxZoom: 16 });
        }
    }

    // =====================================================
    // 6. ESTIMATIVAS DE DISTÂNCIA E TEMPO
    // =====================================================

    function calcularEstimativas() {
        const pontos = [];
        if (_posicaoMotorista && coordValida(_posicaoMotorista.lat, _posicaoMotorista.lng)) {
            pontos.push(_posicaoMotorista);
        }

        let qtdComGps = 0;
        let totalParadasSelecionadas = 0;

        _itensEdicao.forEach(item => {
            if (!item.selecionada) return;
            totalParadasSelecionadas++;
            if (coordValida(item.latitude, item.longitude)) {
                pontos.push({ lat: item.latitude, lng: item.longitude });
                qtdComGps++;
            }
        });

        if (pontos.length < 2) {
            return {
                distanciaKm: null,
                tempoMin: null,
                totalParadas: totalParadasSelecionadas,
                comGps: qtdComGps
            };
        }

        let distanciaDireta = 0;
        for (let i = 0; i < pontos.length - 1; i++) {
            distanciaDireta += haversineKm(pontos[i].lat, pontos[i].lng, pontos[i + 1].lat, pontos[i + 1].lng);
        }

        // Correção de rota urbana (~1.28)
        const distanciaEstimadaKm = Math.round(distanciaDireta * 1.28 * 10) / 10;
        const tempoDeslocamentoHoras = distanciaEstimadaKm / 24;
        const tempoParadasMin = totalParadasSelecionadas * 7;
        const tempoTotalMin = Math.round((tempoDeslocamentoHoras * 60) + tempoParadasMin);

        return {
            distanciaKm: distanciaEstimadaKm,
            tempoMin: tempoTotalMin,
            totalParadas: totalParadasSelecionadas,
            comGps: qtdComGps
        };
    }

    function atualizarPainelEstimativas() {
        const elResumo = document.getElementById('resumo-estimativa-roteiro');
        if (!elResumo) return;

        const est = calcularEstimativas();
        if (est.totalParadas === 0) {
            elResumo.innerHTML = `
                <div class="d-flex align-items-center justify-content-between p-2 rounded bg-light border text-muted small">
                    <span><i class="bi bi-info-circle me-1"></i> Selecione ao menos 1 entrega</span>
                    <span class="badge bg-secondary">0 paradas</span>
                </div>`;
            return;
        }

        const badgeGps = est.comGps < est.totalParadas ?
            `<span class="badge bg-warning text-dark ms-2" title="${est.totalParadas - est.comGps} nota(s) sem coordenadas usam endereço nominal"><i class="bi bi-geo-alt"></i> ${est.comGps}/${est.totalParadas} GPS</span>` :
            `<span class="badge bg-success-subtle text-success ms-2"><i class="bi bi-check-all"></i> 100% GPS</span>`;

        let textoKmTempo = '';
        if (est.distanciaKm !== null) {
            const horas = Math.floor(est.tempoMin / 60);
            const mins = est.tempoMin % 60;
            const tempoFmt = horas > 0 ? `${horas}h ${mins}min` : `${mins} min`;
            textoKmTempo = `<strong>~${est.distanciaKm} km</strong> &bull; <strong>~${tempoFmt}</strong>`;
        } else {
            textoKmTempo = `<span>Roteirização por endereço nominal</span>`;
        }

        elResumo.innerHTML = `
            <div class="d-flex align-items-center justify-content-between p-2 rounded bg-white shadow-xs border">
                <div class="small text-dark">
                    <i class="bi bi-speedometer2 text-primary me-1"></i> ${textoKmTempo}
                </div>
                <div class="d-flex align-items-center">
                    <span class="badge bg-primary rounded-pill">${est.totalParadas} paradas</span>
                    ${badgeGps}
                </div>
            </div>`;
    }

    // =====================================================
    // 7. RENDERIZAÇÃO DA LISTA NO MODAL
    // =====================================================

    function renderizarListaModal() {
        const containerLista = document.getElementById('lista-roteirizacao');
        if (!containerLista) return;

        if (_itensEdicao.length === 0) {
            containerLista.innerHTML = `
                <div class="text-center text-muted p-4">
                    <i class="bi bi-inbox fs-2 d-block mb-2"></i>
                    Nenhuma nota encontrada neste manifesto.
                </div>`;
            return;
        }

        // Garante que os estados PENDENTE, ATUAL, CONCLUIDA estejam sincronizados
        recalcularEstadosRota(_itensEdicao);

        let html = '';
        let seq = 1;

        _itensEdicao.forEach((item, index) => {
            const numeroSeq = item.selecionada ? seq++ : '-';
            const temGps = coordValida(item.latitude, item.longitude);

            let classeCard = 'card-item-roteiro mb-2 border shadow-xs';
            let badgeClasse = 'badge-inativa';
            let statusLabel = '';

            if (item.estado === 'CONCLUIDA') {
                classeCard += ' item-concluido';
                badgeClasse = 'badge-concluida';
                statusLabel = '<span class="badge bg-success-subtle text-success border border-success-subtle py-0" style="font-size: 0.65rem;">CONCLUÍDA</span>';
            } else if (item.estado === 'ATUAL') {
                classeCard += ' item-atual border-warning border-2';
                badgeClasse = 'badge-atual';
                statusLabel = '<span class="badge bg-warning text-dark fw-bold py-0" style="font-size: 0.65rem;"><i class="bi bi-geo-alt-fill me-1"></i>ATUAL</span>';
            } else if (item.estado === 'PENDENTE') {
                badgeClasse = 'badge-ativa';
                statusLabel = '<span class="badge bg-light text-muted border py-0" style="font-size: 0.65rem;">PENDENTE</span>';
            } else {
                classeCard += ' item-desmarcado';
            }

            html += `
                <div class="${classeCard}" data-index="${index}" data-numero="${item.numero}">
                    <div class="card-body p-2 d-flex align-items-center gap-2">
                        <!-- Alça de Arrasto (Handle) -->
                        <div class="drag-handle text-muted px-1 py-2 cursor-grab" title="Arraste para reordenar">
                            <i class="bi bi-grip-vertical fs-5"></i>
                        </div>

                        <!-- Checkbox de Seleção -->
                        <div class="form-check m-0">
                            <input class="form-check-input check-parada" type="checkbox" 
                                   ${item.selecionada ? 'checked' : ''} 
                                   onchange="Roteirizacao.toggleSelecaoItem(${index}, this.checked)">
                        </div>

                        <!-- Badge Numérico -->
                        <div class="badge-sequencia ${badgeClasse}">
                            ${item.estado === 'CONCLUIDA' ? '<i class="bi bi-check-lg"></i>' : numeroSeq}
                        </div>

                        <!-- Destinatário e Endereço -->
                        <div class="flex-grow-1 text-truncate pe-1">
                            <div class="d-flex align-items-center gap-1 mb-0">
                                <span class="fw-bold small text-dark text-truncate">${item.destinatario}</span>
                                ${item.tipo === 'COLETA' ? '<span class="badge bg-dark" style="font-size: 0.62rem;">COLETA</span>' : ''}
                                ${statusLabel}
                            </div>
                            <div class="text-muted text-truncate" style="font-size: 0.72rem;">
                                <i class="bi bi-geo-alt"></i> ${item.endereco}
                            </div>
                        </div>

                        <!-- Indicador GPS -->
                        <div class="text-end">
                            ${temGps ? 
                                '<span class="badge bg-primary-subtle text-primary border border-primary-subtle" style="font-size: 0.65rem;" title="Coordenadas GPS disponíveis">GPS</span>' : 
                                '<span class="badge bg-light text-muted border" style="font-size: 0.65rem;" title="Navegação via endereço">Texto</span>'
                            }
                        </div>
                    </div>
                </div>`;
        });

        containerLista.innerHTML = html;

        // Inicializa SortableJS
        if (window.Sortable && !containerLista.dataset.sortableAtivo) {
            containerLista.dataset.sortableAtivo = 'true';
            _sortableInstancia = new Sortable(containerLista, {
                handle: '.drag-handle',
                animation: 180,
                ghostClass: 'roteiro-sortable-ghost',
                chosenClass: 'roteiro-sortable-chosen',
                onEnd: function (evt) {
                    const oldIdx = evt.oldIndex;
                    const newIdx = evt.newIndex;
                    if (oldIdx === newIdx) return;

                    // Reordena o array interno preservando estritamente a escolha do motorista
                    const movido = _itensEdicao.splice(oldIdx, 1)[0];
                    _itensEdicao.splice(newIdx, 0, movido);

                    recalcularEstadosRota(_itensEdicao);
                    renderizarListaModal();
                    desenharMapaRoteirizacao();
                    atualizarPainelEstimativas();
                }
            });
        }
    }

    // =====================================================
    // 8. CONTROLE DO MODAL DE ROTEIRIZAÇÃO
    // =====================================================

    async function abrirModalRoteirizacao() {
        const manifestoId = obterManifestoIdAtual();
        if (!manifestoId) {
            alert('Nenhum manifesto ativo encontrado.');
            return;
        }

        const modalEl = document.getElementById('modalRoteirizacao');
        if (!modalEl) {
            console.error('[Roteirizacao] Modal #modalRoteirizacao não encontrado.');
            return;
        }

        _itensEdicao = extrairNotasDoManifesto();

        await atualizarLocalizacaoMotorista();

        const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
        modalInstance.show();

        renderizarListaModal();
        atualizarPainelEstimativas();

        // Invalida tamanho do Leaflet para renderização limpa no mobile
        setTimeout(() => {
            inicializarMapa('mapaRoteirizacao');
            if (_mapaInstancia) {
                _mapaInstancia.invalidateSize();
                desenharMapaRoteirizacao();
            }
        }, 300);
    }

    function fecharModalRoteirizacao() {
        const modalEl = document.getElementById('modalRoteirizacao');
        if (modalEl) {
            const modalInstance = bootstrap.Modal.getInstance(modalEl);
            if (modalInstance) modalInstance.hide();
        }
    }

    function toggleSelecaoItem(index, isChecked) {
        if (_itensEdicao[index]) {
            _itensEdicao[index].selecionada = isChecked;
            recalcularEstadosRota(_itensEdicao);
            renderizarListaModal();
            desenharMapaRoteirizacao();
            atualizarPainelEstimativas();
        }
    }

    // =====================================================
    // 9. GERAR ROTA (PERSISTÊNCIA E SELEÇÃO DE NAVEGADOR)
    // =====================================================

    function solicitarGerarRota() {
        const selecionadas = _itensEdicao.filter(it => it.selecionada);
        if (selecionadas.length === 0) {
            alert('Por favor, selecione ao menos uma entrega para roteirizar.');
            return;
        }

        const semDestino = selecionadas.filter(it => !coordValida(it.latitude, it.longitude) && (!it.endereco || it.endereco.includes('NÃO INFORMADO')));
        if (semDestino.length > 0) {
            alert(`Atenção: A nota #${semDestino[0].numero} não possui endereço nem coordenadas válidas.`);
            return;
        }

        const manifestoId = obterManifestoIdAtual();
        recalcularEstadosRota(_itensEdicao);

        const rotaParaSalvar = {
            manifestoId: manifestoId,
            atualizadoEm: new Date().toISOString(),
            segmentoGoogleAtual: 0,
            paradas: _itensEdicao.map((item, idx) => ({
                id: item.id,
                numero: item.numero,
                chave: item.chave,
                destinatario: item.destinatario,
                endereco: item.endereco,
                cep: item.cep,
                latitude: item.latitude,
                longitude: item.longitude,
                tipo: item.tipo,
                concluida: item.concluida,
                selecionada: item.selecionada,
                estado: item.estado,
                ordem: idx + 1
            }))
        };

        salvarRota(manifestoId, rotaParaSalvar);

        // Atualiza banner na tela principal
        renderizarBannerRotaPrincipal(manifestoId);

        // Abre diálogo de navegador
        abrirModalEscolhaNavegador();
    }

    function abrirModalEscolhaNavegador() {
        const modalEl = document.getElementById('modalEscolhaNavegador');
        if (!modalEl) return;

        const containerOpcoes = document.getElementById('opcoes-navegadores-container');
        if (containerOpcoes) {
            const manifestoId = obterManifestoIdAtual();
            const rota = obterRotaSalva(manifestoId);
            const paradasPendentes = (rota && Array.isArray(rota.paradas)) ? rota.paradas.filter(p => p.selecionada && !p.concluida) : [];
            const paradaAtual = (rota && Array.isArray(rota.paradas)) ? rota.paradas.find(p => p.estado === 'ATUAL' && p.selecionada) : null;

            let wazeHtml = '';
            if (paradaAtual) {
                wazeHtml = `
                    <button type="button" class="btn btn-outline-info py-3 rounded-4 fw-bold d-flex align-items-center justify-content-start gap-3 shadow-xs border-2 text-dark text-start" onclick="Roteirizacao.abrirWaze()">
                        <i class="bi bi-cursor-fill text-info fs-3 ms-2"></i>
                        <div class="text-truncate">
                            <div class="fw-bold fs-6">Waze (Parada Atual)</div>
                            <small class="text-muted d-block text-truncate" style="font-size: 0.72rem;">
                                Parada ${paradaAtual.ordem || 1}: NF #${paradaAtual.numero} - ${paradaAtual.destinatario}
                            </small>
                        </div>
                    </button>
                `;
            } else {
                wazeHtml = `
                    <button type="button" class="btn btn-outline-info py-3 rounded-4 fw-bold d-flex align-items-center justify-content-start gap-3 shadow-xs border-2 text-dark" onclick="Roteirizacao.abrirWaze()">
                        <i class="bi bi-cursor-fill text-info fs-3 ms-2"></i>
                        <div class="text-start">
                            <div class="fw-bold fs-6">Waze</div>
                            <small class="text-muted" style="font-size: 0.72rem;">Navegação parada a parada guiada</small>
                        </div>
                    </button>
                `;
            }

            let googleHtml = '';
            const totalPendentes = paradasPendentes.length;
            if (totalPendentes <= LIMITE_SEGMENTO_GOOGLE) {
                googleHtml = `
                    <button type="button" class="btn btn-outline-primary py-3 rounded-4 fw-bold d-flex align-items-center justify-content-start gap-3 shadow-xs border-2 text-dark text-start" onclick="Roteirizacao.abrirGoogleMaps()">
                        <i class="bi bi-geo-alt-fill text-danger fs-3 ms-2"></i>
                        <div class="text-start">
                            <div class="fw-bold fs-6">Google Maps</div>
                            <small class="text-muted" style="font-size: 0.72rem;">Rota com todas as ${totalPendentes} paradas na ordem escolhida</small>
                        </div>
                    </button>
                `;
            } else {
                const totalSegmentos = Math.ceil(totalPendentes / LIMITE_SEGMENTO_GOOGLE);
                googleHtml = `
                    <div class="p-3 rounded-4 bg-light border shadow-xs text-start">
                        <div class="d-flex align-items-center gap-2 mb-2 text-primary fw-bold small">
                            <i class="bi bi-layers-fill fs-5"></i>
                            <div>
                                <span>Google Maps (${totalPendentes} paradas)</span>
                                <small class="text-muted d-block" style="font-size: 0.68rem; font-weight: normal;">
                                    Dividido em ${totalSegmentos} trechos sem alterar a sequência
                                </small>
                            </div>
                        </div>
                        <div class="d-flex flex-column gap-2 mt-2">
                `;
                for (let s = 0; s < totalSegmentos; s++) {
                    const de = s * LIMITE_SEGMENTO_GOOGLE + 1;
                    const ate = Math.min((s + 1) * LIMITE_SEGMENTO_GOOGLE, totalPendentes);
                    googleHtml += `
                        <button type="button" class="btn btn-outline-primary btn-sm py-2 rounded-3 fw-bold d-flex align-items-center justify-content-between" onclick="Roteirizacao.abrirGoogleMaps(${s})">
                            <span><i class="bi bi-geo-alt text-danger me-1"></i> Trecho ${s + 1} (Paradas ${de} a ${ate})</span>
                            <i class="bi bi-arrow-right-short fs-5"></i>
                        </button>
                    `;
                }
                googleHtml += `
                        </div>
                    </div>
                `;
            }

            containerOpcoes.innerHTML = `
                ${wazeHtml}
                ${googleHtml}
                <button type="button" class="btn btn-light rounded-pill py-2 text-muted fw-semibold mt-2" data-bs-dismiss="modal">
                    Cancelar
                </button>
            `;
        }

        const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
        modalInstance.show();
    }

    // =====================================================
    // 10. GOOGLE MAPS (COM ESTRATÉGIA DE SEGMENTAÇÃO)
    // =====================================================

    /**
     * Constrói a URL do Google Maps respeitando a ordem exata do motorista.
     * Limite: 1 origem + até 9 waypoints + 1 destino = 10 paradas por segmento.
     * Se houver mais de 10 paradas, divide em segmentos sem descartar nenhuma.
     */
    function gerarUrlGoogleMaps(manifestoId, indiceSegmento = null) {
        const rotaSalva = obterRotaSalva(manifestoId || obterManifestoIdAtual());
        if (!rotaSalva || !Array.isArray(rotaSalva.paradas)) return null;

        const paradasPendentes = rotaSalva.paradas.filter(p => p.selecionada && !p.concluida);
        if (paradasPendentes.length === 0) return null;

        const totalPendentes = paradasPendentes.length;
        const totalSegmentos = Math.ceil(totalPendentes / LIMITE_SEGMENTO_GOOGLE);

        let segIdx = indiceSegmento !== null ? indiceSegmento : (rotaSalva.segmentoGoogleAtual || 0);
        if (segIdx >= totalSegmentos) segIdx = 0;

        const inicio = segIdx * LIMITE_SEGMENTO_GOOGLE;
        const fim = Math.min(inicio + LIMITE_SEGMENTO_GOOGLE, totalPendentes);
        const lote = paradasPendentes.slice(inicio, fim);

        const formatarPonto = (p) => {
            // Prioridade absoluta: Latitude e Longitude
            if (coordValida(p.latitude, p.longitude)) {
                return `${p.latitude},${p.longitude}`;
            }
            // Fallback: Endereço sanitizado
            return encodeURIComponent(sanitizarEnderecoParaUrl(p.endereco, p.cep));
        };

        // Origem: Localização do motorista (se disponível)
        let originParam = '';
        if (_posicaoMotorista && coordValida(_posicaoMotorista.lat, _posicaoMotorista.lng)) {
            originParam = `${_posicaoMotorista.lat},${_posicaoMotorista.lng}`;
        }

        let destinationParam = '';
        let waypointsParam = '';

        if (lote.length === 1) {
            destinationParam = formatarPonto(lote[0]);
        } else {
            const ultimo = lote[lote.length - 1];
            destinationParam = formatarPonto(ultimo);

            const intermediarios = lote.slice(0, lote.length - 1);
            waypointsParam = intermediarios.map(p => formatarPonto(p)).join('|');
        }

        let url = `https://www.google.com/maps/dir/?api=1&travelmode=driving`;
        if (originParam) url += `&origin=${originParam}`;
        if (destinationParam) url += `&destination=${destinationParam}`;
        if (waypointsParam) url += `&waypoints=${waypointsParam}`;

        return {
            url: url,
            segmentoIndex: segIdx,
            totalSegmentos: totalSegmentos,
            paradasSegmento: lote,
            totalPendentes: totalPendentes
        };
    }

    function abrirGoogleMaps(indiceSegmento = null) {
        const manifestoId = obterManifestoIdAtual();
        const res = gerarUrlGoogleMaps(manifestoId, indiceSegmento);
        if (!res) {
            alert('Todas as entregas selecionadas desta rota já foram concluídas!');
            return;
        }

        localStorage.setItem(PREF_NAV_KEY, 'google');

        const rotaSalva = obterRotaSalva(manifestoId);
        if (rotaSalva) {
            rotaSalva.segmentoGoogleAtual = res.segmentoIndex;
            salvarRota(manifestoId, rotaSalva);
        }

        console.log(`[Roteirizacao] Google Maps Trecho ${res.segmentoIndex + 1}/${res.totalSegmentos} (${res.paradasSegmento.length} paradas):`, res.url);

        const modalNavEl = document.getElementById('modalEscolhaNavegador');
        if (modalNavEl) {
            const modalNav = bootstrap.Modal.getInstance(modalNavEl);
            if (modalNav) modalNav.hide();
        }
        fecharModalRoteirizacao();

        dispararNavegacaoExterna(res.url);
    }

    // =====================================================
    // 11. WAZE (ENVIANDO SOMENTE A PARADA ATUAL)
    // =====================================================

    /**
     * Constrói a URL do Waze exclusivamente para a parada com estado 'ATUAL'.
     * Mantém o motorista no controle sem digitação manual de endereço.
     */
    function gerarUrlWaze(manifestoId) {
        const rotaSalva = obterRotaSalva(manifestoId || obterManifestoIdAtual());
        if (!rotaSalva || !Array.isArray(rotaSalva.paradas)) return null;

        // Localiza a parada ATUAL
        let paradaAlvo = rotaSalva.paradas.find(p => p.estado === 'ATUAL' && p.selecionada);
        if (!paradaAlvo) {
            paradaAlvo = rotaSalva.paradas.find(p => p.selecionada && !p.concluida);
        }
        if (!paradaAlvo) return null;

        let url = '';
        // Prioridade absoluta: Latitude e Longitude
        if (coordValida(paradaAlvo.latitude, paradaAlvo.longitude)) {
            url = `https://waze.com/ul?ll=${paradaAlvo.latitude},${paradaAlvo.longitude}&navigate=yes`;
        } else {
            // Fallback: Endereço sanitizado
            const endEnc = encodeURIComponent(sanitizarEnderecoParaUrl(paradaAlvo.endereco, paradaAlvo.cep));
            url = `https://waze.com/ul?q=${endEnc}&navigate=yes`;
        }

        return {
            url: url,
            parada: paradaAlvo
        };
    }

    function abrirWaze() {
        const manifestoId = obterManifestoIdAtual();
        const res = gerarUrlWaze(manifestoId);
        if (!res) {
            alert('Todas as entregas desta rota já foram concluídas!');
            return;
        }

        localStorage.setItem(PREF_NAV_KEY, 'waze');

        console.log(`[Roteirizacao] Waze Parada ATUAL #${res.parada.numero} (${res.parada.destinatario}):`, res.url);

        const modalNavEl = document.getElementById('modalEscolhaNavegador');
        if (modalNavEl) {
            const modalNav = bootstrap.Modal.getInstance(modalNavEl);
            if (modalNav) modalNav.hide();
        }
        fecharModalRoteirizacao();

        dispararNavegacaoExterna(res.url);
    }

    function dispararNavegacaoExterna(url) {
        // 1. Suporte Capacitor Nativo Android / iOS
        if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.AppLauncher) {
            try {
                window.Capacitor.Plugins.AppLauncher.openUrl({ url: url }).catch(() => {
                    abrirUrlNavegador(url);
                });
                return;
            } catch (e) {}
        }

        abrirUrlNavegador(url);
    }

    function abrirUrlNavegador(url) {
        // 2. Tenta window.open com target _system (padrão Android/Capacitor/Cordova)
        try {
            const w = window.open(url, '_system');
            if (w) return;
        } catch (e) {}

        // 3. Fallback PWA / Navegador Padrão
        try {
            const a = document.createElement('a');
            a.href = url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        } catch (e) {
            window.location.href = url;
        }
    }

    // =====================================================
    // 12. AVANÇO AUTOMÁTICO DE ROTA APÓS BAIXA
    // =====================================================

    /**
     * Chamado automaticamente quando uma nota é baixada (online ou offline).
     * 1. Marca a nota como CONCLUIDA
     * 2. Promove a próxima nota da sequência para ATUAL
     * 3. Atualiza o banner e botão NAVEGAR PARA PRÓXIMA
     */
    function avancarProximaEntregaAposBaixa(numeroNotaBaixada) {
        const manifestoId = obterManifestoIdAtual();
        if (!manifestoId) return;

        const rota = obterRotaSalva(manifestoId);
        if (!rota || !Array.isArray(rota.paradas)) return;

        let alterado = false;
        rota.paradas.forEach((p) => {
            if (String(p.numero) === String(numeroNotaBaixada) || String(p.id) === String(numeroNotaBaixada)) {
                if (!p.concluida) {
                    p.concluida = true;
                    alterado = true;
                }
            }
        });

        if (alterado) {
            recalcularEstadosRota(rota.paradas);
            salvarRota(manifestoId, rota);

            const novaAtual = rota.paradas.find(p => p.estado === 'ATUAL');
            if (novaAtual) {
                console.log(`✅ [Roteirizacao] Nota #${numeroNotaBaixada} concluída. Nova parada ATUAL: #${novaAtual.numero} (${novaAtual.destinatario}).`);
            } else {
                console.log(`🏁 [Roteirizacao] Todas as paradas da rota foram concluídas.`);
            }

            renderizarBannerRotaPrincipal(manifestoId);
        }
    }

    function navegarParaProxima(manifestoId) {
        const rota = obterRotaSalva(manifestoId);
        if (!rota || !rota.paradas) {
            abrirModalRoteirizacao();
            return;
        }

        const navPref = localStorage.getItem(PREF_NAV_KEY) || 'waze';
        if (navPref === 'google') {
            abrirGoogleMaps();
        } else {
            abrirWaze();
        }
    }

    // =====================================================
    // 13. BANNER DINÂMICO DE ROTA NA TELA PRINCIPAL
    // =====================================================

    function renderizarBannerRotaPrincipal(manifestoId) {
        const container = document.getElementById('container-roteirizacao-principal');
        if (!container) return;

        const rota = obterRotaSalva(manifestoId);
        if (!rota || !Array.isArray(rota.paradas)) {
            container.innerHTML = `
                <div class="mb-3">
                    <button type="button" class="btn btn-outline-primary w-100 fw-bold py-2 rounded-pill shadow-xs d-flex align-items-center justify-content-center gap-2" onclick="Roteirizacao.abrirModal()">
                        <i class="bi bi-compass fs-5 text-primary"></i>
                        <span>ROTEIRIZAR ENTREGAS</span>
                    </button>
                </div>`;
            return;
        }

        // Sincroniza baixas já ocorridas no backend
        const notasGerais = window.notasGerais || [];
        if (notasGerais.length > 0) {
            rota.paradas.forEach(p => {
                const nfRef = notasGerais.find(n => String(n.numero_nota || n.numero_coleta || n.id) === String(p.numero));
                if (nfRef && (nfRef.ja_baixada || ['BAIXADA', 'OCORRENCIA'].includes(nfRef.status))) {
                    p.concluida = true;
                }
            });
            recalcularEstadosRota(rota.paradas);
            salvarRota(manifestoId, rota);
        }

        const paradasSelecionadas = rota.paradas.filter(p => p.selecionada);
        const total = paradasSelecionadas.length;
        const concluidas = paradasSelecionadas.filter(p => p.concluida).length;
        const paradaAtual = paradasSelecionadas.find(p => p.estado === 'ATUAL');

        if (!paradaAtual || concluidas >= total) {
            container.innerHTML = `
                <div class="card bg-success-subtle border border-success-subtle shadow-xs rounded-4 mb-3">
                    <div class="card-body p-3 d-flex align-items-center justify-content-between">
                        <div class="d-flex align-items-center gap-2">
                            <i class="bi bi-check-circle-fill text-success fs-3"></i>
                            <div>
                                <h6 class="fw-bold text-success mb-0">Rota 100% Concluída</h6>
                                <small class="text-muted">${concluidas} de ${total} paradas finalizadas</small>
                            </div>
                        </div>
                        <button class="btn btn-sm btn-outline-success rounded-pill fw-bold" onclick="Roteirizacao.abrirModal()">
                            Ver Rota
                        </button>
                    </div>
                </div>`;
            return;
        }

        const navPref = localStorage.getItem(PREF_NAV_KEY) || 'waze';
        const nomeNav = navPref === 'google' ? 'Google Maps' : 'Waze';
        const iconeNav = navPref === 'google' ? 'bi-geo-alt-fill text-danger' : 'bi-cursor-fill text-info';
        const indiceSeq = paradasSelecionadas.indexOf(paradaAtual) + 1;

        container.innerHTML = `
            <div class="card border-0 shadow-sm rounded-4 mb-3 overflow-hidden" style="background: linear-gradient(135deg, #ffffff 0%, #eff6ff 100%); border-left: 5px solid #2563eb !important;">
                <div class="card-body p-3">
                    <div class="d-flex align-items-center justify-content-between mb-2">
                        <div class="d-flex align-items-center gap-2">
                            <span class="badge bg-warning text-dark fw-bold px-2 py-1 rounded-pill" style="font-size: 0.72rem;">
                                <i class="bi bi-geo-alt-fill me-1"></i>Parada ${indiceSeq} de ${total} (ATUAL)
                            </span>
                            <span class="badge bg-light text-secondary border px-2 py-0" style="font-size: 0.68rem;">
                                ${concluidas} concluídas
                            </span>
                        </div>
                        <button class="btn btn-link text-primary text-decoration-none fw-bold p-0 small" onclick="Roteirizacao.abrirModal()">
                            <i class="bi bi-sliders me-1"></i>Editar Ordem
                        </button>
                    </div>

                    <div class="mb-3">
                        <div class="d-flex align-items-center gap-1 mb-1">
                            <span class="badge bg-secondary-subtle text-dark" style="font-size: 0.7rem;">NF #${paradaAtual.numero}</span>
                            <h6 class="fw-bold text-dark mb-0 text-truncate" style="font-size: 0.95rem;">
                                ${paradaAtual.destinatario}
                            </h6>
                        </div>
                        <p class="small text-muted mb-0 text-truncate" style="font-size: 0.78rem;">
                            <i class="bi bi-geo-alt me-1 text-danger"></i>${paradaAtual.endereco}
                        </p>
                    </div>

                    <div class="d-flex gap-2">
                        <button type="button" class="btn btn-primary btn-sm flex-grow-1 fw-bold py-2 rounded-pill shadow-xs d-flex align-items-center justify-content-center gap-2" 
                                onclick="Roteirizacao.navegarProxima('${manifestoId}')">
                            <i class="bi ${iconeNav}"></i>
                            <span>NAVEGAR PARA PRÓXIMA (${nomeNav})</span>
                        </button>
                        <button type="button" class="btn btn-light btn-sm border rounded-circle d-flex align-items-center justify-content-center" 
                                style="width: 38px; height: 38px; min-width: 38px;" 
                                onclick="Roteirizacao.abrirModalEscolhaNavegador()" 
                                title="Trocar navegador">
                            <i class="bi bi-gear text-secondary"></i>
                        </button>
                    </div>
                </div>
            </div>`;
    }

    // =====================================================
    // 14. EXPORTAÇÃO GLOBAL
    // =====================================================

    window.Roteirizacao = {
        abrirModal: abrirModalRoteirizacao,
        fecharModal: fecharModalRoteirizacao,
        toggleSelecaoItem: toggleSelecaoItem,
        solicitarGerarRota: solicitarGerarRota,
        abrirModalEscolhaNavegador: abrirModalEscolhaNavegador,
        abrirGoogleMaps: abrirGoogleMaps,
        abrirWaze: abrirWaze,
        navegarProxima: navegarParaProxima,
        avancarProximaEntregaAposBaixa: avancarProximaEntregaAposBaixa,
        renderizarBanner: renderizarBannerRotaPrincipal,
        obterRotaSalva: obterRotaSalva,
        removerRotaSalva: removerRotaSalva,
        // Helpers para testes automatizados / auditoria
        recalcularEstados: recalcularEstadosRota,
        haversineKm: haversineKm,
        sanitizarEnderecoParaUrl: sanitizarEnderecoParaUrl,
        gerarUrlGoogleMaps: gerarUrlGoogleMaps,
        gerarUrlWaze: gerarUrlWaze,
        salvarRota: salvarRota
    };

})(window, document);
