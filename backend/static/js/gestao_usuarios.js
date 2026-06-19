// static/js/gestao_usuarios.js
// Gestao de Usuarios - CRUD + Permissoes

const CARGO_LOGADO = document.querySelector('[data-cargo]')?.dataset.cargo || 'MEMBRO';

const PERM_FIELDS = [
    'pode_acessar_dashboard', 'pode_puxar_relatorio',
    'pode_ver_manifestos', 'pode_criar_manifesto', 'pode_excluir_manifesto', 'pode_editar_manifesto',
    'pode_adicionar_notas', 'pode_remover_notas',
    'pode_acessar_sac', 'pode_acessar_tickets',
    'pode_registrar_motorista', 'pode_excluir_motorista',
    'pode_gerenciar_usuarios', 'pode_alterar_permissoes',
    'pode_realizar_baixas', 'pode_ver_historico'
];

function getCSRF() {
    return document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith('csrftoken='))?.split('=')[1] || '';
}

// === CARREGAR USUARIOS ===
async function carregarUsuarios() {
    const filial = document.getElementById('filtro-filial')?.value || '';
    const tipo = document.getElementById('filtro-tipo')?.value || '';
    const cargo = document.getElementById('filtro-cargo')?.value || '';
    
    const params = new URLSearchParams();
    if (filial) params.set('filial_id', filial);
    if (tipo) params.set('tipo', tipo);
    if (cargo) params.set('cargo', cargo);
    
    const tbody = document.getElementById('tabela-usuarios');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Carregando...</td></tr>';
    
    try {
        const resp = await fetch(`/gestao/api/usuarios/?${params.toString()}`);
        const data = await resp.json();
        
        if (!data.usuarios || data.usuarios.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center py-5 text-muted"><i class="bi bi-people fs-1 d-block mb-2"></i>Nenhum usuario encontrado</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.usuarios.map(u => renderUserRow(u)).join('');
    } catch (err) {
        console.error('Erro ao carregar usuarios:', err);
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-danger"><i class="bi bi-exclamation-triangle me-2"></i>Erro ao carregar</td></tr>';
    }
}

function renderUserRow(u) {
    const badgeTipo = u.tipo_usuario === 'SAC' 
        ? '<span class="badge bg-info-subtle text-info">SAC</span>' 
        : '<span class="badge bg-primary-subtle text-primary">Operacional</span>';
    
    let badgeCargo = '';
    if (u.cargo === 'GESTOR') badgeCargo = '<span class="badge bg-danger-subtle text-danger">Gestor</span>';
    else if (u.cargo === 'GERENTE') badgeCargo = '<span class="badge bg-warning-subtle text-warning">Gerente</span>';
    else badgeCargo = '<span class="badge bg-secondary-subtle text-secondary">Membro</span>';
    
    const statusBadge = u.tem_user 
        ? '<span class="badge bg-success-subtle text-success"><i class="bi bi-check-circle me-1"></i>Ativo</span>'
        : '<span class="badge bg-secondary-subtle text-secondary"><i class="bi bi-clock me-1"></i>Pendente</span>';
    
    const iniciais = u.nome.split(' ').map(n => n[0]).slice(0, 2).join('').toUpperCase();
    
    let tokenHTML = '';
    if (CARGO_LOGADO === 'GESTOR' || CARGO_LOGADO === 'ADMINISTRADOR') {
        if (u.token) {
            tokenHTML = `
            <div class="d-flex align-items-center gap-2 mt-1" style="font-size: 0.75rem;">
                <span class="text-muted fw-bold">Token:</span>
                <span class="font-monospace text-secondary" id="token-text-${u.id}" style="letter-spacing: 2px;">••••••••••••••••</span>
                <button class="btn btn-sm btn-link p-0 text-muted" onclick="toggleTokenVisibility(event, ${u.id}, '${u.token}')" title="Mostrar/Ocultar Token" style="text-decoration: none;">
                    <i class="bi bi-eye" id="token-eye-${u.id}"></i>
                </button>
                <button class="btn btn-sm btn-link p-0 text-muted" onclick="copyToken(event, '${u.token}')" title="Copiar Token" style="text-decoration: none;">
                    <i class="bi bi-clipboard"></i>
                </button>
            </div>`;
        } else {
            tokenHTML = `
            <div class="d-flex align-items-center gap-2 mt-1" style="font-size: 0.75rem;">
                <span class="text-muted fw-bold">Token:</span>
                <span class="text-muted font-monospace">Sem token gerado</span>
            </div>`;
        }
    }
    
    return `
    <tr data-id="${u.id}">
        <td class="px-4 py-3">
            <div class="d-flex align-items-center gap-3">
                <div class="rounded-circle bg-primary bg-opacity-10 text-primary fw-bold d-flex align-items-center justify-content-center" 
                     style="width: 40px; height: 40px; font-size: 0.85rem;">${iniciais}</div>
                <div>
                    <div class="fw-semibold mb-1">${u.nome}</div>
                    <div class="small text-muted mb-1" title="E-mail"><i class="bi bi-envelope"></i> ${u.email || 'Não informado'}</div>
                    ${tokenHTML}
                </div>
            </div>
        </td>
        <td class="py-3">
            <div class="small fw-bold ${u.ultimo_acesso ? 'text-success' : 'text-danger'}" title="Último Acesso">
                <i class="bi bi-box-arrow-in-right"></i> ${u.ultimo_acesso || 'Nunca acessou'}
            </div>
        </td>
        <td class="py-3"><code>${formatCPF(u.cpf)}</code></td>
        <td class="py-3">${badgeTipo}</td>
        <td class="py-3">${badgeCargo}</td>
        <td class="py-3"><span class="text-muted small">${u.filial_nome}</span></td>
        <td class="py-3">${statusBadge}</td>
        <td class="py-3 text-end pe-4">
            <div class="btn-group btn-group-sm gap-1">
                <button class="btn btn-outline-primary rounded-pill px-3" title="Editar" onclick='abrirModalEditar(${JSON.stringify(u)})'>
                    <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-outline-success rounded-pill px-3" title="Permissoes" onclick='abrirModalPermissoes(${JSON.stringify(u)})'>
                    <i class="bi bi-shield-check"></i>
                </button>
                <button class="btn btn-outline-secondary rounded-pill px-3" title="Enviar Redefinição de Senha" onclick="enviarRedefinicaoSenha(${u.id})">
                    <i class="bi bi-envelope"></i>
                </button>
                <button class="btn btn-outline-danger rounded-pill px-3" title="Excluir" onclick="abrirModalExcluir(${u.id}, '${u.nome}')">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        </td>
    </tr>`;
}

function formatCPF(cpf) {
    if (!cpf || cpf.length !== 11) return cpf;
    return cpf.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4');
}

// === CRIAR USUARIO ===
function abrirModalCriar() {
    document.getElementById('modalUsuarioTitulo').textContent = 'Novo Usuario';
    document.getElementById('edit-usuario-id').value = '';
    document.getElementById('edit-usuario-id').value = '';
    document.getElementById('campo-nome').value = '';
    document.getElementById('campo-email').value = '';
    document.getElementById('campo-cpf').value = '';
    document.getElementById('campo-cpf').disabled = false;
    document.getElementById('campo-tipo').value = 'OPERACIONAL';
    document.getElementById('campo-cargo').value = 'MEMBRO';
    document.getElementById('campo-is-sac-mobile').checked = false;
    new bootstrap.Modal(document.getElementById('modalUsuario')).show();
}

// === EDITAR USUARIO ===
function abrirModalEditar(u) {
    document.getElementById('modalUsuarioTitulo').textContent = 'Editar Usuario';
    document.getElementById('edit-usuario-id').value = u.id;
    document.getElementById('edit-usuario-id').value = u.id;
    document.getElementById('campo-nome').value = u.nome;
    document.getElementById('campo-email').value = u.email || '';
    document.getElementById('campo-cpf').value = u.cpf;
    document.getElementById('campo-cpf').disabled = true;
    document.getElementById('campo-tipo').value = u.tipo_usuario;
    document.getElementById('campo-cargo').value = u.cargo;
    document.getElementById('campo-is-sac-mobile').checked = u.is_sac_mobile === true;
    const filialEl = document.getElementById('campo-filial');
    if (filialEl) filialEl.value = u.filial_id || '';
    new bootstrap.Modal(document.getElementById('modalUsuario')).show();
}

// === SALVAR (CRIAR OU EDITAR) ===
async function salvarUsuario() {
    const id = document.getElementById('edit-usuario-id').value;
    const nome = document.getElementById('campo-nome').value.trim();
    const email = document.getElementById('campo-email').value.trim();
    const cpf = document.getElementById('campo-cpf').value.replace(/\D/g, '');
    const tipo = document.getElementById('campo-tipo').value;
    const cargo = document.getElementById('campo-cargo').value;
    const filialEl = document.getElementById('campo-filial');
    const filial = filialEl ? filialEl.value : '';
    const is_sac_mobile = document.getElementById('campo-is-sac-mobile').checked;
    
    if (!nome) return Swal.fire('Erro', 'Informe o nome', 'error');
    if (!email && !id) return Swal.fire('Erro', 'Informe o E-mail', 'error');
    
    const body = { nome, email, cpf, tipo_usuario: tipo, cargo: cargo, is_sac_mobile: is_sac_mobile };
    if (filial) body.filial_id = parseInt(filial);
    
    let url, method;
    if (id) {
        url = `/gestao/api/usuarios/${id}/editar/`;
        method = 'PATCH';
    } else {
        if (!cpf || cpf.length !== 11) return Swal.fire('Erro', 'CPF deve ter 11 digitos', 'error');
        url = '/gestao/api/usuarios/criar/';
        method = 'POST';
    }
    
    try {
        const resp = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
            body: JSON.stringify(body)
        });
        const data = await resp.json();
        
        if (resp.ok) {
            bootstrap.Modal.getInstance(document.getElementById('modalUsuario'))?.hide();
            Swal.fire({ icon: 'success', title: 'Sucesso!', text: data.mensagem, timer: 2000, showConfirmButton: false });
            carregarUsuarios();
        } else {
            Swal.fire('Erro', data.erro || 'Erro ao salvar', 'error');
        }
    } catch (err) {
        console.error(err);
        Swal.fire('Erro', 'Falha na conexao', 'error');
    }
}

