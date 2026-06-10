from django.shortcuts import render, redirect
from django.db import transaction
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login
from usuarios.models import Motorista , Filial
from manifesto.models import Manifesto, Ocorrencia , NotaFiscal , BaixaNF , ManifestoBuscaLog, HistoricoOcorrencia
from suporte.models import VideoTreinamento
import json
from django.views.generic import TemplateView, ListView
from usuarios.decorators import apenas_operacional
from django.utils import timezone
from datetime import timedelta
from configuracao.models import ConfiguracaoSistema
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.db.models import Count, Q, Sum, Avg, ExpressionWrapper, FloatField, Prefetch
from collections import defaultdict

def login_operacional_view(request):
    # ✅ NOVO: Se o usuário já estiver logado, redireciona para a página certa
    if request.method == 'GET':
        if request.user.is_authenticated:
            try:
                tipo = request.user.motorista_perfil.tipo_usuario
                if tipo == 'OPERACIONAL':
                    return redirect('/dashboard/') 
                elif tipo in ['SAC', 'GESTOR']:
                    return redirect('/dashboard/')
            except Exception:
                pass
        return render(request, 'desktop/login.html')

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            cpf = data.get('cpf', '').replace('.', '').replace('-', '')
            senha = data.get('senha')
            acao = data.get('acao') 

            try:
                perfil = Motorista.objects.get(cpf=cpf)
            except Motorista.DoesNotExist:
                return JsonResponse({'status': 'erro', 'message': 'CPF não registrado.'}, status=404)

            # 1. Removida a restrição de acesso exclusivo do painel para a tela unificada

            # 2. Lógica de Verificação Inicial
            # Identifica se é SAC para App ou SAC para Painel
            tipo_retorno = perfil.tipo_usuario
            if perfil.tipo_usuario == 'SAC' and getattr(perfil, 'is_sac_mobile', False):
                tipo_retorno = 'SAC_MOBILE'
            
            if acao == 'verificar':
                if not perfil.user or not perfil.user.has_usable_password():
                    return JsonResponse({'status': 'novo_usuario', 'nome': perfil.nome_completo, 'tipo': tipo_retorno})
                else:
                    return JsonResponse({'status': 'usuario_registrado', 'nome': perfil.nome_completo, 'tipo': tipo_retorno})

            # Definição do link baseado no cargo (Não usado mais para JWT motorista, mas mantido por segurança)
            url_destino = '/dashboard/' if tipo_retorno in ['OPERACIONAL', 'SAC', 'GESTOR'] else '/app-sac/' if tipo_retorno == 'SAC_MOBILE' else '/app/'

            # 3. Lógica de Cadastro de Senha
            if acao == 'cadastrar':
                if not perfil.user:
                    user = User.objects.create_user(username=cpf, password=senha)
                    if perfil.nome_completo:
                        user.first_name = perfil.nome_completo.split()[0]
                        nomes = perfil.nome_completo.split()
                        if len(nomes) > 1:
                            user.last_name = " ".join(nomes[1:])
                    user.save()
                    perfil.user = user
                    perfil.save()
                else:
                    perfil.user.set_password(senha)
                    perfil.user.save()
                
                login(request, perfil.user)
                return JsonResponse({'status': 'sucesso', 'url': url_destino})

            # 4. Lógica de Login Comum
            if acao == 'login':
                user = authenticate(request, username=cpf, password=senha)
                if user:
                    login(request, user)
                    return JsonResponse({'status': 'sucesso', 'url': url_destino})
                else:
                    return JsonResponse({'status': 'erro', 'message': 'Senha incorreta.'}, status=401)

        except Exception as e:
            return JsonResponse({'status': 'erro', 'message': str(e)}, status=500)

# logout do operacional
from django.contrib.auth import logout
def logout_operacional_view(request):
    logout(request)
    return redirect('/login/')

