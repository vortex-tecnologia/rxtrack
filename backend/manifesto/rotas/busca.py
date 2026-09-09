# manifesto/rotas/busca.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from usuarios.models import Motorista, Filial
from manifesto.models import ManifestoBuscaLog, Manifesto
from manifesto.tasks import buscar_manifesto_completo_task
import logging

logger = logging.getLogger(__name__)

class BuscarManifestoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            motorista = getattr(request.user, 'motorista_perfil', None)
            if not motorista:
                logger.warning(f"Usuário {request.user.username} não possui motorista_perfil vinculado.")
                return Response({'erro': 'Seu usuário não possui um perfil de motorista vinculado.'}, status=403)

            numero = request.data.get('numero_manifesto')
            if not numero:
                return Response({'erro': 'Número do manifesto é obrigatório'}, status=400)

            # Normalização: remove espaços e zeros à esquerda para batimento flexível
            numero_str = str(numero).strip()
            numero_limpo = numero_str.lstrip('0')
            numeros_tentativa = [numero_str]
            if numero_limpo and numero_limpo != numero_str:
                numeros_tentativa.append(numero_limpo)

            with transaction.atomic():
                # 1. VERIFICAÇÃO NO BANCO LOCAL
                manifesto_existente = Manifesto.objects.filter(
                    numero_manifesto__in=numeros_tentativa
                ).first()

                if manifesto_existente:
                    # CASO 1: CANCELADO
                    if manifesto_existente.status == 'CANCELADO':
                        return Response({
                            'erro': f"O Manifesto #{manifesto_existente.numero_manifesto} está CANCELADO no sistema e não pode ser iniciado."
                        }, status=400)

                    # CASO 2: FINALIZADO (ou com trava finalizado=True)
                    if manifesto_existente.finalizado or manifesto_existente.status == 'FINALIZADO':
                        notas_pendentes_qs = NotaFiscal.objects.filter(
                            manifesto=manifesto_existente,
                            status='PENDENTE',
                            baixa_info__isnull=True
                        )
                        qtd_pendentes = notas_pendentes_qs.count()

                        if qtd_pendentes > 0:
                            # Possui notas pendentes: verifica janela de 24h
                            from django.utils import timezone
                            from datetime import timedelta
                            limite_24h = timezone.now() - timedelta(hours=24)
                            data_ref_fim = manifesto_existente.data_finalizacao or manifesto_existente.data_criacao
                            recente = bool(data_ref_fim and data_ref_fim >= limite_24h)

                            if not recente:
                                return Response({
                                    'erro': f"O Manifesto #{manifesto_existente.numero_manifesto} foi finalizado há mais de 24 horas e não pode ser reaberto."
                                }, status=400)

                            # Verifica se o motorista já possui outro manifesto ativo
                            outro_ativo = Manifesto.objects.filter(
                                motorista=motorista,
                                status='EM_TRANSPORTE',
                                finalizado=False
                            ).exclude(id=manifesto_existente.id).first()

                            if outro_ativo:
                                return Response({
                                    'erro': f"O Manifesto #{manifesto_existente.numero_manifesto} possui {qtd_pendentes} nota(s) pendente(s), mas você já está com o manifesto #{outro_ativo.numero_manifesto} ativo em transporte. Finalize-o antes de reabrir este."
                                }, status=400)

                            # Reabre o manifesto
                            manifesto_existente.motorista = motorista
                            manifesto_existente.status = 'EM_TRANSPORTE'
                            manifesto_existente.finalizado = False
                            manifesto_existente.data_finalizacao = None
                            manifesto_existente.save(update_fields=['motorista', 'status', 'finalizado', 'data_finalizacao'])

                            ManifestoBuscaLog.objects.update_or_create(
                                numero_manifesto=manifesto_existente.numero_manifesto,
                                motorista=motorista,
                                defaults={'status': 'PROCESSADO', 'mensagem_erro': None}
                            )

                            logger.info(f"PWA: Manifesto #{manifesto_existente.numero_manifesto} reaberto via busca local com {qtd_pendentes} notas pendentes.")
                            return Response({
                                "mensagem": f"Manifesto #{manifesto_existente.numero_manifesto} reaberto com sucesso! ({qtd_pendentes} nota(s) pendente(s))",
                                "status": "PROCESSADO",
                                "local": True
                            }, status=200)
                        else:
                            # Totalmente concluído
                            return Response({
                                'erro': f"O Manifesto #{manifesto_existente.numero_manifesto} já se encontra FINALIZADO no sistema (todas as notas baixadas)."
                            }, status=400)

                    # CASO 3: EM TRANSPORTE
                    if manifesto_existente.status == 'EM_TRANSPORTE':
                        if manifesto_existente.motorista == motorista:
                            return Response({
                                "mensagem": f"Manifesto #{manifesto_existente.numero_manifesto} já está ativo na sua rota!",
                                "status": "PROCESSADO",
                                "local": True
                            }, status=200)
                        else:
                            outro_nome = manifesto_existente.motorista.nome_completo if manifesto_existente.motorista else "outro motorista"
                            return Response({
                                'erro': f"O Manifesto #{manifesto_existente.numero_manifesto} já está em rota com o motorista {outro_nome}."
                            }, status=400)

                    # CASO 4: AGUARDANDO
                    if manifesto_existente.status == 'AGUARDANDO':
                        outro_ativo = Manifesto.objects.filter(
                            motorista=motorista,
                            status='EM_TRANSPORTE',
                            finalizado=False
                        ).exclude(id=manifesto_existente.id).first()

                        if outro_ativo:
                            return Response({
                                'erro': f"Você já possui o manifesto #{outro_ativo.numero_manifesto} em transporte ativo. Finalize-o antes de iniciar um novo."
                            }, status=400)

                        manifesto_existente.motorista = motorista
                        manifesto_existente.status = 'EM_TRANSPORTE'
                        manifesto_existente.finalizado = False
                        manifesto_existente.data_finalizacao = None
                        manifesto_existente.save(update_fields=['motorista', 'status', 'finalizado', 'data_finalizacao'])

                        ManifestoBuscaLog.objects.update_or_create(
                            numero_manifesto=manifesto_existente.numero_manifesto,
                            motorista=motorista,
                            defaults={'status': 'PROCESSADO', 'mensagem_erro': None}
                        )

                        logger.info(f"PWA: Manifesto #{manifesto_existente.numero_manifesto} ativado via busca local.")
                        return Response({
                            "mensagem": f"Manifesto #{manifesto_existente.numero_manifesto} localizado e ativado com sucesso!",
                            "status": "PROCESSADO",
                            "local": True
                        }, status=200)

                # 2. NÃO EXISTE NO BANCO LOCAL -> Sincronização externa com TMS ESL
                # Antes de disparar busca no TMS, verifica se motorista já tem transporte ativo
                outro_ativo = Manifesto.objects.filter(
                    motorista=motorista,
                    status='EM_TRANSPORTE',
                    finalizado=False
                ).first()

                if outro_ativo:
                    return Response({
                        'erro': f"Você já possui o manifesto #{outro_ativo.numero_manifesto} ativo em transporte. Finalize-o antes de buscar um novo."
                    }, status=400)

                log, created = ManifestoBuscaLog.objects.update_or_create(
                    numero_manifesto=numero_str,
                    motorista=motorista,
                    defaults={
                        'status': 'AGUARDANDO',
                        'mensagem_erro': None,
                        'payload': None
                    }
                )
                logger.info(f"PWA: Log {'criado' if created else 'atualizado'} para manifesto {numero_str}. ID={log.id}")
                buscar_manifesto_completo_task.delay(log.id)

                return Response({
                    'status': 'AGUARDANDO',
                    'log_id': log.id,
                    'local': False,
                    'mensagem': 'Consultando manifesto no TMS ESL...'
                }, status=202)

        except Exception as e:
            logger.error(f"Erro na BuscarManifestoView (PWA): {str(e)}")
            return Response({'erro': str(e)}, status=500)

