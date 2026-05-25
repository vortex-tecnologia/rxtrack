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
    
    return `
    <tr data-id="${u.id}">
        <td class="px-4 py-3">
            <div class="d-flex align-items-center gap-3">
                <div class="rounded-circle bg-primary bg-opacity-10 text-primary fw-bold d-flex align-items-center justify-content-center" 
                     style="width: 40px; height: 40px; font-size: 0.85rem;">${iniciais}</div>
                <div>
                    <div class="fw-semibold">${u.nome}</div>
                </div>
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
    document.getElementById('campo-nome').value = '';
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
    document.getElementById('campo-nome').value = u.nome;
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
    const cpf = document.getElementById('campo-cpf').value.replace(/\D/g, '');
    const tipo = document.getElementById('campo-tipo').value;
    const cargo = document.getElementById('campo-cargo').value;
    const filialEl = document.getElementById('campo-filial');
    const filial = filialEl ? filialEl.value : '';
    const is_sac_mobile = document.getElementById('campo-is-sac-mobile').checked;
    
    if (!nome) return Swal.fire('Erro', 'Informe o nome', 'error');
    
    const body = { nome, cpf, tipo_usuario: tipo, cargo: cargo, is_sac_mobile: is_sac_mobile };
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

// === INICIALIZACAO ===
document.addEventListener('DOMContentLoaded', () => {
    carregarUsuarios();
});
