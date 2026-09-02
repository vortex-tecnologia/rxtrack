from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Q
from manifesto.models import Manifesto, NotaFiscal, BaixaNF, Ocorrencia
from usuarios.models import Filial, Motorista
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from manifesto.rotas.baixa import upload_via_ftp
from manifesto.tasks import enviar_baixa_esl_task, enviar_baixa_minuta_task, enviar_coleta_esl_task
from .services import (
    calcular_metricas_manifesto,
    gerar_benchmarking_filiais,
    obter_detalhes_360_manifesto
)


@method_decorator(login_required, name='dispatch')
class AuditoriaDashboardView(TemplateView):
    template_name = 'desktop/auditoria_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # 1. Identifica Perfil, Cargo e Filial do Usuário
        usuario_filial = None
        is_gestor = user.is_superuser
        perfil_motorista = None

        if user.is_authenticated:
            try:
                perfil_motorista = Motorista.objects.select_related('filial').get(user=user)
                usuario_filial = perfil_motorista.filial
                if perfil_motorista.cargo in ['ADMINISTRADOR', 'GESTOR', 'GERENTE']:
                    is_gestor = True
            except Exception:
                if user.is_staff or user.is_superuser:
                    is_gestor = True

        # 2. Definição da Filial Ativa (Isolamento Estrito)
        filial_param = self.request.GET.get('filial')
        todas_filiais = Filial.objects.all().order_by('nome')
        filial_ativa = None
        filial_ativa_id = None
        modo_todas_filiais = False

        if is_gestor:
            # Gestor pode alternar filiais ou escolher 'todas'
            if filial_param == 'todas':
                modo_todas_filiais = True
                filial_ativa_id = 'todas'
            elif filial_param:
                filial_ativa = Filial.objects.filter(id=filial_param).first()
                if filial_ativa:
                    filial_ativa_id = str(filial_ativa.id)
                elif usuario_filial:
                    filial_ativa = usuario_filial
                    filial_ativa_id = str(usuario_filial.id)
            elif usuario_filial:
                filial_ativa = usuario_filial
                filial_ativa_id = str(usuario_filial.id)
            elif todas_filiais.exists():
                filial_ativa = todas_filiais.first()
                filial_ativa_id = str(filial_ativa.id)
        else:
            # Operador comum: RESTRITO estritamente à sua filial
            filial_ativa = usuario_filial
            filial_ativa_id = str(usuario_filial.id) if usuario_filial else None

        # 3. Aba Ativa (Sub-menu de Auditoria)
        active_tab = self.request.GET.get('tab', 'cockpit')
        if active_tab not in ['cockpit', 'batalha', 'penalidades']:
            active_tab = 'cockpit'

        # 4. Manifestos Ativos (EM_TRANSPORTE) com anotações de contagem
        manifestos_qs = Manifesto.objects.filter(status='EM_TRANSPORTE').select_related(
            'motorista', 'filial', 'filial_operacao', 'veiculo'
        )

        if not modo_todas_filiais:
            if filial_ativa:
                manifestos_qs = manifestos_qs.filter(
                    Q(filial_operacao=filial_ativa) | (Q(filial_operacao__isnull=True) & Q(filial=filial_ativa))
                )
            else:
                manifestos_qs = manifestos_qs.none()

        motorista_filtro = self.request.GET.get('motorista')
        if motorista_filtro:
            manifestos_qs = manifestos_qs.filter(motorista_id=motorista_filtro)

        manifestos_qs = manifestos_qs.annotate(
            total_notas=Count('notas_fiscais'),
            notas_pendentes=Count('notas_fiscais', filter=Q(notas_fiscais__status='PENDENTE')),
            notas_baixadas=Count('notas_fiscais', filter=Q(notas_fiscais__status__in=['BAIXADA', 'OCORRENCIA']))
        ).order_by('-data_criacao')

        # 5. Processamento Analítico de Cada Motorista em Rota
        agora = timezone.now()
        manifestos_data = [calcular_metricas_manifesto(m, agora=agora) for m in manifestos_qs]

        # KPIs do Topo
        total_ativos = len(manifestos_data)
        total_criticos = sum(1 for d in manifestos_data if d['status_cor'] == 'danger')
        total_atencao = sum(1 for d in manifestos_data if d['status_cor'] == 'warning')
        total_em_analise_ia = sum(d['em_analise_ia'] for d in manifestos_data)

        # Média de Ritmo (Entregas / Hora da base)
        ritmos = [d['ritmo_entregas_hora'] for d in manifestos_data if d['ritmo_entregas_hora'] > 0]
        ritmo_medio_base = round(sum(ritmos) / len(ritmos), 1) if ritmos else 0.0

        # Média de Score da base
        scores = [d['score'] for d in manifestos_data]
        score_medio_base = round(sum(scores) / len(scores), 0) if scores else 100

        # 6. Dados da Aba: Batalha de Filiais (Benchmarking)
        benchmarking = {}
        if active_tab == 'batalha' or is_gestor:
            benchmarking = gerar_benchmarking_filiais()

        # 7. Dados da Aba: Central de Penalidades (Desleixo)
        penalidades_qs = BaixaNF.objects.filter(motivo_baixa='MOTORISTA_DESLEIXO').select_related(
            'nota_fiscal__manifesto__motorista',
            'nota_fiscal__manifesto__filial',
            'nota_fiscal__manifesto__filial_operacao',
            'ocorrencia',
            'autor_baixa'
        ).order_by('-data_baixa')

        if not modo_todas_filiais and filial_ativa:
            penalidades_qs = penalidades_qs.filter(
                Q(nota_fiscal__manifesto__filial_operacao=filial_ativa) |
                (Q(nota_fiscal__manifesto__filial_operacao__isnull=True) & Q(nota_fiscal__manifesto__filial=filial_ativa))
            )

        total_penalidades = penalidades_qs.count()
        ultimas_penalidades = penalidades_qs[:15]

        top_penalidades = penalidades_qs.values(
            'nota_fiscal__manifesto__motorista__nome_completo'
        ).annotate(total=Count('id')).order_by('-total')[:5]

        # 8. Alimenta o Contexto
        context.update({
            'active_tab': active_tab,
            'is_gestor': is_gestor,
            'usuario_filial': usuario_filial,
            'filial_ativa': filial_ativa,
            'filial_ativa_id': filial_ativa_id,
            'modo_todas_filiais': modo_todas_filiais,
            'todas_filiais': todas_filiais,

            # Cockpit
            'manifestos': manifestos_data,
            'total_ativos': total_ativos,
            'total_criticos': total_criticos,
            'total_atencao': total_atencao,
            'total_em_analise_ia': total_em_analise_ia,
            'ritmo_medio_base': ritmo_medio_base,
            'score_medio_base': int(score_medio_base),

            # Batalha de Filiais
            'benchmarking': benchmarking,

            # Penalidades
            'total_penalidades': total_penalidades,
            'ultimas_penalidades': ultimas_penalidades,
            'top_penalidades': top_penalidades,
        })

        return context