@method_decorator(login_required, name='dispatch')
@method_decorator(apenas_operacional, name='dispatch')
class DashboardView(TemplateView):
    template_name = 'desktop/paginas/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoje_inicio = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        hoje_fim = hoje_inicio + timedelta(days=1)

        # Pega nome, foto e FILIAL do usuario logado
        context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.last_name or self.request.user.username
        context['usuario_foto'] = ''
        usuario_filial = None
        
        try:
            perfil = Motorista.objects.get(user=self.request.user)
            usuario_filial = perfil.filial
            if perfil.foto_perfil:
                context['usuario_foto'] = perfil.foto_perfil.url
        except Motorista.DoesNotExist:
            pass

        # Recupera parâmetro de filtro da URL
        filial_param = self.request.GET.get('filial')

        # --- 1. CARDS DE RESUMO ---
        # 1. Busca os manifestos do dia
        manifestos_do_dia = Manifesto.objects.filter(data_criacao__range=(hoje_inicio, hoje_fim)).exclude(numero_manifesto__startswith='SAC-')
        
        # 2. Aplica filtro de Filial (Prioridade: URL param -> Perfil do Usuário -> Vazio)
        sem_filial = not bool(usuario_filial)
        
        if filial_param == 'todas':
            # Se filtrou explicitamente por 'todas', mostra tudo
            pass
        elif filial_param:
            # Se filtrou por uma filial específica, mostra ela
            manifestos_do_dia = manifestos_do_dia.filter(filial_id=filial_param)
        elif usuario_filial:
            # Padrão: mostra a do usuário
            manifestos_do_dia = manifestos_do_dia.filter(filial=usuario_filial)
        else:
            # Se não filtrou nada e não tem filial, não mostra nada
            manifestos_do_dia = manifestos_do_dia.none()

        notas_do_dia = NotaFiscal.objects.filter(manifesto__in=manifestos_do_dia)

        # para filtrar as notas que pertencem aos manifestos ativos do dia
        context['notas_em_transporte'] = NotaFiscal.objects.filter(
            status='PENDENTE',
            manifesto__in=manifestos_do_dia, # Notas que pertencem aos manifestos do dia...
            manifesto__status='EM_TRANSPORTE' # ...e que o manifesto esteja em transporte
        ).count()
        context['mfts_ativos'] = manifestos_do_dia.filter(status='EM_TRANSPORTE').count()
        context['total_notas'] = notas_do_dia.filter(status='BAIXADA').count()
        context['notas_ocorrencia'] = notas_do_dia.filter(status='OCORRENCIA').count()
        # Pega todas as notas em transporte junto com as que foram baixadas e com ocorrencias 
        


        # --- 2. TOP PERFORMANCE (MOTORISTAS REAIS) ---
        # Pegamos motoristas que tiveram notas baixadas hoje
        top_motoristas = (
            Motorista.objects.filter(manifestos__in=manifestos_do_dia)
            .annotate(
                total=Count('manifestos__notas_fiscais'),
                entregues=Count('manifestos__notas_fiscais', filter=Q(manifestos__notas_fiscais__status__in=['BAIXADA', 'OCORRENCIA'])),
            )
            .filter(total__gt=0)
            .order_by('-entregues')[:5] # Top 5
        )

        # Calculamos o percentual para cada um
        for m in top_motoristas:
            m.percentual = int((m.entregues / m.total) * 100) if m.total > 0 else 0
            m.ultimo_mft = m.manifestos.filter(data_criacao__range=(hoje_inicio, hoje_fim)).last()

        context['top_motoristas'] = top_motoristas

        # --- 3. DADOS DO GRÁFICO (ENTREGAS POR HORA) ---
        # Agrupamos as baixas de hoje por hora
        from collections import defaultdict

        baixas_hoje = BaixaNF.objects.filter(
            data_baixa__range=(hoje_inicio, hoje_fim)
        )

        contador_por_hora = defaultdict(int)

        for baixa in baixas_hoje:
            hora_local = timezone.localtime(baixa.data_baixa).hour
            contador_por_hora[hora_local] += 1

        horas_labels = [f"{h:02d}:00" for h in range(8, 21)]

        acumulado = 0
        valores_finais = []

        for h in range(8, 21):
            acumulado += contador_por_hora.get(h, 0)
            valores_finais.append(acumulado)

        context['grafico_labels'] = json.dumps(horas_labels)
        context['grafico_valores'] = json.dumps(valores_finais)
        
        context['titulo'] = "Painel de Controle Operacional"
        context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.username
        
        # Passar lista de filiais e filial ativa para o Dropdown no Frontend
        context['filiais'] = Filial.objects.all().order_by('nome')
        context['filial_selecionada'] = filial_param if filial_param else (str(usuario_filial.id) if usuario_filial else 'todas')
        context['sem_filial'] = sem_filial
        
        return context




