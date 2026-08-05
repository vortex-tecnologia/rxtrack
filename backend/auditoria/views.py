from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Q, F, ExpressionWrapper, DateTimeField
from manifesto.models import Manifesto, NotaFiscal, BaixaNF, Ocorrencia
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from manifesto.tasks import enviar_baixa_esl_task

@method_decorator(login_required, name='dispatch')
class AuditoriaDashboardView(TemplateView):
    template_name = 'desktop/auditoria_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Filtros básicos
        filial_id = self.request.GET.get('filial')
        motorista_id = self.request.GET.get('motorista')
        
        # Busca filial do usuário
        usuario_filial = None
        if self.request.user.is_authenticated:
            try:
                from usuarios.models import Motorista
                perfil = Motorista.objects.get(user=self.request.user)
                usuario_filial = perfil.filial
            except Exception:
                pass
                
        # Manifestos Ativos (EM_TRANSPORTE)
        manifestos_ativos = Manifesto.objects.filter(status='EM_TRANSPORTE').select_related('motorista', 'filial')
        
        if filial_id == 'todas':
            pass
        elif filial_id:
            manifestos_ativos = manifestos_ativos.filter(motorista__filial_id=filial_id)
        elif usuario_filial:
            manifestos_ativos = manifestos_ativos.filter(motorista__filial=usuario_filial)
        else:
            manifestos_ativos = manifestos_ativos.none()
            
        if motorista_id:
            manifestos_ativos = manifestos_ativos.filter(motorista_id=motorista_id)

        # Adiciona contagem de notas
        manifestos_ativos = manifestos_ativos.annotate(
            total_notas=Count('notas_fiscais'),
            notas_pendentes=Count('notas_fiscais', filter=Q(notas_fiscais__status='PENDENTE')),
            notas_baixadas=Count('notas_fiscais', filter=Q(notas_fiscais__status__in=['BAIXADA', 'OCORRENCIA']))
        )

        # Lógica de "Stale" (Parado)
        agora = timezone.now()
        limite_stale = agora - timedelta(hours=4)
        
        manifestos_data = []
        for m in manifestos_ativos:
            status_cor = 'success'
            if m.notas_pendentes > 0:
                if not m.ultimo_acesso or m.ultimo_acesso < limite_stale:
                    status_cor = 'danger' # Crítico: Notas pendentes e sem acesso há 4h
                elif m.ultimo_acesso < (agora - timedelta(hours=2)):
                    status_cor = 'warning' # Atenção: Sem acesso há 2h
            
            # Progresso
            progresso = 0
            if m.total_notas > 0:
                progresso = int((m.notas_baixadas / m.total_notas) * 100)

            manifestos_data.append({
                'obj': m,
                'status_cor': status_cor,
                'progresso': progresso,
                'horas_sem_sinal': int((agora - m.ultimo_acesso).total_seconds() / 3600) if m.ultimo_acesso else None
            })

        context['manifestos'] = manifestos_data
        context['total_ativos'] = manifestos_ativos.count()
        context['total_criticos'] = sum(1 for d in manifestos_data if d['status_cor'] == 'danger')
        
        # Penalidades (Motorista Desleixo)
        penalidades_qs = BaixaNF.objects.filter(motivo_baixa='MOTORISTA_DESLEIXO')
        
        if filial_id == 'todas':
            pass
        elif filial_id:
            penalidades_qs = penalidades_qs.filter(nota_fiscal__manifesto__motorista__filial_id=filial_id)
        elif usuario_filial:
            penalidades_qs = penalidades_qs.filter(nota_fiscal__manifesto__motorista__filial=usuario_filial)
        else:
            penalidades_qs = penalidades_qs.none()
            
        context['total_penalidades'] = penalidades_qs.count()
        
        # Top 5 Motoristas com mais penalidades
        context['top_penalidades'] = penalidades_qs.values(
            'nota_fiscal__manifesto__motorista__nome_completo'
        ).annotate(
            total=Count('id')
        ).order_by('-total')[:5]

        context['sem_filial'] = not bool(usuario_filial)

        return context

from rest_framework.parsers import MultiPartParser, FormParser
from manifesto.rotas.baixa import upload_via_ftp
from manifesto.tasks import enviar_baixa_esl_task, enviar_baixa_minuta_task, enviar_coleta_esl_task

class RegistrarBaixaManualSACView(APIView):
    """
    Endpoint exclusivo para o SAC realizar baixas forçadas pelo painel de auditoria.
    Suporta envio de comprovante/foto, validações de ocorrências por tipo de documento e despacho TMS.
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

                # --- REGRA DE VALIDAÇÃO DE FOTO ---
                # Para Entregas (NF-e/CT-e), ocorrências 01 ou 02 EXIGEM foto
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

                # Identifica o perfil do SAC
                perfil_sac = getattr(request.user, 'motorista_perfil', None)

                # Registro da Baixa
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

                # Integração Inteligente com o TMS conforme o tipo
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
