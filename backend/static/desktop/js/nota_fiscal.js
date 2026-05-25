// Controle Global do Modal de Importação
let dadosTemporariosNfe = null;

/**
 * Gerencia a visibilidade das etapas dentro do modal
 * @param {string} stepName - 'busca', 'loading', 'resultado', 'sucesso'
 */
function displayModalError(msg) {
    const box = document.getElementById('modal-feedback');
    const text = document.getElementById('feedback-text');
    if (box && text) {
        text.innerText = msg;
        box.style.display = 'block';
        // Remove automaticamente após 5 segundos
        setTimeout(() => { box.style.display = 'none'; }, 5000);
    }
}
function showStep(stepName) {
    // Esconde feedback de erro ao mudar de tela
    const feedback = document.getElementById('modal-feedback');
    if (feedback) feedback.style.display = 'none';

    const steps = ['busca', 'loading', 'resultado', 'sucesso'];
    steps.forEach(s => {
        const el = document.getElementById(`step-${s}`);
        if (el) el.style.display = 'none';
    });
    
    const target = document.getElementById(`step-${stepName}`);
    if (target) {
        target.style.display = 'block';
        target.classList.add('animate__animated', 'animate__fadeIn');
    }
}

/**
 * Primeira Etapa: Busca no Backend (Local -> TMS)
 */
function processarBuscaNfe() {
    const inputNum = document.getElementById('importNumero');
    const inputCnpj = document.getElementById('importCnpj');
    
    // Sanitização e validação
    const numero = inputNum ? inputNum.value.replace(/\D/g, '') : '';
    const cnpj = inputCnpj ? inputCnpj.value.replace(/\D/g, '') : '';

    if (!numero || !cnpj) {
        if (!numero) inputNum.classList.add('is-invalid');
        if (!cnpj) inputCnpj.classList.add('is-invalid');
        displayModalError("Preencha o número da NF-e e o CNPJ do Emissor.");
        return;
    }

    // Limpa estados de erro anteriores
    inputNum.classList.remove('is-invalid');
    inputCnpj.classList.remove('is-invalid');

    showStep('loading');
    document.getElementById('loading-text').innerText = "Consultando TMS ESL...";

    // Correção do erro de "value" do CSRF Token
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');
    if (!csrfToken) {
        showStep('busca');
        displayModalError("Erro de segurança: Token CSRF não encontrado.");
        return;
    }

    fetch('/api/manifesto/buscar-importar/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken.value
        },
        body: JSON.stringify({ numero: numero, cnpj_emissor: cnpj })
    })
    .then(r => {
        if (r.status === 404) throw new Error("Nota não encontrada no TMS.");
        if (!r.ok) throw new Error("Erro na comunicação com o servidor.");
        return r.json();
    })
    .then(data => {
        if (data.sucesso) {
            dadosTemporariosNfe = data.dados;
            document.getElementById('resNfe').innerText = data.dados.numero;
            document.getElementById('resDest').innerText = data.dados.destinatario;
            document.getElementById('resEnd').innerText = data.dados.endereco;
            document.getElementById('resChave').innerText = data.dados.chave;

            setTimeout(() => { 
                showStep('resultado');
                if (typeof carregarManifestosNoSelect === "function") carregarManifestosNoSelect();
            }, 800);
        } else {
            throw new Error(data.mensagem || "Dados da nota inválidos.");
        }
    })
    .catch(err => {
        showStep('busca');
        displayModalError(err.message);
    });
}

/**
 * Segunda Etapa: Salvar o vínculo no banco
 */
function processarInclusaoFinal() {
    const select = document.getElementById('selectManifesto');
    const manifestoId = select ? select.value : '';

    if (!manifestoId) {
        displayModalError("Selecione um manifesto para vincular esta nota.");
        return;
    }

    showStep('loading');
    document.getElementById('loading-text').innerText = "Salvando no banco...";

    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');

    fetch('/api/manifesto/buscar-importar/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken.value
        },
        body: JSON.stringify({ ...dadosTemporariosNfe, manifesto_id: manifestoId })
    })
    .then(r => r.json())
    .then(data => {
        if (data.sucesso) {
            showStep('sucesso');
            setTimeout(() => { location.reload(); }, 1500);
        } else {
            throw new Error(data.mensagem || "Erro ao salvar vínculo.");
        }
    })
    .catch(err => {
        showStep('resultado');
        displayModalError(err.message);
    });
}


function voltarParaBusca() {
    showStep('busca');
}

function carregarManifestosNoSelect() {
    const select = document.getElementById('selectManifesto');
    const filtro = document.getElementById('filtroManifesto');
    if (!select) return;

    // Reseta o filtro ao abrir
    if (filtro) filtro.value = '';

    fetch('/api/manifesto/listar-para-select/')
        .then(r => r.json())
        .then(data => {
            if (data.sucesso) {
                // Armazenamos a lista completa para o filtro funcionar localmente
                window.listaManifestosCache = data.manifestos;
                renderizarOpcoesManifesto(data.manifestos);
            } else {
                displayModalError("Erro ao carregar manifestos.");
            }
        })
        .catch(() => displayModalError("Falha ao buscar manifestos."));
}

/**
 * Renderiza as opções no select com base em um array
 */
function renderizarOpcoesManifesto(lista) {
    const select = document.getElementById('selectManifesto');
    let options = '';
    
    if (lista.length === 0) {
        options = '<option value="" disabled>Nenhum manifesto encontrado</option>';
    } else {
        lista.forEach(m => {
            options += `<option value="${m.id}">#${m.numero} - ${m.motorista}</option>`;
        });
    }
    select.innerHTML = options;
}

/**
 * Filtra as opções do select conforme o usuário digita
 */
function filtrarManifestos() {
    const termo = document.getElementById('filtroManifesto').value.toLowerCase();
    
    // Filtra no cache local para ser instantâneo
    const filtrados = window.listaManifestosCache.filter(m => {
        return m.numero.toString().includes(termo) || 
               m.motorista.toLowerCase().includes(termo);
    });

    renderizarOpcoesManifesto(filtrados);
}