@method_decorator(login_required, name='dispatch')
@method_decorator(apenas_operacional, name='dispatch')
class NotasFiscaisListView(ListView):
    template_name = 'desktop/paginas/notas_fiscais.html'
    context_object_name = 'notas'
    paginate_by = 50

    def get_queryset(self):
        usuario_filial = None
        if self.request.user.is_authenticated:
            try:
                perfil = Motorista.objects.get(user=self.request.user)
                usuario_filial = perfil.filial
            except Motorista.DoesNotExist:
                pass

        # Subquery para pegar apenas a última baixa_info de cada nota de forma eficiente
        # No Django 4.x+, prefetch_related com to_attr e QuerySet limitado funciona bem
        baixas_prefetch = BaixaNF.objects.order_by('-data_baixa')

        queryset = NotaFiscal.objects.select_related(
            'manifesto', 'manifesto__motorista'
        ).prefetch_related(
            Prefetch('baixa_info', queryset=baixas_prefetch, to_attr='_prefetched_ultima_baixa'),
            'baixa_info__ocorrencia'
        ).order_by('-manifesto__data_criacao', '-id')

        # --- LÓGICA DE FILTROS ---
        q = self.request.GET.get('q') # Busca Geral (NF ou Chave)
        motorista = self.request.GET.get('motorista')
        manifesto = self.request.GET.get('manifesto')
        integrado = self.request.GET.get('integrado')
        data_inicio = self.request.GET.get('data_inicio')
        filial_param = self.request.GET.get('filial')

        if filial_param == 'todas':
            pass
        elif filial_param:
            queryset = queryset.filter(manifesto__filial_id=filial_param)
        elif usuario_filial:
            queryset = queryset.filter(manifesto__filial=usuario_filial)
        else:
            queryset = queryset.none()

        if q:
            queryset = queryset.filter(
                Q(numero_nota__icontains=q) | Q(chave_acesso__icontains=q)
            )
        
        if motorista:
            queryset = queryset.filter(manifesto__motorista__nome_completo__icontains=motorista)
            
        if manifesto:
            queryset = queryset.filter(manifesto__numero_manifesto__icontains=manifesto)

        if integrado:
            is_integrado = integrado == 'sim'
            queryset = queryset.filter(baixa_info__integrado_tms=is_integrado)

        if data_inicio:
            queryset = queryset.filter(manifesto__data_criacao__date=data_inicio)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        usuario_filial = None
        if self.request.user.is_authenticated:
            try:
                perfil = Motorista.objects.get(user=self.request.user)
                usuario_filial = perfil.filial
            except Motorista.DoesNotExist:
                pass

        filial_param = self.request.GET.get('filial')

        context['ocorrencias'] = Ocorrencia.objects.all().order_by('descricao')
        context['titulo'] = "Gestão de Notas Fiscais"
        context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.username
        context['filiais'] = Filial.objects.all().order_by('nome')
        context['filial_selecionada'] = filial_param if filial_param else (str(usuario_filial.id) if usuario_filial else 'todas')
        context['sem_filial'] = not bool(usuario_filial)
        
        return context

from django.shortcuts import render, get_object_or_404
from manifesto.models import NotaFiscal

# Use os decoradores diretamente na função, sem o method_decorator
@login_required(login_url='/login/')
@apenas_operacional
def detalhes_nota_fiscal_view(request, nota_id):
    # 1. Busca a nota de referência para descobrir a chave de acesso
    nota_clicada = get_object_or_404(NotaFiscal, id=nota_id)
    
    # 2. Define o filtro para buscar o histórico de forma inteligente
    if nota_clicada.chave_acesso:
        # Se tem chave, busca por ela (Padrão para NF-e)
        filtros_historico = Q(chave_acesso=nota_clicada.chave_acesso)
    elif nota_clicada.tipo_operacao == 'COLETA':
        # Para coletas sem chave, busca por numero_coleta ou ID do TMS
        filtros_historico = Q(tipo_operacao='COLETA') & (
            Q(numero_coleta=nota_clicada.numero_coleta) | 
            Q(freight_id_tms=nota_clicada.freight_id_tms)
        )
    else:
        # Para minutas/outros sem chave, busca pelo número da nota
        filtros_historico = Q(numero_nota=nota_clicada.numero_nota) & Q(chave_acesso__isnull=True)

    # 3. Busca TODAS as ocorrências dessa nota conforme os filtros definidos
    historico_completo = NotaFiscal.objects.filter(
        filtros_historico
    ).select_related(
        'manifesto', 
        'manifesto__motorista'
    ).prefetch_related(
        'baixa_info',           
        'baixa_info__ocorrencia' 
    ).order_by('-manifesto__data_criacao')

    context = {
        'nota_principal': nota_clicada,
        'historico': historico_completo,
    }
    
    # Retorna apenas o fragmento HTML para o modal
    return render(request, 'desktop/parciais/detalhes_nota_modal.html', context)

