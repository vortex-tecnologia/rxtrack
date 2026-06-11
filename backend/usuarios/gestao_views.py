# usuarios/gestao_views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_http_methods
from django.db import transaction
from .models import Motorista, Filial, PermissaoUsuario
import json

CARGO_NIVEL = {'MEMBRO': 1, 'GERENTE': 2, 'GESTOR': 3}


def get_perfil_logado(request):
    """Retorna o perfil do usuario logado ou None."""
    if hasattr(request.user, 'motorista_perfil'):
        return request.user.motorista_perfil
    return None


def pode_gerenciar(perfil):
    """Verifica se o perfil tem permissao para gerenciar usuarios."""
    if not perfil:
        return False
    return perfil.cargo in ['GESTOR', 'GERENTE']


@login_required
def gestao_usuarios_page(request):
    """Renderiza a pagina de gestao de usuarios."""
    perfil = get_perfil_logado(request)
    if not perfil or not pode_gerenciar(perfil):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Acesso negado")
    
    filiais = Filial.objects.all()
    return render(request, 'desktop/gestao_usuarios.html', {
        'filiais': filiais,
        'perfil_logado': perfil,
    })


@login_required
def api_listar_usuarios(request):
    """Lista usuarios filtrados por filial, tipo e cargo."""
    perfil = get_perfil_logado(request)
    if not perfil or not pode_gerenciar(perfil):
        return JsonResponse({'erro': 'Sem permissao'}, status=403)
    
    filial_id = request.GET.get('filial_id')
    tipo = request.GET.get('tipo')
    cargo = request.GET.get('cargo')
    
    qs = Motorista.objects.exclude(tipo_usuario='MOTORISTA').select_related('filial', 'user')
    
    # Gerente so ve sua filial
    if perfil.cargo == 'GERENTE':
        qs = qs.filter(filial=perfil.filial)
    elif filial_id:
        qs = qs.filter(filial_id=filial_id)
    
    if tipo:
        qs = qs.filter(tipo_usuario=tipo)
    if cargo:
        qs = qs.filter(cargo=cargo)
    
    usuarios = []
    for m in qs.order_by('nome_completo'):
        # Busca permissoes
        perms = {}
        if hasattr(m, 'permissoes'):
            p = m.permissoes
            perms = {
                'pode_acessar_dashboard': p.pode_acessar_dashboard,
                'pode_puxar_relatorio': p.pode_puxar_relatorio,
                'pode_ver_manifestos': p.pode_ver_manifestos,
                'pode_criar_manifesto': p.pode_criar_manifesto,
                'pode_excluir_manifesto': p.pode_excluir_manifesto,
                'pode_editar_manifesto': p.pode_editar_manifesto,
                'pode_adicionar_notas': p.pode_adicionar_notas,
                'pode_remover_notas': p.pode_remover_notas,
                'pode_acessar_sac': p.pode_acessar_sac,
                'pode_acessar_tickets': p.pode_acessar_tickets,
                'pode_registrar_motorista': p.pode_registrar_motorista,
                'pode_excluir_motorista': p.pode_excluir_motorista,
                'pode_gerenciar_usuarios': p.pode_gerenciar_usuarios,
                'pode_alterar_permissoes': p.pode_alterar_permissoes,
                'pode_realizar_baixas': p.pode_realizar_baixas,
                'pode_ver_historico': p.pode_ver_historico,
            }
        
        usuarios.append({
            'id': m.id,
            'nome': m.nome_completo,
            'cpf': m.cpf,
            'email': m.email if m.email else None,
            'ultimo_acesso': m.user.last_login.strftime('%d/%m/%Y %H:%M') if m.user and m.user.last_login else None,
            'tipo_usuario': m.tipo_usuario,
            'cargo': m.cargo,
            'filial_id': m.filial_id,
            'filial_nome': m.filial.nome if m.filial else 'Sem filial',
            'tem_user': m.user is not None,
            'is_sac_mobile': getattr(m, 'is_sac_mobile', False),
            'permissoes': perms,
        })
    
    return JsonResponse({'usuarios': usuarios})