class ImportarManifestoAdminView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        numero = request.data.get('numero_manifesto')
        motorista_id = request.data.get('motorista_id')

        logger.info(f"ADMIN: Requisição de importação: manifesto={numero}, motorista={motorista_id}")

        if not numero or not motorista_id:
            return Response({'erro': 'Número do manifesto e motorista são obrigatórios'}, status=400)

        try:
            motorista = Motorista.objects.get(id=motorista_id)
            
            # Verificar se motorista já tem manifesto ativo
            if Manifesto.objects.filter(motorista=motorista, status='EM_TRANSPORTE').exists():
                return Response({'erro': 'Este motorista já possui um manifesto em transporte ativo.'}, status=400)

            # Criar ou atualizar log de busca
            log, _ = ManifestoBuscaLog.objects.update_or_create(
                numero_manifesto=numero,
                motorista=motorista,
                defaults={
                    'status': 'AGUARDANDO',
                    'mensagem_erro': None
                }
            )

            # Disparar Task Celery (apenas log_id conforme assinatura da task)
            buscar_manifesto_completo_task.delay(log.id)

            return Response({
                'status': 'AGUARDANDO', 
                'log_id': log.id,
                'mensagem': 'Importação iniciada com sucesso!'
            }, status=202)

        except Motorista.DoesNotExist:
            return Response({'erro': 'Motorista não encontrado'}, status=404)
        except Exception as e:
            logger.error(f"Erro na importação admin: {str(e)}")
            return Response({'erro': str(e)}, status=500)

class CheckImportStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, log_id):
        try:
            log = ManifestoBuscaLog.objects.get(id=log_id)
            return Response({
                'status': log.status,
                'mensagem_erro': log.mensagem_erro
            })
        except ManifestoBuscaLog.DoesNotExist:
            return Response({'erro': 'Log não encontrado'}, status=404)

class ListarTodosLogsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logs = ManifestoBuscaLog.objects.select_related('motorista').all().order_by('-atualizado_em')
        data = []
        for log in logs:
            data.append({
                'id': log.id,
                'data': log.criado_em.strftime('%d/%m/%Y %H:%M'),
                'numero': log.numero_manifesto,
                'motorista': log.motorista.nome_completo if log.motorista else "N/A",
                'status': log.status,
                'quantidade_notas': log.quantidade_notas,
                'erro': log.mensagem_erro
            })
        return Response(data)