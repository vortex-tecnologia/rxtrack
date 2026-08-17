from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from manifesto.models import Manifesto
from usuarios.models import Filial, Motorista
from django.db.models import Count, Q


@login_required(login_url='/login/')
def painel_monitoramento(request):
    hoje = timezone.now().date()
    
    # 1. Identificar a filial do usuário logado (se houver perfil)
    usuario_filial = None
    if request.user.is_authenticated:
        try:
            perfil = getattr(request.user, 'motorista_perfil', None) or Motorista.objects.select_related('filial').filter(user=request.user).first()
            if perfil:
                usuario_filial = perfil.filial
        except Exception:
            pass

    # 2. Carregar todas as filiais cadastradas com contagem de manifestos ativos
    filiais_qs = Filial.objects.all().order_by('nome')
    filiais_data = []
    for f in filiais_qs:
        total_ativos = Manifesto.objects.filter(filial=f, status='EM_TRANSPORTE').count()
        filiais_data.append({
            'id': f.id,
            'nome': f.nome,
            'total_ativos': total_ativos,
        })

    # 3. Definir qual filial inicia ativa (Prioridade: URL param -> Filial do Usuário -> 1ª Filial da lista)
    filial_param_id = request.GET.get('filial')
    filial_ativa_id = None
    
    if filial_param_id and filial_param_id.isdigit():
        filial_ativa_id = int(filial_param_id)
    elif usuario_filial:
        filial_ativa_id = usuario_filial.id
    elif filiais_data:
        filial_ativa_id = filiais_data[0]['id']

    # 4. Busca todos os manifestos ativos (todas as filiais) para permitir troca instantânea via JS
    manifestos = Manifesto.objects.filter(
        status='EM_TRANSPORTE'
    ).select_related('motorista', 'filial').annotate(
        total_nfe=Count('notas_fiscais', distinct=True),
        baixadas=Count('notas_fiscais', filter=Q(notas_fiscais__status__in=['BAIXADA', 'OCORRENCIA']), distinct=True),
        total_ilegivel=Count('notas_fiscais__baixa_info', filter=Q(notas_fiscais__baixa_info__solicitar_nova_foto=True), distinct=True)
    ).order_by('filial', 'motorista__user__first_name')

    context = {
        'manifestos': manifestos,
        'filiais': filiais_data,
        'filial_ativa_id': filial_ativa_id,
        'hoje': hoje,
        'titulo': 'Torre de Controle Live',
        'usuario_nome': request.user.get_full_name() or request.user.username,
        'filial_selecionada': 'todas', # Conecta o socket ao grupo geral para escutar todas as filiais
    }
    return render(request, 'desktop/paginas/painel/monitoramento.html', context)