@login_required
@require_POST
def api_criar_usuario(request):
    """Cria um novo usuario (pre-cadastro + perfil)."""
    perfil = get_perfil_logado(request)
    if not perfil or not pode_gerenciar(perfil):
        return JsonResponse({'erro': 'Sem permissao'}, status=403)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'erro': 'JSON invalido'}, status=400)
    
    nome = data.get('nome', '').strip()
    cpf = data.get('cpf', '').replace('.', '').replace('-', '').strip()
    email = data.get('email', '').strip()
    tipo_usuario = data.get('tipo_usuario', 'OPERACIONAL')
    cargo_novo = data.get('cargo', 'MEMBRO')
    filial_id = data.get('filial_id', perfil.filial_id)
    is_sac_mobile = data.get('is_sac_mobile', False)
    
    if not nome or not cpf or len(cpf) != 11 or not email:
        return JsonResponse({'erro': 'Nome, CPF (11 digitos) e E-mail sao obrigatorios'}, status=400)
    
    # Validacao de hierarquia
    nivel_logado = CARGO_NIVEL.get(perfil.cargo, 0)
    nivel_novo = CARGO_NIVEL.get(cargo_novo, 0)
    
    if nivel_novo >= nivel_logado:
        return JsonResponse({'erro': f'Voce nao pode criar usuario com cargo {cargo_novo}'}, status=403)
    
    # Gerente so cria MEMBRO
    if perfil.cargo == 'GERENTE' and cargo_novo != 'MEMBRO':
        return JsonResponse({'erro': 'Gerente so pode criar Membros'}, status=403)
    
    # Verifica CPF duplicado
    if Motorista.objects.filter(cpf=cpf).exists():
        return JsonResponse({'erro': 'CPF ja cadastrado no sistema'}, status=400)
    
    try:
        with transaction.atomic():
            motorista = Motorista.objects.create(
                cpf=cpf,
                nome_completo=nome,
                email=email,
                tipo_usuario=tipo_usuario,
                cargo=cargo_novo,
                filial_id=filial_id or perfil.filial_id,
                is_sac_mobile=is_sac_mobile,
            )
            # Permissoes sao criadas automaticamente pelo signal
            
        # Send Welcome Email
        try:
            from django.core.mail import send_mail
            from django.template.loader import render_to_string
            from django.utils.html import strip_tags
            from django.conf import settings
            
            dominio = f"{request.scheme}://{request.get_host()}"
            context = {'nome': nome, 'cpf': cpf, 'dominio': dominio}
            html_message = render_to_string('emails/boas_vindas.html', context)
            plain_message = strip_tags(html_message)
            
            send_mail(
                'Bem-vindo ao QuickTrack',
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                html_message=html_message,
                fail_silently=True
            )
        except Exception as e:
            print(f"Erro ao enviar email: {e}")
        
        return JsonResponse({'status': 'ok', 'id': motorista.id, 'mensagem': f'{nome} criado com sucesso!'})
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


@login_required
@require_http_methods(["PATCH"])
def api_editar_usuario(request, usuario_id):
    """Edita tipo, cargo, filial de um usuario."""
    perfil = get_perfil_logado(request)
    if not perfil or not pode_gerenciar(perfil):
        return JsonResponse({'erro': 'Sem permissao'}, status=403)
    
    try:
        alvo = Motorista.objects.get(id=usuario_id)
    except Motorista.DoesNotExist:
        return JsonResponse({'erro': 'Usuario nao encontrado'}, status=404)
    
    # Nao pode editar quem tem cargo >= ao seu, exceto se for Gestor
    nivel_logado = CARGO_NIVEL.get(perfil.cargo, 0)
    nivel_alvo = CARGO_NIVEL.get(alvo.cargo, 0)
    
    if nivel_alvo >= nivel_logado and perfil.cargo != 'GESTOR':
        return JsonResponse({'erro': 'Voce nao pode editar este usuario'}, status=403)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'erro': 'JSON invalido'}, status=400)
    
    # Atualiza campos permitidos
    if 'tipo_usuario' in data:
        alvo.tipo_usuario = data['tipo_usuario']
    
    if 'cargo' in data:
        cargo_novo = data['cargo']
        nivel_novo = CARGO_NIVEL.get(cargo_novo, 0)
        if nivel_novo >= nivel_logado and perfil.cargo != 'GESTOR':
            return JsonResponse({'erro': f'Voce nao pode promover para {cargo_novo}'}, status=403)
        alvo.cargo = cargo_novo
    
    if 'filial_id' in data:
        if perfil.cargo == 'GESTOR':
            alvo.filial_id = data['filial_id']
        else:
            return JsonResponse({'erro': 'Apenas Gestor pode mudar filial'}, status=403)
    
    if 'nome' in data:
        alvo.nome_completo = data['nome']
        
    if 'is_sac_mobile' in data:
        alvo.is_sac_mobile = bool(data['is_sac_mobile'])
        
    if 'email' in data:
        alvo.email = data['email']
    
    alvo.save()
    
    return JsonResponse({'status': 'ok', 'mensagem': f'{alvo.nome_completo} atualizado!'})