import pytz
from datetime import datetime, time
# Pagina Manifesto 
@method_decorator(login_required(login_url='/login/'), name='dispatch')
@method_decorator(apenas_operacional, name='dispatch')
class ManifestosMonitoramentoView(ListView):
    model = Manifesto
    template_name = 'desktop/paginas/manifesto.html'
    context_object_name = 'manifestos'
    paginate_by = 20

    def get_queryset(self):
        usuario_filial = None
        if self.request.user.is_authenticated:
            try:
                perfil = Motorista.objects.get(user=self.request.user)
                usuario_filial = perfil.filial
            except Motorista.DoesNotExist:
                pass

        # Otimização: traz motorista e conta as notas em uma única query
        queryset = Manifesto.objects.select_related('motorista', 'filial').exclude(numero_manifesto__startswith='SAC-').annotate(
            total_notas=Count('notas_fiscais'),
            notas_concluidas=Count(
                'notas_fiscais', 
                filter=Q(notas_fiscais__status__in=['BAIXADA', 'OCORRENCIA'])
            )
        ).order_by('-data_criacao')

        # Filtros
        filial_id = self.request.GET.get('filial')
        numero = self.request.GET.get('numero')
        motorista = self.request.GET.get('motorista')
        data_str = self.request.GET.get('data')

        if filial_id == 'todas':
            pass
        elif filial_id:
            queryset = queryset.filter(filial_id=filial_id)
        elif usuario_filial:
            queryset = queryset.filter(filial=usuario_filial)
        else:
            queryset = queryset.none()
        
        if numero:
            queryset = queryset.filter(numero_manifesto__icontains=numero)
        
        if motorista:
            queryset = queryset.filter(motorista__nome_completo__icontains=motorista)
        
        if data_str:
            try:
                # 1. Converte a string do input (YYYY-MM-DD) para objeto date
                data_foco = datetime.strptime(data_str.strip(), '%Y-%m-%d').date()
                
                # 2. Define o fuso horário de Brasília
                tz = pytz.timezone('America/Sao_Paulo')
                
                # 3. Cria o range: de 00:00:00 até 23:59:59 no horário de Brasília
                # O Django converterá isso para UTC automaticamente ao consultar o banco
                inicio_dia = tz.localize(datetime.combine(data_foco, time.min))
                fim_dia = tz.localize(datetime.combine(data_foco, time.max))
                
                # 4. Filtra pelo intervalo (muito mais seguro que __date)
                queryset = queryset.filter(data_criacao__range=(inicio_dia, fim_dia))
                
            except (ValueError, TypeError):
                pass

        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        usuario_filial = None
        if self.request.user.is_authenticated:
            try:
                perfil = Motorista.objects.get(user=self.request.user)
                usuario_filial = perfil.filial
            except Motorista.DoesNotExist:
                pass
                
        # Manter os valores dos filtros no contexto para o formulário não resetar
        context['filiais'] = Filial.objects.all().order_by('nome')
        context['titulo'] = "Monitoramento de Manifestos"
        context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.username
        
        # Opcional: passa os filtros atuais para o template (útil para manter o estado dos inputs)
        filial_param = self.request.GET.get('filial')
        context['filial_selecionada'] = filial_param if filial_param else (str(usuario_filial.id) if usuario_filial else 'todas')
        context['filtro_data'] = self.request.GET.get('data', '')
        context['filtro_numero'] = self.request.GET.get('numero', '')
        context['motoristas_list'] = Motorista.objects.all().order_by('nome_completo')
        context['ultimos_logs'] = ManifestoBuscaLog.objects.all().order_by('-atualizado_em')[:5]
        context['sem_filial'] = not bool(usuario_filial)
        
        return context
    
