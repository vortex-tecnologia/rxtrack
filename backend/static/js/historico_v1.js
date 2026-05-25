async function abrirHistorico() {
    const modalEl = document.getElementById('modalHistorico');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
    
    const container = document.getElementById('historico-content');
    container.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary"></div></div>';

    try {
        // Usa o authFetch para garantir o envio do Token JWT
        const response = await authFetch(`${API_BASE}manifesto/historico/`);
        
        if (!response.ok) {
            const erro = await response.json();
            throw new Error(erro.error || "Falha ao carregar histórico");
        }

        const manifestos = await response.json();

        if (!manifestos || manifestos.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-folder-x display-1 text-muted"></i>
                    <p class="mt-3">Nenhum manifesto finalizado encontrado.</p>
                </div>`;
            return;
        }

        let accordionHTML = `<div class="accordion accordion-flush" id="accordionManifestos">`;

        manifestos.forEach((m, index) => {
            accordionHTML += `
                <div class="accordion-item border shadow-sm mb-3" style="border-radius: 12px; overflow: hidden;">
                    <h2 class="accordion-header">
                        <button class="accordion-button collapsed p-3" type="button" data-bs-toggle="collapse" data-bs-target="#m-${index}">
                            <div class="w-100">
                                <div class="d-flex justify-content-between align-items-center me-3">
                                    <span class="fw-bold text-primary">Manifesto #${m.numero}</span>
                                    <span class="badge bg-success">Finalizado</span>
                                </div>
                                <div class="small text-muted mt-1">
                                    <i class="bi bi-box-seam"></i> ${m.qtd_nfe} NF-es | <i class="bi bi-calendar3"></i> ${m.data}
                                </div>
                            </div>
                        </button>
                    </h2>
                    <div id="m-${index}" class="accordion-collapse collapse" data-bs-parent="#accordionManifestos">
                        <div class="accordion-body bg-light">
                            <div class="list-group list-group-flush shadow-sm rounded">
                                ${m.notas.map((nf) => `
                                    <div class="list-group-item">
                                        <div class="d-flex justify-content-between align-items-center">
                                            <span class="fw-bold small">NF ${nf.numero_nf}</span>
                                            <span class="badge rounded-pill bg-info text-dark" style="font-size: 0.65rem;">
                                                ${nf.tipo_ocorrencia || 'Entregue'}
                                            </span>
                                        </div>
                                        
                                        <div class="mt-2 p-2 bg-white rounded border" style="font-size: 0.8rem;">
                                            <div class="text-muted"><i class="bi bi-person me-1"></i>Recebedor: ${nf.recebedor || 'Não informado'}</div>
                                            <div class="text-muted small mb-2"><i class="bi bi-chat-left-text me-1"></i>${nf.descricao_detalhada}</div>
                                            
                                            ${nf.foto_comprovante ? `
                                                <button class="btn btn-sm btn-outline-primary mt-1 w-100" onclick="verFotoCanhoto('${nf.foto_comprovante}')">
                                                    <i class="bi bi-camera me-1"></i> Ver Comprovante
                                                </button>
                                            ` : '<div class="text-danger mt-1 small"><i class="bi bi-x-circle me-1"></i>Sem foto cadastrada</div>'}
                                        </div>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                </div>`;
        });

        accordionHTML += `</div>`;
        container.innerHTML = accordionHTML;

    } catch (err) {
        container.innerHTML = `<div class="alert alert-danger">Erro: ${err.message}</div>`;
        console.error(err);
    }

}

function verFotoCanhoto(url) {
    if (!url) {
        alert("Comprovante não disponível.");
        return;
    }

    const modalHTML = `
        <div class="modal fade" id="modalFotoCanhoto" tabindex="-1">
            <div class="modal-dialog modal-dialog-centered modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Comprovante de Entrega</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body text-center">
                        <img src="${url}" class="img-fluid rounded shadow" alt="Comprovante">
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove modal anterior se existir
    const modalExistente = document.getElementById('modalFotoCanhoto');
    if (modalExistente) {
        modalExistente.remove();
    }

    // Adiciona no body
    document.body.insertAdjacentHTML('beforeend', modalHTML);

    // Abre modal
    const modal = new bootstrap.Modal(
        document.getElementById('modalFotoCanhoto')
    );
    modal.show();
}