class AuditoriaDetalhes360View(APIView):
    """
    Endpoint JSON para carregar os detalhes 360º de um motorista / manifesto
    para exibição instantânea no Drawer lateral de auditoria.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, manifesto_id):
        detalhes = obter_detalhes_360_manifesto(manifesto_id)
        if not detalhes:
            return Response({'erro': 'Manifesto não localizado.'}, status=404)
        
        # Remove instâncias de models Django antes de serializar
        detalhes.pop('obj', None)
        return Response(detalhes)


class RegistrarBaixaManualSACView(APIView):
    """
    Endpoint exclusivo para o SAC realizar baixas forçadas pelo painel de auditoria.
    Suporta anexo de comprovante/foto, validações por tipo de documento e despacho TMS.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        nota_id = request.data.get('nota_id')
        codigo_tms = request.data.get('codigo_tms')
        motivo_baixa = request.data.get('motivo_baixa', 'OPERACAO_NORMAL')
        observacao = request.data.get('observacao', '')
        recebedor_in = request.data.get('recebedor')
        foto_arquivo = request.FILES.get('foto') or request.FILES.get('comprovante')

        if not nota_id or not codigo_tms:
            return Response({'erro': 'Nota e Código de Ocorrência são obrigatórios.'}, status=400)

        try:
            with transaction.atomic():
                nf = NotaFiscal.objects.get(id=nota_id)
                ocorrencia = Ocorrencia.objects.filter(
                    Q(codigo_tms=codigo_tms) | Q(codigo_referencia=codigo_tms)
                ).first()

                if not ocorrencia:
                    return Response({'erro': f'Código de ocorrência {codigo_tms} não localizado.'}, status=400)

                # Regra de validação de foto para ocorrência 01 ou 02 em entregas
                cod_ref = str(ocorrencia.codigo_referencia or ocorrencia.codigo_tms or '').strip()
                if nf.tipo_operacao != 'COLETA' and (cod_ref in ['01', '02', '1', '2'] or str(codigo_tms).strip() in ['01', '02', '1', '2']):
                    if not foto_arquivo:
                        return Response({
                            'erro': 'O anexo de foto/comprovante é OBRIGATÓRIO para entregas finalizadas com código 01 (Entregue) ou 02 (Parcial).'
                        }, status=400)

                # Upload da Foto via FTP caso anexada
                url_final_foto = None
                if foto_arquivo:
                    id_foto = nf.chave_acesso if nf.chave_acesso else f"sac_nota_{nf.numero_nota}"
                    nome_arquivo = f"sac_{nf.id}_{id_foto}.jpg"
                    url_final_foto = upload_via_ftp(foto_arquivo.read(), nome_arquivo)

                perfil_sac = getattr(request.user, 'motorista_perfil', None)

                cod_ref_str = str(ocorrencia.codigo_referencia or '').strip()
                cod_tms_str = str(ocorrencia.codigo_tms or '').strip()
                desc_upper = str(ocorrencia.descricao or '').upper()

                is_sucesso = (
                    ocorrencia.tipo == 'ENTREGA' or
                    cod_ref_str in ['01', '02', '1', '2'] or
                    cod_tms_str in ['01', '02', '1', '2'] or
                    'REALIZADA' in desc_upper or
                    'ENTREGUE' in desc_upper
                )

                baixa = BaixaNF.objects.create(
                    nota_fiscal=nf,
                    tipo='ENTREGA' if is_sucesso else 'OCORRENCIA',
                    ocorrencia=ocorrencia,
                    comprovante_foto_url=url_final_foto,
                    recebedor=recebedor_in if recebedor_in else "FINALIZADO PELO SAC",
                    observacao=f"[BAIXA SAC] {observacao}",
                    motivo_baixa=motivo_baixa,
                    autor_baixa=perfil_sac,
                    data_baixa=timezone.now()
                )

                nf.status = 'BAIXADA' if is_sucesso else 'OCORRENCIA'
                nf.save()

                # Integração com TMS
                from configuracao.utils import get_config
                config = get_config()
                if config.enviar_tms:
                    if nf.tipo_operacao == 'COLETA':
                        enviar_coleta_esl_task.delay(baixa.id)
                    elif nf.chave_acesso:
                        enviar_baixa_esl_task.delay(baixa.id)
                    else:
                        enviar_baixa_minuta_task.delay(baixa.id)

                return Response({
                    'status': 'sucesso',
                    'mensagem': f'Nota {nf.numero_nota} baixada com sucesso pelo SAC e enviada para integração com o TMS.'
                })

        except NotaFiscal.DoesNotExist:
            return Response({'erro': 'Nota fiscal não localizada.'}, status=404)
        except Exception as e:
            return Response({'erro': str(e)}, status=400)