@login_required
def detalhes_manifesto_modal_view(request, manifesto_id):
    # Busca o manifesto e faz o prefetch das notas e baixas para ser rápido
    from manifesto.models import Manifesto, NotaFiscal
    from django.db.models import Count, Q
    from django.shortcuts import get_object_or_404

    manifesto = get_object_or_404(Manifesto, id=manifesto_id)
    notas = NotaFiscal.objects.filter(manifesto=manifesto)
    
    total_notas = notas.count()
    concluidas = notas.filter(status='BAIXADA').count()
    
    # Cálculo da percentagem com segurança para não dividir por zero
    progresso = (concluidas / total_notas * 100) if total_notas > 0 else 0
    
    context = {
        'manifesto': manifesto,
        'notas': notas,
        'total_notas': total_notas,
        'concluidas': concluidas,
        'progresso': int(progresso)
    }
    return render(request, 'desktop/parciais/detalhes_manifesto_modal.html', context)

@login_required
def editar_manifesto_modal_view(request, manifesto_id):
    from manifesto.models import Manifesto, Motorista, Filial
    
    manifesto = get_object_or_404(Manifesto, id=manifesto_id)
    motoristas = Motorista.objects.all().order_by('nome_completo')
    filiais = Filial.objects.all().order_by('nome')
    
    context = {
        'manifesto': manifesto,
        'motoristas': motoristas,
        'filiais': filiais,
    }
    return render(request, 'desktop/parciais/editar_manifesto_modal.html', context)

from django.views.decorators.http import require_POST

@login_required
@require_POST
def salvar_edicao_manifesto_view(request, manifesto_id):
    """
    Processa a atualização dos dados do manifesto via AJAX.
    Trava campos sensíveis e valida a integridade dos KMs.
    """
    manifesto = get_object_or_404(Manifesto, id=manifesto_id)
    
    try:
        # 1. Captura de dados do POST
        status_post = request.POST.get('status')
        filial_id = request.POST.get('filial')
        km_ini_raw = request.POST.get('km_inicial')
        km_fin_raw = request.POST.get('km_final')
        foi_finalizado = request.POST.get('finalizado') == 'on'

        # 2. Conversão e Validação de KMs
        # Substituímos vírgula por ponto para evitar erro de conversão
        km_inicial = float(km_ini_raw.replace(',', '.')) if km_ini_raw else 0.0
        km_final = float(km_fin_raw.replace(',', '.')) if km_fin_raw else 0.0

        if km_final > 0 and km_final < km_inicial:
            return JsonResponse({
                'success': False, 
                'message': f'Erro: KM Final ({km_final}) não pode ser menor que o Inicial ({km_inicial}).'
            }, status=400)

        # 3. Atualização dos campos permitidos
        manifesto.status = status_post
        manifesto.km_inicial = km_inicial if km_ini_raw else None
        manifesto.km_final = km_final if km_fin_raw else None
        
        if filial_id:
            manifesto.filial_id = filial_id

        # 4. Lógica de Status e Datas de Finalização
        enviar_finalizacao_tms = False
        # Se o checkbox de finalizar foi marcado agora
        if foi_finalizado and not manifesto.finalizado:
            manifesto.finalizado = True
            manifesto.data_finalizacao = timezone.now()
            manifesto.status = 'FINALIZADO'
            enviar_finalizacao_tms = True
        
        # Se o checkbox foi desmarcado (reabertura de manifesto)
        elif not foi_finalizado and manifesto.finalizado:
            manifesto.finalizado = False
            manifesto.data_finalizacao = None
            # Se estava FINALIZADO, volta para EM_TRANSPORTE ao reabrir
            if manifesto.status == 'FINALIZADO':
                manifesto.status = 'EM_TRANSPORTE'

        # 5. Salva no Banco de Dados
        manifesto.save()

        # Dispara integração TMS em background se acabou de ser finalizado
        if enviar_finalizacao_tms:
            from manifesto.tasks import finalizar_manifesto_tms_task
            finalizar_manifesto_tms_task.delay(manifesto.id)

        return JsonResponse({
            'success': True, 
            'message': 'Manifesto atualizado com sucesso!',
            'novo_status': manifesto.get_status_display()
        })

    except ValueError:
        return JsonResponse({
            'success': False, 
            'message': 'Erro: Os valores de KM devem ser números válidos.'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'message': f'Erro inesperado: {str(e)}'
        }, status=500)