// === PERMISSOES ===
function abrirModalPermissoes(u) {
    document.getElementById('perm-usuario-id').value = u.id;
    document.getElementById('perm-nome-usuario').textContent = u.nome;
    
    // Preenche os toggles com as permissoes atuais
    PERM_FIELDS.forEach(campo => {
        const el = document.getElementById(`perm-${campo}`);
        if (el) {
            el.checked = u.permissoes?.[campo] ?? false;
        }
    });
    
    new bootstrap.Modal(document.getElementById('modalPermissoes')).show();
}

async function salvarPermissoes() {
    const id = document.getElementById('perm-usuario-id').value;
    const body = {};
    
    PERM_FIELDS.forEach(campo => {
        const el = document.getElementById(`perm-${campo}`);
        if (el) body[campo] = el.checked;
    });
    
    try {
        const resp = await fetch(`/gestao/api/usuarios/${id}/permissoes/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
            body: JSON.stringify(body)
        });
        const data = await resp.json();
        
        if (resp.ok) {
            bootstrap.Modal.getInstance(document.getElementById('modalPermissoes'))?.hide();
            Swal.fire({ icon: 'success', title: 'Permissoes salvas!', text: data.mensagem, timer: 2000, showConfirmButton: false });
            carregarUsuarios();
        } else {
            Swal.fire('Erro', data.erro || 'Erro ao salvar permissoes', 'error');
        }
    } catch (err) {
        console.error(err);
        Swal.fire('Erro', 'Falha na conexao', 'error');
    }
}

// === EXCLUIR ===
function abrirModalExcluir(id, nome) {
    document.getElementById('excluir-usuario-id').value = id;
    document.getElementById('excluir-texto').textContent = `Tem certeza que deseja excluir "${nome}"? Esta acao nao pode ser desfeita.`;
    new bootstrap.Modal(document.getElementById('modalExcluir')).show();
}

async function confirmarExclusao() {
    const id = document.getElementById('excluir-usuario-id').value;
    
    try {
        const resp = await fetch(`/gestao/api/usuarios/${id}/deletar/`, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': getCSRF() }
        });
        const data = await resp.json();
        
        if (resp.ok) {
            bootstrap.Modal.getInstance(document.getElementById('modalExcluir'))?.hide();
            Swal.fire({ icon: 'success', title: 'Excluido!', text: data.mensagem, timer: 2000, showConfirmButton: false });
            carregarUsuarios();
        } else {
            Swal.fire('Erro', data.erro || 'Erro ao excluir', 'error');
        }
    } catch (err) {
        console.error(err);
        Swal.fire('Erro', 'Falha na conexao', 'error');
    }
}

// === ENVIAR REDEFINICAO DE SENHA ===
async function enviarRedefinicaoSenha(id) {
    if(!confirm("Deseja enviar um link de redefinição de senha para o e-mail cadastrado deste usuário?")) return;
    
    try {
        const response = await fetch(`/usuarios/reset-senha/${id}/`, {
            method: 'POST',
            headers: { 
                'X-CSRFToken': getCSRF(),
                'Content-Type': 'application/json'
            }
        });
        const data = await response.json();
        if (data.success) {
            Swal.fire({ icon: 'success', title: 'Sucesso!', text: 'E-mail de redefinição enviado com sucesso!', timer: 2000, showConfirmButton: false });
        } else {
            Swal.fire('Erro', data.message || 'Erro ao enviar e-mail', 'error');
        }
    } catch (e) {
        console.error(e);
        Swal.fire('Erro', 'Falha na conexao ao servidor', 'error');
    }
}

// === INICIALIZACAO ===
document.addEventListener('DOMContentLoaded', () => {
    carregarUsuarios();
});

// === VISIBILIDADE DO TOKEN ===
function toggleTokenVisibility(event, userId, tokenValue) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const tokenSpan = document.getElementById(`token-text-${userId}`);
    const eyeIcon = document.getElementById(`token-eye-${userId}`);
    if (!tokenSpan || !eyeIcon) return;

    if (tokenSpan.textContent.includes('•')) {
        tokenSpan.textContent = tokenValue;
        tokenSpan.style.letterSpacing = 'normal';
        eyeIcon.className = 'bi bi-eye-slash';
    } else {
        tokenSpan.textContent = '••••••••••••••••';
        tokenSpan.style.letterSpacing = '2px';
        eyeIcon.className = 'bi bi-eye';
    }
}

// === COPIAR TOKEN ===
function copyToken(event, tokenValue) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    if (!navigator.clipboard) {
        // Fallback para navegadores antigos ou sem HTTPS local
        const el = document.createElement('textarea');
        el.value = tokenValue;
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        Swal.fire({
            icon: 'success',
            title: 'Copiado!',
            text: 'Token copiado para a área de transferência',
            timer: 1500,
            showConfirmButton: false
        });
        return;
    }
    navigator.clipboard.writeText(tokenValue).then(() => {
        Swal.fire({
            icon: 'success',
            title: 'Copiado!',
            text: 'Token copiado para a área de transferência',
            timer: 1500,
            showConfirmButton: false
        });
    }).catch(err => {
        console.error('Falha ao copiar token:', err);
    });
}