@login_required
@require_http_methods(["DELETE"])
def api_deletar_usuario(request, usuario_id):
    """Deleta um usuario (valida hierarquia)."""
    perfil = get_perfil_logado(request)
    if not perfil or not pode_gerenciar(perfil):
        return JsonResponse({'erro': 'Sem permissao'}, status=403)
    
    try:
        alvo = Motorista.objects.get(id=usuario_id)
    except Motorista.DoesNotExist:
        return JsonResponse({'erro': 'Usuario nao encontrado'}, status=404)
    
    nivel_logado = CARGO_NIVEL.get(perfil.cargo, 0)
    nivel_alvo = CARGO_NIVEL.get(alvo.cargo, 0)
    
    if nivel_alvo >= nivel_logado and perfil.cargo != 'GESTOR':
        return JsonResponse({'erro': 'Voce nao pode excluir este usuario'}, status=403)
        
    if alvo.id == perfil.id:
        return JsonResponse({'erro': 'Voce nao pode excluir a si mesmo'}, status=403)
    
    # Gerente so deleta MEMBRO
    if perfil.cargo == 'GERENTE' and alvo.cargo != 'MEMBRO':
        return JsonResponse({'erro': 'Gerente so pode excluir Membros'}, status=403)
    
    nome = alvo.nome_completo
    
    # Deleta User associado se existir
    if alvo.user:
        alvo.user.delete()
    alvo.delete()
    
    return JsonResponse({'status': 'ok', 'mensagem': f'{nome} removido com sucesso!'})


@login_required
@require_POST
def api_salvar_permissoes(request, usuario_id):
    """Salva permissoes individuais de um usuario."""
    perfil = get_perfil_logado(request)
    if not perfil:
        return JsonResponse({'erro': 'Sem permissao'}, status=403)
    
    # Apenas GESTOR pode alterar permissoes
    if perfil.cargo != 'GESTOR':
        return JsonResponse({'erro': 'Apenas Gestor pode alterar permissoes'}, status=403)
    
    try:
        alvo = Motorista.objects.get(id=usuario_id)
    except Motorista.DoesNotExist:
        return JsonResponse({'erro': 'Usuario nao encontrado'}, status=404)
    
    # Nao pode alterar permissoes de GESTOR
    if alvo.cargo == 'GESTOR':
        return JsonResponse({'erro': 'Nao e possivel alterar permissoes de um Gestor'}, status=403)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'erro': 'JSON invalido'}, status=400)
    
    # Cria permissoes se nao existirem
    perm, created = PermissaoUsuario.objects.get_or_create(
        motorista=alvo,
        defaults=PermissaoUsuario.defaults_por_cargo(alvo.cargo, alvo.tipo_usuario)
    )
    
    # Atualiza cada permissao enviada
    campos_permitidos = [f.name for f in PermissaoUsuario._meta.get_fields() 
                         if hasattr(f, 'name') and f.name.startswith('pode_')]
    
    for campo in campos_permitidos:
        if campo in data:
            setattr(perm, campo, bool(data[campo]))
    
    perm.save()
    
    return JsonResponse({'status': 'ok', 'mensagem': f'Permissoes de {alvo.nome_completo} atualizadas!'})
