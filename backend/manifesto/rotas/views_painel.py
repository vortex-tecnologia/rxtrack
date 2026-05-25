from django.shortcuts import render
from django.contrib.auth.decorators import login_required # Import correto para funções
from django.utils import timezone
from manifesto.models import Manifesto, NotaFiscal
from django.db.models import Count, Q

@login_required(login_url='/login/') # Garante que só acessa se estiver logado
def painel_monitoramento(request):
    hoje = timezone.now().date()
    
    # Filtrar por filial do usuário se aplicável
    usuario_filial = None
    if request.user.is_authenticated:
        try:
            from usuarios.models import Motorista
            perfil = Motorista.objects.get(user=request.user)
            usuario_filial = perfil.filial
        except Motorista.DoesNotExist:
            pass

    # A filial ativa pro WebSocket (se existir, o slug do nome)
    from django.utils.text import slugify
    filial_selecionada = slugify(usuario_filial.nome) if usuario_filial else "todas"

    # Buscamos manifestos de hoje (Ativos)
    # Aqui a view não filtra por filial no ORM (vê todos os ativos), 
    # mas caso precise isolar, seria:
    # qs = Manifesto.objects.filter(status='EM_TRANSPORTE')
    # if usuario_filial: qs = qs.filter(filial=usuario_filial)
    
    # Manter o comportamento existente de exibir todos (?) ou filtrar?
    # O user pediu isolamento. Vamos filtrar a exibição inicial também!
    qs = Manifesto.objects.filter(status='EM_TRANSPORTE')
    # Opcional: Se 'filial' puder ser passada na URL
    # 2. FILTRO DE FILIAL (Prioridade: URL param -> Perfil do Usuário -> Todas)
    filial_param_id = request.GET.get('filial')
    if filial_param_id == 'todas' or filial_param_id == 'Todas as Filiais':
        # Não filtra por filial, mostra tudo
        pass
    elif filial_param_id:
        qs = qs.filter(filial_id=filial_param_id)
    elif usuario_filial:
        qs = qs.filter(filial=usuario_filial)

    manifestos = qs.select_related('motorista', 'filial').annotate(
        total_nfe=Count('notas_fiscais'),
        baixadas=Count('notas_fiscais', filter=Q(notas_fiscais__status__in=['BAIXADA', 'OCORRENCIA']))
    ).order_by('filial', 'motorista__user__first_name')

    context = {
        'manifestos': manifestos,
        'hoje': hoje,
        'titulo': 'Painel de Monitoramento',
        'usuario_nome': request.user.get_full_name() or request.user.username,
        'filial_selecionada': filial_selecionada, # Adicionado para o WebSocket
    }
    return render(request, 'desktop/paginas/painel/monitoramento.html', context)