@login_required
@require_POST
def sincronizar_manifesto_operacional_view(request, manifesto_id):
    """
    Inicia a sincronização de um manifesto já existente via Painel Operacional.
    """
    from manifesto.models import ManifestoBuscaLog
    from manifesto.tasks import buscar_manifesto_completo_task
    
    manifesto = get_object_or_404(Manifesto, id=manifesto_id)
    
    try:
        # Se não tiver motorista, usa o usuário logado (opcional) ou não atrela
        # A task buscar_manifesto_completo_task espera um log de busca com motorista.
        # Se for o operacional forçando, talvez possamos usar o motorista do manifesto
        motorista_vinculado = manifesto.motorista
        
        # Cria ou atualiza o log de busca
        log, created = ManifestoBuscaLog.objects.update_or_create(
            numero_manifesto=manifesto.numero_manifesto,
            motorista=motorista_vinculado, # Pode ser None se o manifesto não tiver motorista
            defaults={'status': 'AGUARDANDO', 'mensagem_erro': None}
        )
        
        # Dispara a busca
        buscar_manifesto_completo_task.delay(log.id)
        
        return JsonResponse({
            'success': True,
            'message': 'A sincronização com o TMS foi iniciada no servidor.'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Erro ao iniciar sincronização: {str(e)}'
        }, status=500)

@login_required
@require_POST
def deletar_manifesto_operacional_view(request, manifesto_id):
    """
    Deleta totalmente o manifesto e suas dependências.
    """
    manifesto = get_object_or_404(Manifesto, id=manifesto_id)
    
    try:
        nome_mft = manifesto.numero_manifesto
        # Django apaga as NFs em cascata devido a on_delete=models.CASCADE 
        # nas ForeignKey's referentes
        manifesto.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Manifesto #{nome_mft} deletado permanentemente.'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Houve um erro ao deletar: {str(e)}'
        }, status=500)
    

from datetime import datetime, time
import pytz
from django.db.models import Count, Q, ExpressionWrapper, FloatField, Case, When, Value
from django.db.models.functions import Cast, Round
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from usuarios.models import Motorista

class MotoristasPerformanceView(LoginRequiredMixin, ListView):
    model = Motorista
    template_name = 'desktop/paginas/motoristas_list.html'
    context_object_name = 'motoristas'
    login_url = '/login/'

    def get_queryset(self):
        # Captura filial do usuário ativo
        usuario_filial = None
        if self.request.user.is_authenticated:
            try:
                perfil = Motorista.objects.get(user=self.request.user)
                usuario_filial = perfil.filial
            except Motorista.DoesNotExist:
                pass
                
        # 1. Base: Apenas quem é motorista
        queryset = Motorista.objects.filter(tipo_usuario='MOTORISTA')
        
        filial_param = self.request.GET.get('filial')
        
        if filial_param == 'todas':
            pass
        elif filial_param:
            queryset = queryset.filter(filial_id=filial_param)
        elif usuario_filial:
            queryset = queryset.filter(filial=usuario_filial)
        else:
            queryset = queryset.none()

        # 2. Captura datas do filtro
        data_inicio_str = self.request.GET.get('data_inicio')
        data_fim_str = self.request.GET.get('data_fim')

        filtros_periodo = Q()

        if data_inicio_str and data_fim_str:
            try:
                tz = pytz.timezone('America/Sao_Paulo')
                
                # Converte strings para objetos date
                d_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
                d_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
                
                # Cria o range com fuso horário (mesma lógica da sua outra view)
                inicio_dt = tz.localize(datetime.combine(d_inicio, time.min))
                fim_dt = tz.localize(datetime.combine(d_fim, time.max))
                
                # Define o filtro que será usado nas anotações
                filtros_periodo = Q(manifestos__data_criacao__range=(inicio_dt, fim_dt))
                
                # OBRIGATÓRIO: Filtra o queryset principal para garantir que os counts 
                # só olhem para motoristas que tiveram manifestos nesse range
                queryset = queryset.filter(manifestos__data_criacao__range=(inicio_dt, fim_dt)).distinct()
                
            except (ValueError, TypeError):
                pass

        # 3. Agora fazemos os cálculos baseados no filtro de período
        queryset = queryset.annotate(
            total_mfts=Count('manifestos', distinct=True, filter=filtros_periodo),
            
            baixas_sucesso=Count(
                'manifestos__notas_fiscais', 
                filter=filtros_periodo & Q(manifestos__notas_fiscais__status='BAIXADA')
            ),
            
            ocorrencias_20=Count(
                'manifestos__notas_fiscais', 
                filter=filtros_periodo & Q(manifestos__notas_fiscais__baixa_info__ocorrencia__codigo_tms='20')
            ),
            # pega todas as notas com status de pendente 
            baixas_pendentes=Count(
                'manifestos__notas_fiscais', 
                distinct=True,
                filter=filtros_periodo & Q(manifestos__notas_fiscais__status='PENDENTE')
            ),

            total_notas_geral=Count(
                'manifestos__notas_fiscais', 
                filter=filtros_periodo
            )
        ).annotate(
            reputacao=ExpressionWrapper(
                Round(
                    Case(
                        When(total_notas_geral__gt=0, 
                             then=(Cast('baixas_sucesso', FloatField()) / Cast('total_notas_geral', FloatField())) * 100),
                        default=Value(0.0),
                    ), 1
                ),
                output_field=FloatField()
            )
        ).order_by('-reputacao', '-baixas_sucesso')

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        usuario_filial = None
        if self.request.user.is_authenticated:
            try:
                perfil = Motorista.objects.get(user=self.request.user)
                usuario_filial = perfil.filial
            except Motorista.DoesNotExist:
                pass
                
        context['titulo'] = 'Performance de Motoristas'
        context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.username
        context['data_inicio'] = self.request.GET.get('data_inicio', '')
        context['data_fim'] = self.request.GET.get('data_fim', '')
        
        filial_param = self.request.GET.get('filial')
        context['filiais'] = Filial.objects.all().order_by('nome')
        context['filial_selecionada'] = filial_param if filial_param else (str(usuario_filial.id) if usuario_filial else 'todas')
        context['sem_filial'] = not bool(usuario_filial)
        
        return context
    
# WS PARA ATUALIZAR O PAINEL EM TEMPO REAL    
@require_POST
def motorista_cadastrar(request):
    import re
    try:
        nome = request.POST.get('nome_completo')
        cpf_sujo = request.POST.get('cpf')
        telefone = request.POST.get('telefone', '')
        filial_id = request.POST.get('filial_id')
        foto = request.FILES.get('foto_perfil')

        # Remove tudo que não for número (limpa pontos e traços)
        cpf_limpo = re.sub(r'\D', '', cpf_sujo)

        Motorista.objects.create(
            nome_completo=nome,
            cpf=cpf_limpo,
            telefone=telefone,
            filial_id=filial_id if filial_id else None,
            foto_perfil=foto
        )
        return JsonResponse({'success': True, 'message': 'Motorista cadastrado com sucesso!'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Erro ao cadastrar: {str(e)}'})

@require_POST
def motorista_editar(request):
    import re
    try:
        id_m = request.POST.get('motorista_id')
        motorista = get_object_or_404(Motorista, id=id_m)
        
        motorista.nome_completo = request.POST.get('nome_completo')
        motorista.cpf = request.POST.get('cpf')
        motorista.telefone = request.POST.get('telefone', '')
        
        filial_id = request.POST.get('filial_id')
        motorista.filial_id = filial_id if filial_id else None
        
        if request.FILES.get('foto_perfil'):
            motorista.foto_perfil = request.FILES.get('foto_perfil')
            
        motorista.save()
        return JsonResponse({'success': True, 'message': 'Dados atualizados com sucesso!'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Erro ao editar: {str(e)}'})

# --- VIEWS DA CENTRAL DE AJUDA ---

@method_decorator(login_required(login_url='/login/'), name='dispatch')
@method_decorator(apenas_operacional, name='dispatch')
class SuporteView(TemplateView):
    template_name = 'desktop/paginas/suporte.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = "Suporte Online"
        context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.username
        return context

@method_decorator(login_required(login_url='/login/'), name='dispatch')
@method_decorator(apenas_operacional, name='dispatch')
class TreinamentosView(TemplateView):
    template_name = 'desktop/paginas/treinamentos.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = "Treinamentos e Tutoriais"
        context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.username
        context['videos'] = VideoTreinamento.objects.filter(ativo=True)
        return context

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

@csrf_exempt
@login_required(login_url='/login/')
def registrar_view_treinamento(request, video_id):
    if request.method == 'POST':
        try:
            video = VideoTreinamento.objects.get(id=video_id)
            video.visualizacoes += 1
            video.save(update_fields=['visualizacoes'])
            return JsonResponse({'status': 'success', 'views': video.visualizacoes})
        except VideoTreinamento.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Vídeo não encontrado'}, status=404)
    return JsonResponse({'status': 'error', 'message': 'Método inválido'}, status=405)

@csrf_exempt
@login_required(login_url='/login/')
def avaliar_treinamento(request, video_id):
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            tipo = data.get('tipo') # 'like' ou 'dislike'
            
            video = VideoTreinamento.objects.get(id=video_id)
            
            if tipo == 'like':
                video.likes += 1
                video.save(update_fields=['likes'])
                return JsonResponse({'status': 'success', 'likes': video.likes})
            elif tipo == 'dislike':
                video.dislikes += 1
                video.save(update_fields=['dislikes'])
                return JsonResponse({'status': 'success', 'dislikes': video.dislikes})
            else:
                return JsonResponse({'status': 'error', 'message': 'Tipo inválido'}, status=400)
                
        except VideoTreinamento.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Vídeo não encontrado'}, status=404)
    return JsonResponse({'status': 'error', 'message': 'Método inválido'}, status=405)

@method_decorator(login_required(login_url='/login/'), name='dispatch')
@method_decorator(apenas_operacional, name='dispatch')
class CentralAjudaView(TemplateView):
    template_name = 'desktop/paginas/central_ajuda.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = "Central de Ajuda"
        context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.username
        return context

# --- CONFIGURAÇÃO DO SISTEMA ---
@method_decorator(login_required(login_url='/login/'), name='dispatch')
@method_decorator(apenas_operacional, name='dispatch')
class ConfiguracaoSistemaView(TemplateView):
    template_name = 'desktop/paginas/configuracao.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = ConfiguracaoSistema.load()
        perfil = self.request.user.motorista_perfil
        
        # Mascarar tokens se não for gestor
        token_analytics = config.token_analytics
        token_invoices = config.token_invoices
        
        if perfil.cargo != 'GESTOR':
            if token_analytics:
                token_analytics = token_analytics[:5] + "*" * 10 + token_analytics[-5:]
            if token_invoices:
                token_invoices = token_invoices[:5] + "*" * 10 + token_invoices[-5:]

        context.update({
            'config': config,
            'cargo': perfil.cargo,
            'token_analytics_masked': token_analytics,
            'token_invoices_masked': token_invoices,
            'titulo': "Configuração do Sistema",
            'usuario_nome': self.request.user.get_full_name() or self.request.user.username,
        })
        return context

@login_required(login_url='/login/')
@apenas_operacional
@require_POST
def salvar_configuracao_view(request):
    perfil = request.user.motorista_perfil
    if perfil.cargo != 'GESTOR':
        return JsonResponse({'status': 'erro', 'message': 'Acesso negado. Apenas Gestores podem alterar as configurações.'}, status=403)
    
    config = ConfiguracaoSistema.load()
    
    try:
        data = json.loads(request.body)
        
        # Tokens (só atualiza se não vier com asteriscos/mascara do frontend)
        # Na verdade no frontend gestores verão o original, membros verão masked disabled.
        # Mas por segurança, validamos se o campo foi enviado.
        if 'token_analytics' in data: config.token_analytics = data['token_analytics']
        if 'token_invoices' in data: config.token_invoices = data['token_invoices']
        
        config.dominio_esl = data.get('dominio_esl', config.dominio_esl)
        config.report_validacao = data.get('report_validacao', config.report_validacao)
        config.report_busca_nfe = data.get('report_busca_nfe', config.report_busca_nfe)
        
        # Feature Flags
        config.processar_yolo = data.get('processar_yolo', config.processar_yolo)
        config.processar_ocr = data.get('processar_ocr', config.processar_ocr)
        config.enviar_tms = data.get('enviar_tms', config.enviar_tms)
        config.enviar_email_falhas = data.get('enviar_email_falhas', config.enviar_email_falhas)
        config.emails_notificacao = data.get('emails_notificacao', config.emails_notificacao)
        config.armazenar_foto_backup = data.get('armazenar_foto_backup', config.armazenar_foto_backup)
        
        # IA
        config.codigos_ocorrencia_yolo = data.get('codigos_ocorrencia_yolo', config.codigos_ocorrencia_yolo)
        
        config.save()
        return JsonResponse({'status': 'sucesso', 'message': 'Configurações salvas com sucesso!'})
        
    except Exception as e:
        return JsonResponse({'status': 'erro', 'message': str(e)}, status=400)
